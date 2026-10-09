"""Reproducible official-data CLI/HTTP matrix, repeats and owned-container restart checks."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import duckdb

from validate_project_sources import ROOT, WslDoris, digest
from project_matrix_reference import load, render, reference, assess

SEED = 20261005


def cases():
    result = []
    def add(name, calls, expr, date='2026-04-14', market='', **extra):
        case = dict(name=name, calls=calls, expr=expr, date=date, market=market, **extra)
        dsl = render(expr, calls, date, market)
        if 'pre' in extra: dsl = render(extra['pre'], calls, date, market) + ' then ' + dsl
        if 'limit' in extra: dsl += f" limit 0,{extra['limit']}"
        result.append(dict(case, dsl=dsl))
    close = dict(kind='field', metric='close'); net = dict(kind='field', metric='net')
    for date in ['2006-01-04', '2010-05-13', '2018-08-20', '2020-02-03', '2025-01-02', '2026-04-14', '2026-04-12']:
        for market in ['沪', '深', '京']:
            add('date-'+date+'-'+market, [close], ('cmp', 0, '>', 1), date, market)
    for date in ['2006-01-04', '2018-08-20', '2020-02-03', '2026-04-14']:
        add('funds-'+date, [net], ('cmp', 0, '>', 0), date)
    for market in ['沪|深', '^京']: add('market-'+market, [close], ('cmp', 0, '>', 1), market=market)
    for n in [3, 20]: add('ma'+str(n), [dict(kind='ma', n=n)], ('cmp', 0, '>', 1))
    for mode, op in [('CONS', '>='), ('CONS', '='), ('EXIST', '>='), ('EXIST', '=')]:
        call = dict(kind='count', metric='close', mode=mode, countOp=op, n=3, op='>', threshold=1)
        add(mode+op+'3', [call], ('cmp', 0, '=', True))
    for region in ['低', '中', '高']: add('position3-'+region, [dict(kind='position', n=3)], ('cmp', 0, '=', region))
    add('position20', [dict(kind='position', n=20)], ('cmp', 0, '=', '高'))
    add('two-position-windows', [dict(kind='position', n=3), dict(kind='position', n=5)],
        ('or', ('cmp', 0, '=', '高'), ('cmp', 1, '=', '低')))
    for kind in ['cross_above', 'cross_down', 'close_together', 'record_high', 'record_low']:
        add(kind, [dict(kind=kind, n=5)], ('cmp', 0, '=', True))
    add('rsi5', [dict(kind='rsi', n=5)], ('cmp', 0, '>', 50))
    for kind in ['ma', 'position', 'cross_above']:
        add('short-history-'+kind, [dict(kind=kind, n=3)], ('cmp', 0, '=', '高') if kind == 'position' else ('cmp', 0, '>', 1) if kind == 'ma' else ('cmp', 0, '=', True), date='2006-01-04')
    for direction in ['desc:dense_rank', 'asc:rank', 'desc:row_number']:
        add('rank-'+direction, [dict(kind='rank', direction=direction)], ('cmp', 0, '<=', 10))
    add('then-rank-limit', [net, dict(kind='rank', direction='desc:row_number')], ('cmp', 1, '<=', 10), pre=('cmp', 0, '>', 0), limit=7)
    for keyword, market in [('600000', ''), ('NO_SUCH_SECURITY', ''), ('600000', '深')]:
        add('query-'+keyword+'-'+market, [close, dict(kind='query', keyword=keyword)], ('callcmp', 0, '>', 1), market=market)
    add('arithmetic', [close, dict(kind='field', metric='open')], ('sumcmp', 0, 1, 20))
    rng = random.Random(SEED)
    metrics = ['close', 'open', 'volume', 'net']
    thresholds = {'close': [1, 5, 10, 50], 'open': [1, 10, 20], 'volume': [0, 100000, 10000000], 'net': [0, 1000000, -1000000]}
    for i in range(12):
        chosen = rng.sample(metrics, 3); calls = [dict(kind='field', metric=m) for m in chosen]
        predicates = [('cmp', j, rng.choice(['>', '<=', '!=']), rng.choice(thresholds[m])) for j, m in enumerate(chosen)]
        expr = (rng.choice(['and', 'or']), predicates[0], (rng.choice(['and', 'or']), predicates[1], predicates[2]))
        add('seeded-'+str(i+1).zfill(2), calls, expr, date=rng.choice(['2018-08-20', '2020-02-03', '2026-04-14']), market=rng.choice(['', '沪', '深', '京', '^京']), limit=10000)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--certificate', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT/'target/data-audit/acceptance-a0f7260.duckdb')
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='D:/Java/jdk-21/bin/java.exe')
    parser.add_argument('--restart', action='store_true', help='Restart only the owned diagnostic container twice')
    parser.add_argument('--only-case', help='Single-case diagnosis, not a complete matrix')
    args = parser.parse_args(); folder = args.output_dir.resolve()
    if args.only_case and args.restart: raise ValueError('Single-case diagnosis cannot claim restart-suite coverage')
    if folder.exists(): raise ValueError('Use a fresh output directory')
    folder.mkdir(parents=True)
    certificate = json.loads(args.certificate.read_text(encoding='utf-8')); snapshot = certificate['snapshotId']
    suite = cases()
    if args.only_case:
        suite = [c for c in suite if c['name'] == args.only_case]
        if len(suite) != 1: raise ValueError('Unknown case')
    report = dict(purpose='PROJECT_EXPANDED_OFFICIAL_DATA_MATRIX' if not args.only_case else 'PROJECT_SINGLE_CASE_DIAGNOSTIC',
        officialAcceptanceEligible=False, seed=SEED, snapshotId=snapshot, manifestSha256=certificate['manifestSha256'],
        jarSha256=digest(ROOT/'target/dsl-doris-compiler.jar'), certificateSha256=digest(args.certificate),
        oracleSha256=digest(ROOT/'scripts/doris/project_matrix_reference.py'), runnerSha256=digest(Path(__file__)),
        policySha256=digest(ROOT/'config/acceptance/project-data-policy-v1.json'), checks=[], executions=[], restart=[])
    (folder/'matrix.json').write_text(json.dumps(suite, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    reader = 'dsl_project_matrix_'+secrets.token_hex(6); password = secrets.token_hex(24); token = secrets.token_hex(24)
    env = os.environ.copy(); env.update(DSL_PROJECT_PASSWORD=password, DSL_PROJECT_TOKEN=token)
    java = [args.java, '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8',
            '-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets', '-jar', str(ROOT/'target/dsl-doris-compiler.jar')]
    server = None; account = False; client = None; con = None
    expected = {}
    def artifact(label, suffix='.json'):
        return folder/(re.sub(r'[<>:"/\\|?*]', '_', label)+suffix)

    def redact(text): return str(text).replace(password, '[REDACTED]').replace(token, '[REDACTED]')
    def persist():
        (folder/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    def check(name, ok, **details):
        report['checks'].append(dict(name=name, status='PASS' if ok else 'FAIL', **details)); persist()
        if not ok: raise AssertionError(name)
    def stop():
        nonlocal server
        if server is not None:
            if server.poll() is None: server.terminate()
            server.wait(timeout=10); server = None
    def request(endpoint, dsl):
        payload = dict(dsl=dsl, snapshotId=snapshot, maxRows=10000)
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer '+token}
        try:
            with urllib.request.urlopen(urllib.request.Request(endpoint+'/execute', data=json.dumps(payload).encode(), headers=headers), timeout=80) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error: return error.code, json.loads(error.read())
    def start_server(connection, label):
        nonlocal server
        log = folder/(label+'-server.log')
        with log.open('wb') as output:
            server = subprocess.Popen(java+['serve-doris']+connection+['--project-validation', str(args.certificate.resolve()),
                '--http-port', '0', '--auth-token-env', 'DSL_PROJECT_TOKEN'], env=env, stdout=output, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+30
        while time.monotonic() < deadline and server.poll() is None:
            match = re.search(r'Listening on (http://127.0.0.1:\d+)', log.read_text(encoding='utf-8', errors='replace'))
            if match: return match[1]
            time.sleep(.1)
        raise RuntimeError('HTTP server startup failed')
    def verify(label, case, data, transport, phase, wall):
        artifact(label).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        checks = assess(data, expected[case['name']]); limits = data['limits']
        checks['resourcePolicyEqual'] = (limits['queryTimeoutSeconds'] == 10 and limits['maxExecutionMemoryBytes'] == 2147483648
            and limits['maxEstimatedScanRows'] == 100000000 and limits['maxReturnRows'] == 10000)
        checks['certificateEqual'] = data['dataQuality']['certificateSha256'] == report['certificateSha256']
        details = dict(case=case['name'], phase=phase, transport=transport, rows=len(data['rows']), expectedRows=len(expected[case['name']]['rows']),
            coverageStatus=data['dataQuality']['coverageStatus'], observed=data['dataQuality']['observedSecurities'],
            wallSeconds=round(wall, 3), totalMillis=data['timings']['totalMillis'],
            dorisExecutionMillis=data['timings']['dorisExecutionMillis'], validationMillis=data['dataQuality']['validationMillis'],
            sqlFingerprint=data['sqlFingerprint'], checks=checks)
        report['executions'].append(details)
        check(label, all(checks.values()), **details)
        print(label+' PASS '+str(details['rows'])+' rows '+str(round(details['totalMillis']))+'ms', flush=True)
    def probe(source, host):
        completed = subprocess.run([args.java, '-Dfile.encoding=UTF-8', '-cp', str(ROOT/'target/dsl-doris-compiler.jar'),
            str(ROOT/'scripts/doris/ProjectExecutionProbe.java'), f'jdbc:mysql://{host}:{client.query_port}/newzl', reader,
            str(ROOT/'src/main/resources/stock-slot-registry-v1.json'), str(args.certificate.resolve()), str(source)],
            env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=80)
        (folder/'failure-diagnostic.log').write_text(redact(completed.stdout+'\n'+completed.stderr), encoding='utf-8')
    def source_state():
        queries = ["SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info",
                   'SELECT * FROM newzl.data_snapshot_registry']
        return [sorted(client.query(q)) for q in queries]
    def environment():
        container = subprocess.run(client.prefix+['inspect','-f','{{.HostConfig.Memory}}','dsl-doris-official'], capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=20)
        backend = subprocess.run(client.prefix+['exec','dsl-doris-official','curl','-fsS','--max-time','10',
            f'http://127.0.0.1:{client.be_http_port}/api/show_config'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
        if container.returncode or backend.returncode: raise RuntimeError('Cannot verify diagnostic container/BE memory configuration')
        share = next(row[2] for row in json.loads(backend.stdout) if row[0] == 'mem_limit')
        return dict(containerMemoryBytes=int(container.stdout.strip()), beMemoryShare=share)
    def restart_container(round_number, before):
        start = time.monotonic()
        command = subprocess.Popen(['wsl.exe', '-d', args.distribution, '--exec', 'docker', 'restart', 'dsl-doris-official'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = command.communicate(timeout=90)
        if command.returncode: raise RuntimeError('Owned diagnostic container restart failed: '+stderr.decode('utf-8', errors='replace')[:400])
        deadline = time.monotonic()+180
        last_error = ''
        while time.monotonic() < deadline:
            try:
                # SELECT 1 can succeed before the BE and loaded tablets are ready.
                if source_state() == before: break
            except Exception as error: last_error = redact(error)
            time.sleep(1)
        else: raise RuntimeError('Diagnostic source readiness failed: '+last_error[:400])
        report['restart'].append(dict(round=round_number, readySeconds=round(time.monotonic()-start, 3),
            environmentAfter=environment(),
            cacheInterpretation='Doris FE/BE process restarted; host OS page cache was not cleared. Not a formal cold-cache benchmark.'))
        check('restart-source-state-'+str(round_number), source_state() == before and environment() == report['environment'])

    try:
        client = WslDoris(args.distribution, 'dsl-doris-official')
        before = source_state()
        report['environment'] = environment()
        check('formal-registry-empty', before[1] == [])
        report['sourceCounts'] = {name: int(rows) for name, rows in before[0]}
        con = duckdb.connect(str(args.database), read_only=True); con.execute("SET memory_limit='4GB'"); con.execute('SET threads=4')
        lock = con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone()
        check('raw-reference-lock', lock == (snapshot, certificate['manifestSha256'], 'FAIL'))
        for date in sorted({c['date'] for c in suite}):
            source = load(con, date)
            for case in suite:
                if case['date'] == date: expected[case['name']] = reference(case, source)
            print('reference '+date+' ready', flush=True)
        con.close(); con = None
        references = {name: dict(rows=r['rows'], observed=r['observed'], missingExtensionRows=len(r['missingExtension']),
            coverageStatus=r['coverageStatus'], inputs=[dict(function=i['function'], indicator=i['indicator'], unavailable=len(i['missing'])) for i in r['inputs']],
            sampleKeys=r['sampleKeys']) for name, r in expected.items()}
        (folder/'independent-expected.json').write_text(json.dumps(references, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        address = subprocess.run(['wsl.exe', '-d', args.distribution, '--exec', 'hostname', '-I'], capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=20)
        hosts = re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', address.stdout)
        if address.returncode or not hosts: raise RuntimeError('WSL IPv4 unavailable')
        host = hosts[0]
        connection = ['--host', host, '--port', str(client.query_port), '--database', 'newzl', '--user', reader, '--password-env', 'DSL_PROJECT_PASSWORD',
            '--max-scan-rows', '100000000', '--max-exec-memory-bytes', '2147483648', '--max-return-rows', '10000']
        client.query(f"CREATE USER '{reader}' IDENTIFIED BY '{password}'"); account = True
        client.query(f"GRANT SELECT_PRIV ON newzl.* TO '{reader}'")
        with tempfile.TemporaryDirectory(prefix='matrix-project-') as temp:
            path = Path(temp)/'query.dsl'
            for case in suite:
                path.write_text(case['dsl'], encoding='utf-8'); start = time.monotonic()
                completed = subprocess.run(java+['execute-stock-slot-sql', str(path), '--snapshot-id', snapshot, '--max-rows', '10000']
                    +connection+['--project-validation', str(args.certificate.resolve())], env=env, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=90)
                if completed.returncode:
                    artifact(case['name'], '-failure.log').write_text(redact(completed.stdout+'\n'+completed.stderr), encoding='utf-8')
                    probe(path, host)
                check(case['name']+'-cli', completed.returncode == 0, exitCode=completed.returncode, error=redact(completed.stderr[:400]))
                verify(case['name'], case, json.loads(completed.stdout), 'CLI', 'matrix', time.monotonic()-start)
        if not args.only_case:
            lookup = {c['name']: c for c in suite}
            endpoint = start_server(connection, 'repeat')
            for round_number in range(1, 9):
                for name in ['position3-高', 'seeded-01']:
                    case = lookup[name]; start = time.monotonic(); status, data = request(endpoint, case['dsl'])
                    check(f'repeat-{round_number}-{name}-http', status == 200, httpStatus=status, error=data if status != 200 else None)
                    verify(f'repeat-{round_number}-{name}', case, data, 'HTTP', 'repeat', time.monotonic()-start)
            stop()
            if args.restart:
                for round_number in range(1, 3):
                    restart_container(round_number, before); endpoint = start_server(connection, 'restart-'+str(round_number))
                    for name in ['position3-高', 'funds-2026-04-14', 'then-rank-limit', 'ma20']:
                        case = lookup[name]; start = time.monotonic(); status, data = request(endpoint, case['dsl'])
                        check(f'restart-{round_number}-{name}-http', status == 200, httpStatus=status, error=data if status != 200 else None)
                        verify(f'restart-{round_number}-{name}', case, data, 'HTTP', 'restart', time.monotonic()-start)
                    stop()
        check('source-state-unchanged', source_state() == before and environment() == report['environment'])
        check('artifacts-unchanged', digest(ROOT/'target/dsl-doris-compiler.jar') == report['jarSha256'] and digest(args.certificate) == report['certificateSha256']
            and digest(ROOT/'scripts/doris/project_matrix_reference.py') == report['oracleSha256'] and digest(Path(__file__)) == report['runnerSha256'])
    except Exception as error:
        report['fatalError'] = redact(error); raise
    finally:
        if con is not None: con.close()
        cleanup_errors = []
        try: stop()
        except Exception as error: cleanup_errors.append(redact(error))
        if account:
            try: client.query(f"DROP USER '{reader}'")
            except Exception as error: cleanup_errors.append(redact(error))
        if cleanup_errors: report['cleanupErrors'] = cleanup_errors
        report.update(cleanup='FAILED' if cleanup_errors else 'DONE', completedAtUtc=datetime.now(timezone.utc).isoformat(),
            passed=sum(c['status'] == 'PASS' for c in report['checks']), total=len(report['checks']),
            matrixCases=len(suite), restartRequested=args.restart)
        report['status'] = 'FAIL' if cleanup_errors or 'fatalError' in report or report['passed'] != report['total'] else 'PASS'
        persist()
    if report['status'] != 'PASS': raise RuntimeError('Matrix cleanup failed; see persisted result')
    print(json.dumps({k: report[k] for k in ['status', 'matrixCases', 'passed', 'total']}, ensure_ascii=False))


if __name__ == '__main__': main()
