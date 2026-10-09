"""T1 combined values/results/coverage/explanations, portable or isolated Doris."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import tempfile

import duckdb

from check_official_field_acceptance import RAW_COLUMNS
from check_project_availability import probe, verify
from project_combination_reference import MATRIX, cases, fixture, reference, source_on
from project_field_reference import load,configure_reference_connection
from project_matrix_reference import assess
from validate_project_sources import ROOT, WslDoris, digest
from project_portable_decimal import install_semantic_views, adapt_compiler_sql


def compiled_paths(suite, java):
    with tempfile.TemporaryDirectory(prefix='project-combination-paths-') as folder:
        path = Path(folder) / 'queries.json'
        path.write_text(json.dumps([c['dsl'] for c in suite], ensure_ascii=False), encoding='utf-8')
        result = subprocess.run([java, '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8',
            '-Dsun.stderr.encoding=UTF-8', '-cp', str(ROOT / 'target/dsl-doris-compiler.jar'),
            str(ROOT / 'scripts/doris/ProjectWindowCompile.java'), str(path)],
            capture_output=True, text=True, encoding='utf-8', errors='strict', timeout=70, check=True)
        outputs = json.loads(result.stdout)
    if len(outputs) != len(suite):
        raise AssertionError('Incomplete project/full-scan compile batch')
    return outputs


def portable(suite, java, native=None, adapter_evidence=None):
    """Run all cases on raw fixtures and independently verify every returned key.

    `native=(client, unique_database)` uses the same raw fixtures in isolated
    Doris tables. The caller owns database creation and cleanup.
    """
    fixtures = fixture()
    with duckdb.connect() as con:
        con.execute('CREATE SCHEMA newzl')
        types = ','.join(k + ' ' + ('DOUBLE' if k in ('qfqMulti', 'qfqAdd', 'hfqMulti', 'hfqAdd') else 'BIGINT') for k in RAW_COLUMNS)
        con.execute('CREATE TABLE newzl.hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR,bizdate DATE,' + types + ')')
        ext_columns = ['ZJLXMainNetTurInDays', 'ZJLXMainNetTurOutDays',
            'ZJLXMainNetTurInSeries', 'ZJLXMainNetTurOutSeries', 'pxMkTopDays', 'mainTurMkTopDays']
        con.execute('CREATE TABLE newzl.hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT,' + ','.join(k + ' BIGINT' for k in ext_columns) + ')')
        con.executemany('INSERT INTO newzl.hsj_stock_hq_basic VALUES(' + ','.join('?' for _ in range(3 + len(RAW_COLUMNS))) + ')', fixtures['sourceRows'])
        con.executemany('INSERT INTO newzl.hsj_stock_hq_ext(mktcode,tgtcode,bizdate,ZJLXMainNetTur) VALUES(?,?,?,?)', fixtures['extensionRows'])
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
                return [[str(v) if v is not None else 'NULL' for v in row]
                    for row in con.execute(adapt_compiler_sql(con, sql, adapter_evidence).replace('`', '"').replace('DATE_FORMAT(', 'STRFTIME('), bindings).fetchall()]
        else:
            client, database = native
            from run_correctness import sql_literal, bind_sql
            client.query((ROOT / 'data/doris/ddl/001_rebuild_tables.sql').read_text(encoding='utf-8').replace('newzl', database).replace('BUCKETS 16', 'BUCKETS 1'))
            client.query((ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8').replace('USE newzl;', 'USE ' + database + ';'))

            def insert(table, columns, rows):
                for start in range(0, len(rows), 100):
                    client.query('INSERT INTO ' + database + '.' + table + ' (' + ','.join(columns) + ') VALUES ' + ','.join('(' + ','.join(sql_literal(v) for v in row) + ')' for row in rows[start:start + 100]))
            insert('hsj_stock_hq_basic', ['mktcode', 'tgtcode', 'bizdate', *RAW_COLUMNS], fixtures['sourceRows'])
            insert('hsj_stock_hq_ext', ['mktcode', 'tgtcode', 'bizdate', 'ZJLXMainNetTur'], fixtures['extensionRows'])

            def query(sql, bindings):
                return [list(row) for row in client.query(bind_sql(sql, bindings).replace('newzl.', database + '.'))]

        paths = compiled_paths(suite, java)
        plans = probe([dict(dsl=c['dsl'], samples=[]) for c in suite], java)
        requests, sources, expected_list, result_rows, result_checks = [], [], [], [], []
        if len(plans) != len(suite):
            raise AssertionError('Compiler returned an incomplete plan batch')
        for case, plan, alternatives in zip(suite, plans, paths):
            source = source_on(fixtures, case['date'])
            expected = reference(case, source)
            rows = query(plan['sql'], plan['bindings'])
            coverage = plan['coverage']
            combined = query(coverage['combinedSql'], coverage['bindings'])
            if not combined:
                raise AssertionError('Combined diagnostics returned no aggregate row')
            width = len(coverage['inputs']) + 2
            counts = combined[0][:width]
            samples = [row[width:] for row in combined if '1' in row[width + 2:]]
            observed = int(counts[0])
            quality = dict(inputs=[dict(i, unavailableSecurities=int(counts[j + 2])) for j, i in enumerate(coverage['inputs'])],
                observedSecurities=observed, currentMissingExtensionRows=int(counts[1]),
                unavailableSamples=samples, coverageStatus='NO_OBSERVATIONS' if observed == 0 else 'PARTIAL_INPUTS' if any(int(c) for c in counts[1:]) else 'COMPLETE_QUERY_INPUTS',
                validationLevel='PROJECT_SCOPED', officialAcceptanceEligible=False)
            checks = assess(dict(rows=rows, truncated=False, dataQuality=quality), expected)
            for mode, compiled in alternatives.items():
                alternative_rows = query(compiled['sql'], compiled['bindings'])
                checks[mode + 'RowsEqual'] = alternative_rows == expected['rows']
                alternate = compiled['coveragePlan']
                alternate_combined = query(alternate['combinedSql'], alternate['bindings'])
                alternate_width = len(alternate['inputs']) + 2
                if not alternate_combined:
                    raise AssertionError('No diagnostic aggregate for ' + mode)
                alternate_counts = alternate_combined[0][:alternate_width]
                alternate_samples = [r[alternate_width:] for r in alternate_combined if '1' in r[alternate_width + 2:]]
                alternate_observed = int(alternate_counts[0])
                alternate_quality = dict(inputs=[dict(i, unavailableSecurities=int(alternate_counts[j + 2])) for j, i in enumerate(alternate['inputs'])],
                    observedSecurities=alternate_observed, currentMissingExtensionRows=int(alternate_counts[1]),
                    unavailableSamples=alternate_samples,
                    coverageStatus='NO_OBSERVATIONS' if alternate_observed == 0 else 'PARTIAL_INPUTS' if any(int(c) for c in alternate_counts[1:]) else 'COMPLETE_QUERY_INPUTS',
                    validationLevel='PROJECT_SCOPED', officialAcceptanceEligible=False)
                alternate_checks = assess(dict(rows=alternative_rows, truncated=False, dataQuality=alternate_quality), expected)
                checks.update({mode + '-' + key: value for key, value in alternate_checks.items()})
                checks[mode + 'CombinedDiagnosticsStable'] = all(r[:alternate_width] == alternate_counts for r in alternate_combined)
            checks['combinedDiagnosticsStable'] = all(row[:width] == counts for row in combined) and 1 <= len(combined) <= 20
            if not all(checks.values()):
                raise AssertionError(json.dumps(dict(case=case['name'], checks=checks, actual=rows, expected=expected['rows'],
                    actualDataQuality=quality, expectedObserved=expected['observed'],
                    expectedInputs=[dict(function=i['function'], indicator=i['indicator'], unavailableSecurities=len(i['missing'])) for i in expected['inputs']]), ensure_ascii=False))
            requests.append(dict(dsl=case['dsl'], samples=samples))
            sources.append(source)
            expected_list.append(expected)
            result_rows.append(rows)
            result_checks.append(checks)
        fetches = probe(requests, java)
        for request, fetch in zip(requests, fetches):
            if request['samples']:
                request['rawRows'] = query(fetch['fetch']['sql'], fetch['fetch']['bindings'])
        explained = probe(requests, java)
        if len(fetches) != len(suite) or len(explained) != len(suite):
            raise AssertionError('Incomplete explanation batch')
        result = []
        for case, request, output, source, expected, rows, checks in zip(suite, requests, explained, sources, expected_list, result_rows, result_checks):
            quality = dict(inputs=output['coverage']['inputs'], sampleDetails=output['details'], unavailableSamples=request['samples'])
            checks.update(verify(quality, case, source['histories']))
            result.append(dict(name=case['name'], status='PASS', checks=checks, rows=rows,
                expectedRows=expected['rows'], observedSecurities=expected['observed'],
                currentMissingExtensionRows=len(expected['missingExtension']),
                expectedInputs=[dict(function=i['function'], indicator=i['indicator'], unavailableSecurities=len(i['missing'])) for i in expected['inputs']],
                coverageStatus=expected['coverageStatus'], samples=len(request['samples']), details=output['details']))
        return result


def execution_checks(suite, folder, certificate, java, audit_db):
    run = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
    matrix = json.loads((folder / 'matrix.json').read_text(encoding='utf-8'))
    if (run['status'] != 'PASS' or run['jarSha256'] != digest(ROOT / 'target/dsl-doris-compiler.jar')
            or run['certificateSha256'] != digest(certificate) or matrix != suite
            or len(run['executions']) != len(suite) * run['rounds']
            or any(e['status'] != 'PASS' for e in run['executions'])):
        raise AssertionError('Execution matrix, certificate, JAR or PASS evidence mismatch')
    cert = json.loads(certificate.read_text(encoding='utf-8'))
    output = []
    lookup = {c['name']: c for c in suite}
    with duckdb.connect(str(audit_db), read_only=True) as con:
        configure_reference_connection(con,audit_db)
        if con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone() != (cert['snapshotId'], cert['manifestSha256'], 'FAIL'):
            raise AssertionError('Independent raw source lock differs from certificate')
        for day in sorted({c['date'] for c in suite}):
            source = load(con, day, 64)
            for entry in run['executions']:
                case = lookup[entry['case']]
                if case['date'] != day:
                    continue
                data = json.loads((folder / entry['artifact']).read_text(encoding='utf-8'))
                expected = reference(case, source)
                checks = assess(data, expected)
                checks.update(verify(data['dataQuality'], case, source['histories']))
                if not all(checks.values()):
                    raise AssertionError('Independent complete result/coverage/explanation mismatch: ' + case['name'])
                output.append(dict(name=case['name'], round=entry['round'], status='PASS', checks=checks,
                    securities=len(expected['rows']), samples=len(expected['sampleKeys'])))
            del source
    return output


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--matrix', type=Path, default=MATRIX)
    p.add_argument('--matrix-output', type=Path)
    p.add_argument('--java', default='java')
    p.add_argument('--native-fixture', action='store_true')
    p.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    p.add_argument('--execution-dir', type=Path)
    p.add_argument('--certificate', type=Path)
    p.add_argument('--audit-db', '--reference-database', dest='audit_db', type=Path,
        default=ROOT / 'target/data-audit/acceptance-a0f7260.duckdb')
    args = p.parse_args()
    if args.output.exists() or args.matrix_output and args.matrix_output.exists():
        raise ValueError('Use fresh immutable output files')
    if args.native_fixture and args.execution_dir:
        raise ValueError('Keep synthetic and official execution evidence separate')
    suite = cases(args.matrix)
    frozen_artifacts = dict(jarSha256=ROOT / 'target/dsl-doris-compiler.jar',
        matrixSha256=args.matrix, runnerSha256=Path(__file__),
        oracleSha256=ROOT / 'scripts/doris/project_combination_reference.py',
        rawFieldOracleSha256=ROOT / 'scripts/doris/project_field_reference.py',
        rawFormulaOracleSha256=ROOT / 'scripts/doris/check_official_field_acceptance.py',
        windowOracleSha256=ROOT / 'scripts/doris/project_matrix_reference.py',
        explanationOracleSha256=ROOT / 'scripts/doris/check_project_availability.py',
        semanticViewSha256=ROOT / 'data/doris/ddl/002_semantic_view.sql',
        portableDecimalAdapterSha256=ROOT / 'scripts/doris/project_portable_decimal.py',
        registrySha256=ROOT / 'src/main/resources/stock-slot-registry-v1.json')
    report = dict(purpose='PROJECT_COMBINATION_VALIDATION', officialAcceptanceEligible=False,
        evidenceType='PORTABLE_RAW_FIXTURE', definitionAuthority='PROJECT_INTERNAL_OFFICIAL_DICTIONARY_UNAVAILABLE',
        portableDecimalAdapter=dict(used=not(args.native_fixture or args.execution_dir),
            evidenceType='PORTABLE_DORIS_DECIMAL_EMULATION',notNativeDorisProof=True),
        **{key: digest(path) for key, path in frozen_artifacts.items()}, checks=[])
    try:
        if args.matrix_output:
            args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
            args.matrix_output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if args.native_fixture:
            client = WslDoris(args.distribution, 'dsl-doris-official')
            database = 'dsl_combinations_' + secrets.token_hex(6)
            before = client.query('SELECT * FROM newzl.data_snapshot_registry')
            created = False
            try:
                client.query('CREATE DATABASE ' + database)
                created = True
                report.update(evidenceType='SYNTHETIC_NATIVE_DORIS', fixtureDatabase=database)
                report['checks'] = portable(suite, args.java, (client, database))
                if client.query('SELECT * FROM newzl.data_snapshot_registry') != before:
                    raise AssertionError('Formal registry changed')
            finally:
                if created:
                    try:
                        client.query('DROP DATABASE ' + database)
                        if client.query("SHOW DATABASES LIKE '" + database + "'"):
                            raise AssertionError('Fixture database still present')
                        report['fixtureCleanup'] = 'DONE'
                    except Exception:
                        report['fixtureCleanup'] = 'FAILED'
                        raise
        elif args.execution_dir:
            if args.certificate is None:
                raise ValueError('Certificate required to identify original raw records')
            report.update(evidenceType='OFFICIAL_RAW_DATA_PROJECT_RULES', certificateSha256=digest(args.certificate))
            report['checks'] = execution_checks(suite, args.execution_dir, args.certificate, args.java, args.audit_db)
            report['executionSha256'] = digest(args.execution_dir / 'result.json')
        else:
            report['checks'] = portable(suite, args.java, adapter_evidence=report['portableDecimalAdapter'])
        if any(digest(path) != report[key] for key, path in frozen_artifacts.items()):
            raise AssertionError('Frozen compiler, matrix or independent source definition changed during validation')
    except Exception as error:
        report['fatalError'] = str(error)
        raise
    finally:
        report.update(status='FAIL' if 'fatalError' in report or not report['checks'] else 'PASS',
            passed=sum(c['status'] == 'PASS' for c in report['checks']), total=len(report['checks']))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'passed', 'total')}))


if __name__ == '__main__':
    main()
