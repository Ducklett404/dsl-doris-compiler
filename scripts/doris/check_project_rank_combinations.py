"""Rank/lookup/count SQL, complete result and bounded explanation comparison.

Default execution is portable synthetic evidence. Native fixtures live only in
an isolated randomly named database. Saved official results are independently
checked against raw locked observations, never treated as a gold standard.
"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
import secrets
import duckdb
from validate_project_sources import ROOT, WslDoris, digest
from project_rank_reference import cases, matrix_document, reference, security_key, load, observation
from project_matrix_reference import assess
from project_field_reference import KEYS,configure_reference_connection
from check_official_field_acceptance import RAW_COLUMNS
from check_project_availability import probe, inputs, expected_reasons
from project_portable_decimal import install_semantic_views, adapt_compiler_sql


def fixture():
    basic = []; extension = []; names = {}; histories = {}
    for index in range(54):
        market = (0, 1, 103)[index % 3]; code = f'{index // 3 + 1:06}'
        length = (1, 2, 3, 4, 19, 20, 21, 25)[index % 8]
        days = [str(date(2026, 4, 14) - timedelta(days=(length - j - 1) * 41)) for j in range(length)]
        if index < 42:
            days = ['2006-01-04', '2018-08-20'] + days
        # Missing target quote on evaluation date; future rows are irrelevant.
        if code == '000003':
            days[-1] = '2026-04-13'
        if index % 7 == 0 and len(days) > 1 and days[-1] == '2026-04-14':
            days[-2] = '2026-04-13'
        history = []
        for j, day in enumerate(days):
            price = (index // 3 % 5 + 1) * 10000  # Exact ties across three markets.
            raw = dict.fromkeys(RAW_COLUMNS, 10000)
            raw.update(lastPx=price, preClosePx=10000, openPx=price, highPx=price + 10000,
                lowPx=price - 10000, closePx=price, volume=100, turnover=price * 100,
                totalShare=100000, listedShare=50000, qfqMulti=2, qfqAdd=3, hfqMulti=3, hfqAdd=-2)
            current = j == len(days) - 1
            if index < len(RAW_COLUMNS) and current:
                raw[RAW_COLUMNS[index]] = None
            if index % 11 == 0:
                raw['volume'] = 0
            if index % 13 == 0:
                raw['preClosePx'] = 0
            if code == '000001':
                raw.update(closePx=(market + 1) * 10000, lastPx=(market + 1) * 10000,
                           volume=100, turnover=(market + 1) * 10000)
            if code == '000002' and current:
                raw['closePx'] = None
            has_ext = not (index % 9 == 0 and current)
            # Unknown historical predicate does not count; legitimate negatives do.
            net = -999999 if index % 8 == 0 and j % 2 == 0 else None if index % 10 == 0 and j % 3 == 0 else (-10 if index % 2 == 0 else 10)
            raw['net'] = net if has_ext else None
            history.append(observation(day, raw, has_ext))
            basic.append((market, code, day, *(raw[k] for k in RAW_COLUMNS)))
            if has_ext:
                extension.append((market, code, day, net))
        histories[(str(market), code)] = history
        names[(str(market), code)] = '目标深零一' if market == 0 and code == '000001' else f'合成证券{market}-{code}'
        basic.append((market, code, '2026-04-15', *([999999] * len(RAW_COLUMNS))))
    # A 20-row history with only three legitimate negative hits, remaining
    # predicate inputs NULL/sentinel. EXIST=3 is true but COUNT_INPUT unavailable.
    key = ('103', '009999'); history = []
    for j in range(20):
        day = str(date(2026, 4, 14) - timedelta(days=(19 - j) * 41))
        raw = dict.fromkeys(RAW_COLUMNS, 10000)
        raw.update(volume=100, turnover=10000, qfqMulti=1, qfqAdd=0, hfqMulti=1, hfqAdd=0,
                   net=-10 if j >= 17 else None if j % 2 else -999999)
        history.append(observation(day, raw))
        basic.append((103, key[1], day, *(raw[k] for k in RAW_COLUMNS)))
        extension.append((103, key[1], day, raw['net']))
    histories[key] = history; names[key] = '未知不计命中'
    return dict(basic=basic, extension=extension, histories=histories, names=names)


def at_date(data, day):
    return dict(histories={k: [r for r in h if r['date'] <= day] for k, h in data['histories'].items()
                          if any(r['date'] == day for r in h)}, names=data['names'])


def verify_details(quality, case, histories):
    specs = inputs(case)
    # Independent value identities can repeat syntactically (and count's base
    # can also be used directly). Explain each semantic input once.
    specs = list({json.dumps(s, sort_keys=True): s for s in specs}.values())
    for spec in specs:
        if spec['function'] == 'query':
            spec['function'] = 'querydata'
            spec['requiredObservations'] = 0  # Cross-security scalar, no single-security history requirement.
    actual = quality['inputs']; samples = quality['unavailableSamples']; details = quality['sampleDetails']
    checks = dict(sampleOrder=[(d['marketCode'], d['securityCode']) for d in details] == [tuple(s[:2]) for s in samples],
        stableIds=all(re.fullmatch('[0-9a-f]{64}', i['inputId']) for i in actual) and len({i['inputId'] for i in actual}) == len(actual))
    matched = {}
    for meta in actual:
        matches = [s for s in specs if all(s[k] == meta[k] for k in ('function', 'indicator', 'role', 'requiredObservations'))]
        if len(matches) != 1:
            raise AssertionError('Ambiguous/mismatched input definition: ' + str(meta))
        matched[meta['inputId']] = matches[0]
    for sample, detail in zip(samples, details):
        key = tuple(sample[:2])
        checks[str(key) + '-extension'] = detail['currentExtensionMissing'] == (sample[2] == '1')
        checks[str(key) + '-flags'] = [i['inputId'] for i in detail['inputs']] == [i['inputId'] for i, flag in zip(actual, sample[3:]) if flag == '1']
        issue_map = {i['inputId']: i for i in detail['inputs']}
        for meta, flag in zip(actual, sample[3:]):
            if flag != '1':
                continue
            issue = issue_map[meta['inputId']]
            if meta['function'] == 'querydata':
                checks[str(key) + '-query-partial'] = issue['status'] == 'PARTIAL_DETAIL' and [r['code'] for r in issue['reasons']] == ['DETAIL_NOT_SUPPORTED']
            else:
                expected = expected_reasons(matched[meta['inputId']], histories[key])
                observed = sorted(issue['reasons'], key=lambda r: (r['code'], r['indicator'], r['requiredObservations']))
                checks[str(key) + '-' + meta['inputId']] = issue['status'] == 'EXPLAINED' and observed == expected
                if observed != expected:
                    raise AssertionError(json.dumps(dict(case=case['name'], security=key, input=meta, expected=expected, observed=observed), ensure_ascii=False))
    if not all(checks.values()):
        raise AssertionError('Explanation mismatch: ' + str(checks))
    return checks


def portable(suite, java, native=None, adapter_evidence=None):
    data = fixture(); con = duckdb.connect()
    try:
        con.execute('CREATE SCHEMA newzl')
        types = ','.join(k + (' DOUBLE' if k in ('qfqMulti', 'qfqAdd', 'hfqMulti', 'hfqAdd') else ' BIGINT') for k in RAW_COLUMNS)
        con.execute('CREATE TABLE newzl.hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR,bizdate DATE,' + types + ')')
        extra = ['ZJLXMainNetTurInDays', 'ZJLXMainNetTurOutDays', 'ZJLXMainNetTurInSeries', 'ZJLXMainNetTurOutSeries', 'pxMkTopDays', 'mainTurMkTopDays']
        con.execute('CREATE TABLE newzl.hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT,' + ','.join(k + ' BIGINT' for k in extra) + ')')
        con.execute('CREATE TABLE newzl.hsj_stock_code_info(mktcode INT,tgtcode VARCHAR,name VARCHAR,hyBlkRefName VARCHAR)')
        con.executemany('INSERT INTO newzl.hsj_stock_hq_basic VALUES(' + ','.join('?' for _ in range(3 + len(RAW_COLUMNS))) + ')', data['basic'])
        con.executemany('INSERT INTO newzl.hsj_stock_hq_ext(mktcode,tgtcode,bizdate,ZJLXMainNetTur) VALUES(?,?,?,?)', data['extension'])
        codes = [(int(m), code, name) for (m, code), name in data['names'].items()]
        con.executemany('INSERT INTO newzl.hsj_stock_code_info(mktcode,tgtcode,name) VALUES(?,?,?)', codes)
        con.execute("SET schema='newzl'")
        ddl = (ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8').replace('USE newzl;', '')
        if native is None:
            metadata = install_semantic_views(con, ddl)
            if adapter_evidence is not None:
                adapter_evidence.update(metadata)
        else:
            con.execute(ddl)
        if native is None:
            def query(sql, bindings):
                return [[str(v) if v is not None else 'NULL' for v in r] for r in con.execute(adapt_compiler_sql(con, sql, adapter_evidence).replace('`', '"').replace('DATE_FORMAT(', 'STRFTIME('), bindings).fetchall()]
        else:
            from run_correctness import sql_literal, bind_sql
            client, database = native
            client.query((ROOT / 'data/doris/ddl/001_rebuild_tables.sql').read_text(encoding='utf-8').replace('newzl', database).replace('BUCKETS 16', 'BUCKETS 1'))
            client.query((ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8').replace('USE newzl;', 'USE ' + database + ';'))
            def insert(table, columns, rows):
                for start in range(0, len(rows), 100):
                    client.query('INSERT INTO ' + database + '.' + table + '(' + ','.join(columns) + ') VALUES ' + ','.join('(' + ','.join(sql_literal(v) for v in row) + ')' for row in rows[start:start + 100]))
            insert('hsj_stock_hq_basic', ['mktcode', 'tgtcode', 'bizdate', *RAW_COLUMNS], data['basic'])
            insert('hsj_stock_hq_ext', ['mktcode', 'tgtcode', 'bizdate', 'ZJLXMainNetTur'], data['extension'])
            insert('hsj_stock_code_info', ['mktcode', 'tgtcode', 'name'], codes)
            def query(sql, bindings):
                return [list(r) for r in client.query(bind_sql(sql, bindings).replace('newzl.', database + '.'))]
        plans = probe([dict(dsl=c['dsl'], samples=[]) for c in suite], java)
        requests = []; checks = []; sources = []; results = []
        for case, plan in zip(suite, plans):
            source = at_date(data, case['date']); expected = reference(case, source)
            rows = query(plan['sql'], plan['bindings']); results.append(rows); sources.append(source)
            coverage = plan['coverage']; combined = query(coverage['combinedSql'], coverage['bindings']); width = len(coverage['inputs']) + 2
            samples = [r[width:] for r in combined if '1' in r[width + 2:]]
            quality = dict(inputs=[dict(i, unavailableSecurities=int(combined[0][j + 2])) for j, i in enumerate(coverage['inputs'])],
                observedSecurities=int(combined[0][0]), currentMissingExtensionRows=int(combined[0][1]), unavailableSamples=samples,
                coverageStatus=expected['coverageStatus'], validationLevel='PROJECT_SCOPED', officialAcceptanceEligible=False)
            compared = assess(dict(rows=rows, truncated=False, dataQuality=quality), expected)
            if not all(compared.values()):
                raise AssertionError(json.dumps(dict(case=case['name'], checks=compared, expected=expected['rows'], actual=rows), ensure_ascii=False))
            # Re-execution proves complete deterministic ordering, including LIMIT ties.
            if query(plan['sql'], plan['bindings']) != rows:
                raise AssertionError('Non-deterministic ordered result: ' + case['name'])
            checks.append(compared); requests.append(dict(dsl=case['dsl'], samples=samples))
        fetches = probe(requests, java)
        for request, fetch in zip(requests, fetches):
            if request['samples']:
                request['rawRows'] = query(fetch['fetch']['sql'], fetch['fetch']['bindings'])
        explained = probe(requests, java); output = []
        for case, request, result, source, rows, compared in zip(suite, requests, explained, sources, results, checks):
            details = verify_details(dict(inputs=result['coverage']['inputs'], sampleDetails=result['details'], unavailableSamples=request['samples']), case, source['histories'])
            output.append(dict(name=case['name'], status='PASS', checks=compared, explanationChecks=details,
                               rows=rows, samples=len(request['samples']), sampleDetails=result['details']))
        return output
    finally:
        con.close()


def saved_execution(suite, args, report):
    if args.certificate is None:
        raise ValueError('A project certificate is required to verify source identity')
    certificate = json.loads(args.certificate.read_text(encoding='utf-8'))
    run = json.loads((args.execution_dir / 'result.json').read_text(encoding='utf-8'))
    executed = json.loads((args.execution_dir / 'matrix.json').read_text(encoding='utf-8'))
    if run['status'] != 'PASS' or run['jarSha256'] != report['jarSha256'] or run['certificateSha256'] != digest(args.certificate) or executed != json.loads(json.dumps(suite, ensure_ascii=False)):
        raise AssertionError('Execution artifacts or frozen matrix identity mismatch')
    rounds = run.get('rounds', 1)
    if len(run['executions']) != len(suite) * rounds or any(e['status'] != 'PASS' for e in run['executions']):
        raise AssertionError('Incomplete execution matrix')
    result = []; lookup = {c['name']: c for c in suite}
    with duckdb.connect(str(args.database), read_only=True) as con:
        report['referenceResources']=configure_reference_connection(con,args.database)
        if con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone() != (certificate['snapshotId'], certificate['manifestSha256'], 'FAIL'):
            raise AssertionError('Locked raw audit source identity mismatch')
        for day in sorted({c['date'] for c in suite}):
            source = load(con, day, 64)
            for execution in run['executions']:
                case = lookup[execution['case']]
                if case['date'] != day:
                    continue
                artifact = Path(execution['artifact'])
                if artifact.is_absolute() or '..' in artifact.parts:
                    raise ValueError('Unsafe execution artifact path')
                data = json.loads((args.execution_dir / artifact).read_text(encoding='utf-8'))
                compared = assess(data, reference(case, source))
                if not all(compared.values()):
                    raise AssertionError('Native raw result/order/coverage mismatch: ' + case['name'] + ' ' + str(compared))
                keys = [tuple(s[:2]) for s in data['dataQuality']['unavailableSamples']]
                if keys:
                    conditions = ' OR '.join('(mktcode=? AND tgtcode=?)' for _ in keys)
                    rows = con.execute('SELECT mktcode,tgtcode,bizdate,ZJLXMainNetTur FROM newzl.hsj_stock_hq_ext WHERE bizdate<=? AND (' + conditions + ')', [day, *[v for k in keys for v in k]]).fetchall()
                    raw_net = {(str(m), code, str(d)): net for m, code, d, net in rows}
                    for key in keys:
                        for row in source['histories'][key]:
                            row['rawNet'] = raw_net.get((*key, row['date']))
                details = verify_details(data['dataQuality'], case, source['histories'])
                result.append(dict(name=case['name'], round=execution['round'], status='PASS', checks=compared, explanationChecks=details))
            del source
    report.update(executionSha256=digest(args.execution_dir / 'result.json'), certificateSha256=digest(args.certificate))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--matrix-output', type=Path)
    parser.add_argument('--matrix', type=Path, default=ROOT / 'config/acceptance/project-rank-matrix-v1.json')
    parser.add_argument('--java', default='java'); parser.add_argument('--native-fixture', action='store_true')
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9'); parser.add_argument('--execution-dir', type=Path)
    parser.add_argument('--certificate', type=Path); parser.add_argument('--database', '--reference-database', dest='database', type=Path, default=ROOT / 'target/data-audit/acceptance-a0f7260.duckdb')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve prior evidence; use a fresh output file')
    suite = cases(); canonical = json.loads(json.dumps(matrix_document(), ensure_ascii=False))
    if json.loads(args.matrix.read_text(encoding='utf-8')) != canonical:
        raise AssertionError('Frozen rank matrix differs from independent definitions')
    if args.matrix_output:
        if args.matrix_output.exists():
            raise ValueError('Preserve matrix evidence')
        args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
        args.matrix_output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = dict(purpose='SYNTHETIC_PORTABLE_RANK_LOOKUP_COUNT_COMBINATIONS', officialAcceptanceEligible=False,
        definitionAuthority='PROJECT_INTERNAL_FROZEN_FUNCTION_SEMANTICS', jarSha256=digest(ROOT / 'target/dsl-doris-compiler.jar'),
        oracleSha256=digest(ROOT / 'scripts/doris/project_rank_reference.py'), runnerSha256=digest(Path(__file__)),
        matrixSha256=digest(args.matrix), matrixCases=len(suite), checks=[],
        portableDecimalAdapter=dict(used=not(args.native_fixture or args.execution_dir),
            implementationSha256=digest(ROOT / 'scripts/doris/project_portable_decimal.py'),
            evidenceType='PORTABLE_DORIS_DECIMAL_EMULATION',notNativeDorisProof=True))
    try:
        if args.native_fixture:
            if args.execution_dir:
                raise ValueError('Native synthetic and official data evidence must be separate')
            client = WslDoris(args.distribution, 'dsl-doris-official'); database = 'dsl_rank_' + secrets.token_hex(6)
            before = client.query('SELECT * FROM newzl.data_snapshot_registry'); created = False
            try:
                client.query('CREATE DATABASE ' + database); created = True
                report.update(purpose='SYNTHETIC_NATIVE_RANK_LOOKUP_COUNT_COMBINATIONS', fixtureDatabase=database)
                report['checks'] = portable(suite, args.java, (client, database))
                if client.query('SELECT * FROM newzl.data_snapshot_registry') != before:
                    raise AssertionError('Official snapshot registry changed')
            finally:
                if created:
                    client.query('DROP DATABASE ' + database)
                report['fixtureCleanup'] = 'DONE'
        elif args.execution_dir:
            report['purpose'] = 'PROJECT_NATIVE_RANK_LOOKUP_COUNT_RAW_COMPARISON'
            report['checks'] = saved_execution(suite, args, report)
        else:
            report['checks'] = portable(suite, args.java, adapter_evidence=report['portableDecimalAdapter'])
        if digest(ROOT / 'target/dsl-doris-compiler.jar') != report['jarSha256']:
            raise AssertionError('Compiler JAR changed during validation')
    except Exception as error:
        report['fatalError'] = str(error); raise
    finally:
        report.update(status='FAIL' if 'fatalError' in report else 'PASS', passed=sum(c['status'] == 'PASS' for c in report['checks']), total=len(report['checks']))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'passed', 'total', 'matrixCases')}))


if __name__ == '__main__':
    main()
