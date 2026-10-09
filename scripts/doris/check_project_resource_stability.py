"""Representative final-combination concurrency, real JDBC timeout and restart evidence.

This is project diagnostics, not a cold-cache or full-matrix performance claim.
Missing runtime is NOT_RUN (exit 2); an execution or cleanup failure is FAIL (1).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = 'dsl-doris-official'
PURPOSE = 'official-data-diagnostic'
BUDGET = dict(queryTimeoutSeconds=10, maxEstimatedScanRows=100000000,
              maxReturnRows=10000, maxExecutionMemoryBytes=2147483648)
HTTP_CONCURRENCY = dict(concurrentRequests=2, maxQueueWaitMillis=10000,
    executorMode='SHARED_SINGLE_CONNECTION_SERIALIZED', databaseQueryParallelism=1,
    interpretation='Two concurrent HTTP requests share one executor; database queries are serialized. '
                   'This checks request queue stability, not parallel database query throughput.')


def http_server_command(java, connection, certificate):
    """Give the isolated HTTP queue the same 10-second wait as the timeout probe."""
    return java + ['serve-doris', *connection, '--project-validation', str(Path(certificate).resolve()),
        '--max-queue-wait-ms', str(HTTP_CONCURRENCY['maxQueueWaitMillis']),
        '--http-port', '0', '--auth-token-env', 'DSL_PROJECT_TOKEN']


def timeout_probe_commands(java, classes, arguments=()):
    """Compile the driver into the executor's application class loader.

    Java source-file launch uses a different loader. DriverManager then hides
    that driver from the executor even though the probe registered it.
    """
    executable = shutil.which(str(java)) or str(java)
    compiler = Path(executable).with_name('javac.exe' if Path(executable).suffix.lower() == '.exe' else 'javac')
    jar = str(ROOT / 'target/dsl-doris-compiler.jar')
    classes = str(Path(classes).resolve())
    compile_command = [str(compiler), '-encoding', 'UTF-8', '-cp', jar, '-d', classes,
                       str(ROOT / 'scripts/doris/ProjectResourceTimeoutProbe.java')]
    launch_command = [executable, '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8',
                      '-Dsun.stderr.encoding=UTF-8', '-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets',
                      '-cp', os.pathsep.join((classes, jar)), 'ProjectResourceTimeoutProbe', *arguments]
    return compile_command, launch_command


def validate_driver_registration(proof):
    if (proof.get('status') != 'PASS' or proof.get('executorClassLoaderVisible') is not True
            or proof.get('driverManagerVisible') is not True or proof.get('nativeRuntime') != 'NOT_RUN'):
        raise AssertionError('Timeout driver is not visible to the executor application class loader')


def warmup_cases(endpoint, selected, request, verify, check):
    """Untimed serial admission warmup; never retry or weaken the queue budget."""
    for item in selected:
        case = item['case']
        status, data, wall = request(endpoint, case)
        check('warmup-http-' + case['name'], status == 200, httpStatus=status)
        verify(case, data, 'warmup', 1, wall)


def save_http_failure(folder, case, status, data, wall, secrets_to_redact):
    name = re.sub(r'[^\w.-]', '_', case['name'])
    path = Path(folder) / f'http-failure-{name}-{time.time_ns()}.json'
    evidence = dict(case=case['name'], httpStatus=status, wallSeconds=wall, response=data)
    path.write_text(redact(json.dumps(evidence, ensure_ascii=False, indent=2), secrets_to_redact) + '\n', encoding='utf-8')
    return path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def select_cases(combinations, ranks):
    """Deterministic representatives; every selected case remains in a frozen matrix."""
    if not combinations or not ranks or len({c['name'] for c in combinations + ranks}) != len(combinations + ranks):
        raise ValueError('Nonempty frozen matrices with distinct names required')
    selected = []
    def add(suite, predicate, oracle):
        candidates = [c for c in suite if predicate(c) and c['name'] not in {s['case']['name'] for s in selected}]
        if candidates:
            selected.append(dict(case=candidates[0], oracle=oracle))
    add(combinations, lambda c: len(c['calls']) >= 3, 'combination')
    add(combinations, lambda c: any(v['kind'] in ('ma', 'rsi') for v in c['calls']), 'combination')
    add(combinations, lambda c: any(v.get('metric') == 'net' for v in c['calls']), 'combination')
    add(combinations, lambda c: c['date'] != '2026-04-14', 'combination')
    add(ranks, lambda c: 'pre' in c and any(v['kind'] == 'rank' for v in c['calls']), 'rank')
    add(ranks, lambda c: any(v['kind'] == 'query' for v in c['calls']), 'rank')
    add(ranks, lambda c: any(v['kind'] == 'count' for v in c['calls']), 'rank')
    if len(selected) < 3:
        raise ValueError('Matrices lack sufficient final-combination representatives')
    return selected


def validate_execution(data, expected, certificate_hash, assess):
    checks = assess(data, expected)
    checks['resourceBudgetEqual'] = all(data['limits'].get(k) == v for k, v in BUDGET.items())
    checks['certificateEqual'] = data['dataQuality']['certificateSha256'] == certificate_hash
    timings = data['dataQuality'].get('diagnosticTimings')
    checks['diagnosticTimingsAvailable'] = isinstance(timings, dict) and all(
        isinstance(timings.get(k), (int, float)) and not isinstance(timings[k], bool)
        and math.isfinite(timings[k]) and timings[k] >= 0 for k in
        ('sourceValidationMillis', 'mainExplainMillis', 'availabilityExplainMillis', 'missingStatisticsMillis', 'sampleDetailsMillis'))
    if not all(v is True for v in checks.values()):
        raise AssertionError('Execution result, coverage or policy mismatch: ' + ','.join(k for k, v in checks.items() if v is not True))
    return checks


def validate_timeout(proof):
    if proof.get('status') != 'PASS' or proof.get('controlQuery') != 'SELECT SLEEP(4)' or proof.get('jdbcTimeoutSeconds') != 1:
        raise AssertionError('Missing real JDBC timeout control evidence')
    if proof.get('actualSlowQueryReached') is not True or proof.get('timeoutCategory') != 'TIMEOUT' or not isinstance(proof.get('recovery'), dict):
        raise AssertionError('Timeout did not reach the real slow SELECT or recovery is missing')


def ownership(prefix):
    result = subprocess.run(prefix + ['inspect', '-f', '{{index .Config.Labels "com.acme.dorisdsl.purpose"}}', CONTAINER],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    if result.returncode or result.stdout.strip() != PURPOSE:
        raise ValueError('Refusing container without the dedicated diagnostic ownership label')


def redact(text, values):
    result = str(text)
    for value in values:
        result = result.replace(value, '[REDACTED]')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--certificate', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='java')
    parser.add_argument('--matrix', required=True, type=Path)
    parser.add_argument('--reference-database', required=True, type=Path)
    parser.add_argument('--restart', action='store_true')
    args = parser.parse_args()
    folder = args.output_dir.resolve()
    if folder.exists():
        raise ValueError('Use a fresh output directory')
    folder.mkdir(parents=True)
    report = dict(purpose='PROJECT_FINAL_COMBINATION_RESOURCE_STABILITY', officialAcceptanceEligible=False,
        cacheState='Doris SQL cache disabled; host page cache retained; explicit serial warmup before hot-process concurrency',
        fullMatrixPerformance=False, budget=BUDGET, concurrency=dict(HTTP_CONCURRENCY),
        status='RUNNING', checks=[], executions=[],
        restartRequested=args.restart, restartStatus='NOT_RUN', timeoutStatus='NOT_RUN', cleanup='NOT_STARTED',
        startedAtUtc=datetime.now(timezone.utc).isoformat())
    def persist():
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    def check(name, ok, **detail):
        report['checks'].append(dict(name=name, status='PASS' if ok else 'FAIL', **detail)); persist()
        if not ok:
            raise AssertionError(name)
    persist()
    sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
    try:
        import duckdb
        from run_correctness import WslDoris
        client = WslDoris(args.distribution, CONTAINER)
        if client.query('SELECT 1') != [('1',)]:
            raise RuntimeError('Doris health unavailable')
        for path in [args.certificate, args.matrix, args.reference_database, ROOT / 'target/dsl-doris-compiler.jar']:
            if not path.is_file():
                raise FileNotFoundError('Required resource input missing: ' + str(path))
    except (ImportError, FileNotFoundError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='NOT_RUN', reason=str(error), cleanup='NOT_NEEDED', completedAtUtc=datetime.now(timezone.utc).isoformat())
        persist(); return 2
    try:
        from project_combination_reference import cases as combination_cases, reference as combination_reference
        from project_rank_reference import cases as rank_cases, matrix_document, reference as rank_reference
        from project_field_reference import load,configure_reference_connection
        from project_matrix_reference import assess
        certificate = read(args.certificate)
        if certificate.get('status') != 'PROJECT_READY_WITH_LIMITATIONS' or certificate.get('definitionAuthority') != 'PROJECT_INTERNAL':
            raise ValueError('Expected the current project source certificate')
    except Exception as error:
        report.update(status='FAIL', fatalError=str(error), cleanup='NOT_NEEDED', completedAtUtc=datetime.now(timezone.utc).isoformat())
        persist(); return 1
    reader = 'dsl_resource_' + secrets.token_hex(6); password = secrets.token_hex(24); token = secrets.token_hex(24)
    values = [password, token]
    env = os.environ.copy(); env.update(DSL_PROJECT_PASSWORD=password, DSL_PROJECT_TOKEN=token)
    server = None; account = False
    def stop():
        nonlocal server
        if server is not None:
            if server.poll() is None: server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=10)
                raise RuntimeError('HTTP process required forced cleanup')
            server = None
    def state():
        return [sorted(client.query(sql)) for sql in [
            "SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info",
            'SELECT * FROM newzl.data_snapshot_registry',
            "SELECT 'basic',MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'extension',MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_ext",
            "SELECT TABLE_NAME,SHA2(VIEW_DEFINITION,256) FROM information_schema.views WHERE TABLE_SCHEMA='newzl' ORDER BY TABLE_NAME"]]
    def environment():
        from configure_project_be_runtime import RUNTIME_TARGET
        from project_fe_runtime import capture_fe_runtime
        ownership(client.prefix)
        result = subprocess.run(client.prefix + ['inspect', '-f', '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}', CONTAINER], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', check=True, timeout=20)
        config = subprocess.run(client.prefix + ['exec', CONTAINER, 'curl', '-fsS', '--max-time', '10', f'http://127.0.0.1:{client.be_http_port}/api/show_config'],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, timeout=20)
        memory, cpus = map(int, result.stdout.split())
        rows = json.loads(config.stdout)
        selected = [row for row in rows if row[0] in RUNTIME_TARGET]
        if len(selected) != len(RUNTIME_TARGET) or {row[0] for row in selected} != set(RUNTIME_TARGET):
            raise ValueError('Incomplete or duplicate BE runtime settings')
        configuration = subprocess.run(client.prefix + ['exec', CONTAINER, 'cat', '/opt/apache-doris/be/conf/be.conf'],
            capture_output=True, check=True, timeout=20)
        return dict(containerMemoryBytes=memory, containerNanoCpus=cpus,
                    beMemoryShare=next(row[2] for row in rows if row[0] == 'mem_limit'),
                    beRuntimeSettings={row[0]:row[2] for row in selected},
                    beConfigurationSha256=hashlib.sha256(configuration.stdout).hexdigest(),
                    feRuntime=capture_fe_runtime(client))
    def memory_sample(label):
        result = subprocess.run(client.prefix + ['stats', '--no-stream', '--format', '{{json .}}', CONTAINER], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', check=True, timeout=20)
        report.setdefault('containerMemorySamples', []).append(dict(label=label, raw=json.loads(result.stdout)))
    def request(endpoint, case):
        request = urllib.request.Request(endpoint + '/execute', data=json.dumps(dict(dsl=case['dsl'], snapshotId=certificate['snapshotId'], maxRows=10000)).encode('utf-8'),
                                         headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.status, json.loads(response.read()), time.monotonic() - started
        except urllib.error.HTTPError as error:
            data = json.loads(error.read())
            wall = time.monotonic() - started
            save_http_failure(folder, case, error.code, data, wall, values)
            return error.code, data, wall
    def start(label, connection):
        nonlocal server
        log = folder / (label + '-server.log')
        with log.open('wb') as stream:
            server = subprocess.Popen(http_server_command(java, connection, args.certificate),
                env=env, stdout=stream, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and server.poll() is None:
            match = re.search(r'Listening on (http://127.0.0.1:\d+)', log.read_text(encoding='utf-8', errors='replace'))
            if match: return match[1]
            time.sleep(.1)
        raise RuntimeError('Project HTTP service startup failed')
    def verify(case, data, phase, replica, wall):
        checks = validate_execution(data, expected[case['name']], report['certificateSha256'], assess)
        name = f"{phase}-{replica}-{case['name']}"
        artifact = re.sub(r'[^\w.-]', '_', name) + '.json'
        (folder / artifact).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        report['executions'].append(dict(case=case['name'], phase=phase, replica=replica, artifact=artifact,
            rows=len(data['rows']), sqlFingerprint=data['sqlFingerprint'], wallSeconds=wall,
            timings=data['timings'], diagnosticTimings=data['dataQuality']['diagnosticTimings'],
            queryProfile=data.get('queryProfile'), profileEvidence='AVAILABLE_SUMMARY' if (data.get('queryProfile') or {}).get('available') else 'NOT_AVAILABLE', checks=checks))
        check(name, True)
    try:
        ownership(client.prefix)
        classes = folder / 'timeout-probe-classes'
        classes.mkdir()
        compile_command, probe_command = timeout_probe_commands(args.java, classes)
        compilation = subprocess.run(compile_command, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=120)
        (folder / 'timeout-compile.log').write_text(redact(compilation.stdout + compilation.stderr, values), encoding='utf-8')
        check('timeout-probe-compile', compilation.returncode == 0, exitCode=compilation.returncode)
        registration = subprocess.run(probe_command + ['--driver-self-check'], capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=30)
        (folder / 'timeout-driver.log').write_text(redact(registration.stderr, values), encoding='utf-8')
        check('timeout-driver-registration-exit', registration.returncode == 0, exitCode=registration.returncode)
        registration_proof = json.loads(registration.stdout)
        validate_driver_registration(registration_proof)
        (folder / 'timeout-driver-proof.json').write_text(json.dumps(registration_proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        report.update(timeoutProbeLaunchMode='COMPILED_APPLICATION_CLASS_PATH',
                      timeoutProbeSourceSha256=digest(ROOT / 'scripts/doris/ProjectResourceTimeoutProbe.java'))
        before = state(); report['sourceStateBefore']=before; check('formal-registry-empty', before[1] == [])
        report['environment'] = environment()
        rank_path = ROOT / 'config/acceptance/project-rank-matrix-v1.json'
        check('frozen-rank-matrix', read(rank_path) == json.loads(json.dumps(matrix_document(), ensure_ascii=False)))
        selected = select_cases(combination_cases(args.matrix), rank_cases())
        report.update(jarSha256=digest(ROOT / 'target/dsl-doris-compiler.jar'), certificateSha256=digest(args.certificate),
            matrixSha256=digest(args.matrix), rankMatrixSha256=digest(rank_path), runnerSha256=digest(Path(__file__)),
            referenceDatabase=str(args.reference_database.resolve()), selectedCases=[s['case']['name'] for s in selected])
        (folder / 'selection.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        expected = {}
        with duckdb.connect(str(args.reference_database), read_only=True) as connection:
            report['referenceResources']=configure_reference_connection(connection,args.reference_database)
            check('raw-source-lock', connection.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone() ==
                (certificate['snapshotId'], certificate['manifestSha256'], 'FAIL'))
            for day in sorted({s['case']['date'] for s in selected}):
                source = load(connection, day, 64)
                for item in selected:
                    if item['case']['date'] == day:
                        expected[item['case']['name']] = (combination_reference if item['oracle'] == 'combination' else rank_reference)(item['case'], source)
                del source
        address = subprocess.run(['wsl.exe', '-d', args.distribution, '--exec', 'hostname', '-I'], capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', check=True, timeout=20)
        hosts = re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', address.stdout)
        if not hosts: raise RuntimeError('WSL IPv4 unavailable')
        connection = ['--host', hosts[0], '--port', str(client.query_port), '--database', 'newzl', '--user', reader, '--password-env', 'DSL_PROJECT_PASSWORD',
            '--max-scan-rows', '100000000', '--max-exec-memory-bytes', '2147483648', '--max-return-rows', '10000']
        java = [args.java, '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8',
            '-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets', '-jar', str(ROOT / 'target/dsl-doris-compiler.jar')]
        client.query(f"CREATE USER '{reader}' IDENTIFIED BY '{password}'"); account = True
        client.query(f"GRANT SELECT_PRIV ON newzl.* TO '{reader}'")
        memory_sample('before-concurrency'); endpoint = start('concurrent', connection)
        report['warmup'] = dict(mode='UNTIMED_SERIAL_HOT_PROCESS_ADMISSION', requestCount=len(selected),
                                performanceSamples=False, retries=0)
        warmup_cases(endpoint, selected, request, verify, check)
        memory_sample('after-warmup')
        with ThreadPoolExecutor(max_workers=HTTP_CONCURRENCY['concurrentRequests']) as workers:
            for item in selected:
                futures = [workers.submit(request, endpoint, item['case'])
                           for _ in range(HTTP_CONCURRENCY['concurrentRequests'])]
                for replica, future in enumerate(futures, 1):
                    status, data, wall = future.result(timeout=100)
                    check('http-' + item['case']['name'] + '-' + str(replica), status == 200, httpStatus=status)
                    verify(item['case'], data, 'concurrent', replica, wall)
        memory_sample('after-concurrency'); stop()
        # A test-only transport reaches a slow actual JDBC SELECT once; it cannot
        # turn an invalid HTTP parameter or a mocked TIMEOUT into database evidence.
        control = dict(name='resource-timeout-recovery', calls=[dict(kind='field', metric='close')],
            expr=['cmp', 0, '>', 1], date='2026-04-14', market='',
            dsl="indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1")
        with duckdb.connect(str(args.reference_database), read_only=True) as raw:
            configure_reference_connection(raw,args.reference_database)
            expected[control['name']] = combination_reference(control, load(raw, control['date'], 64))
        query_file = folder / 'timeout-control.dsl'; query_file.write_text(control['dsl'], encoding='utf-8')
        result = subprocess.run(probe_command + [f'jdbc:mysql://{hosts[0]}:{client.query_port}/newzl', reader,
            str(ROOT / 'src/main/resources/stock-slot-registry-v1.json'), str(args.certificate.resolve()), str(query_file)],
            env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        (folder / 'timeout-probe.log').write_text(redact(result.stderr, values), encoding='utf-8')
        check('timeout-probe-exit', result.returncode == 0, exitCode=result.returncode)
        proof = json.loads(result.stdout); validate_timeout(proof)
        (folder / 'timeout-proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        verify(control, proof['recovery'], 'timeout-recovery', 1, proof['recovery']['timings']['totalMillis'] / 1000)
        report['timeoutStatus'] = 'PASS_REAL_JDBC_CONTROL'
        if args.restart:
            ownership(client.prefix)
            result = subprocess.run(client.prefix + ['restart', CONTAINER], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=120)
            check('owned-restart-command', result.returncode == 0)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                try:
                    if state() == before: break
                except Exception: pass
                time.sleep(1)
            else: raise RuntimeError('Restarted sources not ready')
            check('restart-config-unchanged', environment() == report['environment'])
            endpoint = start('restart', connection)
            for item in selected:
                status, data, wall = request(endpoint, item['case']); check('restart-http-' + item['case']['name'], status == 200)
                verify(item['case'], data, 'restart', 1, wall)
            stop(); memory_sample('after-restart'); report['restartStatus'] = 'PASS_PROCESS_RESTART_HOST_CACHE_RETAINED'
        report['sourceStateAfter']=state()
        check('source-registry-unchanged', report['sourceStateAfter'] == before)
        check('environment-unchanged', environment() == report['environment'])
        check('input-artifacts-unchanged', all(digest(path) == report[key] for path, key in [
            (ROOT / 'target/dsl-doris-compiler.jar', 'jarSha256'), (args.certificate, 'certificateSha256'),
            (args.matrix, 'matrixSha256'), (rank_path, 'rankMatrixSha256'), (Path(__file__), 'runnerSha256')]))
        check('timeout-probe-source-unchanged', digest(ROOT / 'scripts/doris/ProjectResourceTimeoutProbe.java') == report['timeoutProbeSourceSha256'])
    except Exception as error:
        report['fatalError'] = redact(error, values)
    finally:
        errors = []
        try: stop()
        except Exception as error: errors.append(redact(error, values))
        if account:
            try: client.query(f"DROP USER '{reader}'")
            except Exception as error: errors.append(redact(error, values))
        report.update(cleanup='FAILED' if errors else 'DONE', cleanupErrors=errors,
            total=len(report['checks']), passed=sum(c['status'] == 'PASS' for c in report['checks']),
            completedAtUtc=datetime.now(timezone.utc).isoformat())
        report['status'] = 'FAIL' if errors or 'fatalError' in report or report['passed'] != report['total'] else 'PASS'
        persist()
    print(json.dumps({key: report[key] for key in ['status', 'passed', 'total', 'timeoutStatus', 'restartStatus']}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
