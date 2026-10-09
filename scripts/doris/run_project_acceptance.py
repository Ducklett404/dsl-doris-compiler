"""Reproducible project-only acceptance. Formal snapshot gates are never bypassed.

Exit 0: selected project checks passed; 1: real failure; 2: requested environment NOT_RUN.
Offline success is explicitly PASS_OFFLINE_REAL_NOT_RUN, never official acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ('src', 'scripts', 'config', 'docs', 'benchmarks', 'accuracy', '.github', 'plugins', 'examples',
               'data/doris/ddl', 'data/doris/config', 'data/doris/snapshots')
SOURCE_FILES = ('pom.xml', 'executor-doris/pom.xml', 'README.md', 'DELIVERY.md', 'SELF_TEST_REPORT.md', 'mvnw', 'mvnw.cmd', 'AGENTS.md', '.gitignore',
                '.gitattributes', 'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
                'data/doris/data-contract.json', 'data/doris/README.md')
MATRICES = ('config/acceptance/project-combination-matrix-v1.json',
            'config/acceptance/project-rank-matrix-v1.json')
RAW_PRECHECK_CONTRACT = dict(version='raw-all-matrices-precheck-v1', rounds=1,
    caseCounts={'official-field-matrix': 94, 'official-combinations': 79, 'official-rank-combinations': 172},
    performanceSamples=False)
SYSTEM_SLEEP_PREVENTION = dict(status='NOT_STARTED')
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class AutomaticSleepPrevention:
    """Keep a long acceptance run out of Windows *automatic* system sleep.

    This does not keep the display on and does not claim to override an explicit
    sleep, lid-close policy, shutdown or power loss. The request belongs to the
    calling thread and is explicitly cleared when the unified runner exits.
    """
    def __init__(self, platform=None, setter=None):
        self.platform = os.name if platform is None else platform
        self.setter = setter
        self.active = False
        self.evidence = dict(status='NOT_STARTED')

    def __enter__(self):
        if self.platform != 'nt':
            self.evidence = dict(status='NOT_APPLICABLE', mechanism='NON_WINDOWS')
            return self.evidence
        if self.setter is None:
            import ctypes
            function = ctypes.windll.kernel32.SetThreadExecutionState
            function.argtypes = [ctypes.c_uint]
            function.restype = ctypes.c_uint
            self.setter = function
        if not self.setter(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
            raise RuntimeError('Unable to acquire the Windows automatic-sleep prevention request')
        self.active = True
        self.evidence = dict(status='ACTIVE_DURING_RUN',
            mechanism='WINDOWS_SET_THREAD_EXECUTION_STATE_SYSTEM_REQUIRED', displayRequired=False,
            limitations='Does not override explicit sleep, lid-close policy, shutdown or power loss')
        return self.evidence

    def __exit__(self, exception_type, exception, traceback):
        if self.active:
            released = self.setter(ES_CONTINUOUS)
            self.active = False
            if not released and exception_type is None:
                raise RuntimeError('Unable to clear the Windows automatic-sleep prevention request')
        return False


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def reference_identity(path, enabled=True):
    """Bind the actual independent reference bytes, not just its filesystem path."""
    path = Path(path)
    wal = Path(str(path) + '.wal')
    return dict(path=str(path.resolve()), enabled=enabled,
                sha256=digest(path) if enabled and path.is_file() else None,
                bytes=path.stat().st_size if enabled and path.is_file() else None,
                pendingWal=enabled and wal.is_file() and wal.stat().st_size > 0)


def source_files(root=ROOT):
    paths = {root / p for p in SOURCE_FILES if (root / p).is_file()}
    for directory in (*SOURCE_DIRS, 'executor-doris/src'):
        for path in (root / directory).rglob('*'):
            if not path.is_file() or any(p in ('__pycache__', 'target', '.git') for p in path.parts):
                continue
            if path.suffix in ('.pyc', '.log', '.duckdb'):
                continue
            # Snapshot input manifests only, not historical load artifacts or huge data files.
            if 'data/doris/snapshots' in path.relative_to(root).as_posix() and path.name != 'manifest.json':
                continue
            paths.add(path)
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def source_digest(root=ROOT):
    records = ''.join(p.relative_to(root).as_posix() + '\0' + digest(p) + '\n' for p in source_files(root))
    return hashlib.sha256(records.encode('utf-8')).hexdigest()


def identity(root=ROOT):
    def git(*args):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=20)
        return result.stdout.strip() if result.returncode == 0 else None
    version = root / 'source-version.json'
    fallback = read(version).get('gitCommit') if version.is_file() else None
    commit = git('rev-parse', 'HEAD')
    mapping = dict(registrySha256='src/main/resources/stock-slot-registry-v1.json',
                   fieldRulesSha256='docs/project-field-rules.md',
                   policySha256='config/acceptance/project-data-policy-v1.json',
                   manifestSha256='data/doris/snapshots/stock-20060104-20260414-v1/manifest.json',
                   compilerJarSha256='target/dsl-doris-compiler.jar')
    return dict(gitCommit=commit or fallback, gitMetadataAvailable=commit is not None,
                gitDirty=bool(git('status', '--porcelain')) if commit else None,
                sourceSha256=source_digest(root),
                **{key: digest(root / value) if (root / value).is_file() else None for key, value in mapping.items()},
                matrices={p: digest(root / p) if (root / p).is_file() else None for p in MATRICES})


def capture_doris_environment(distribution):
    """Read actual owned runtime state, not an expected policy/default snapshot."""
    from run_correctness import WslDoris
    from check_project_window_performance import owned_runtime_environment
    return owned_runtime_environment(WslDoris(distribution, 'dsl-doris-official'))


def verify_environment_report(proof, frozen):
    """Cross-check matrix/resource report state against the run's frozen state."""
    if 'environment' not in proof:
        return
    observed = proof['environment']
    required = {'containerMemoryBytes', 'containerNanoCpus', 'beMemoryShare',
                'beRuntimeSettings', 'beConfigurationSha256', 'feRuntime'}
    if (not isinstance(observed, dict) or not required.issubset(observed) or
            set(observed) - set(frozen) or any(observed[k] != frozen[k] for k in observed)):
        raise ValueError('Stage environment evidence differs from the frozen run environment')


def verify_report(report, expected=('PASS',), formal_blocked=False):
    """A zero command exit is insufficient: validate the machine result and cleanup."""
    if report.get('status') not in expected:
        raise ValueError('Unexpected machine status: ' + str(report.get('status')))
    if report.get('cleanup') == 'FAILED' or report.get('fixtureCleanup') == 'FAILED' or report.get('cleanupErrors'):
        raise ValueError('Temporary environment cleanup failed')
    if report.get('fatalError'):
        raise ValueError('Machine report contains fatalError')
    resource_stability = report.get('purpose') == 'PROJECT_FINAL_COMBINATION_RESOURCE_STABILITY'
    if (resource_stability or 'timeoutStatus' in report or 'restartStatus' in report) and (report.get('timeoutStatus') != 'PASS_REAL_JDBC_CONTROL'
            or report.get('restartStatus') != 'PASS_PROCESS_RESTART_HOST_CACHE_RETAINED'):
        raise ValueError('Complete stability acceptance requires real timeout and restart evidence')
    if resource_stability and report.get('restartRequested') is not True:
        raise ValueError('Complete stability acceptance requires explicitly requested retained-data restart')
    for name in ('checks', 'executions'):
        collection = report.get(name, [])
        collection = collection.values() if isinstance(collection, dict) else collection
        for entry in collection:
            if 'status' in entry and entry['status'] != 'PASS':
                raise ValueError('Failed or unexecuted nested ' + name)
            flags = entry.get('checks', {})
            if isinstance(flags, dict) and any(v is False for v in flags.values()):
                raise ValueError('False nested correctness check')
    if 'passed' in report and 'total' in report and report['passed'] != report['total']:
        raise ValueError('Incomplete machine result')
    if formal_blocked and (report.get('cases') != [] or report.get('overall', {}).get('accuracy') is not None):
        raise ValueError('Expected BLOCKED formal gate with zero executed cases and null accuracy')


def verify_certificate(folder, expected_identity, max_age_hours=24, now=None):
    """Age is an orchestration contract; does not change the compiler certificate format."""
    folder = Path(folder)
    report, cert = read(folder / 'source-validation-report.json'), read(folder / 'project-validation.json')
    verify_report(report, ('PROJECT_READY_WITH_LIMITATIONS',))
    if report.get('officialRegistryUnchanged') is not True:
        raise ValueError('Official registry changed during source validation')
    if report.get('certificateSha256') != digest(folder / 'project-validation.json'):
        raise ValueError('Certificate damaged or replaced')
    if report.get('jarSha256') != expected_identity['compilerJarSha256']:
        raise ValueError('Certificate was made with a different compiler JAR')
    if cert.get('manifestSha256') != expected_identity['manifestSha256'] or report.get('manifestSha256') != expected_identity['manifestSha256']:
        raise ValueError('Certificate source manifest changed')
    if cert.get('status') != 'PROJECT_READY_WITH_LIMITATIONS' or cert.get('definitionAuthority') != 'PROJECT_INTERNAL':
        raise ValueError('Wrong certificate authority')
    if set(cert.get('sources', {})) != {'basic', 'extension', 'code'} or any(v.get('status') != 'PROJECT_READY' for v in cert['sources'].values()):
        raise ValueError('The combined acceptance matrix requires all three project sources')
    stamp = datetime.fromisoformat(report['completedAtUtc'])
    if stamp.tzinfo is None:
        raise ValueError('Certificate timestamp must include its timezone')
    current = now or datetime.now(timezone.utc)
    age = current - stamp
    if max_age_hours <= 0 or age < -timedelta(minutes=5) or age > timedelta(hours=max_age_hours):
        raise ValueError('Project certificate is expired or future-dated; create a fresh run')
    return digest(folder / 'project-validation.json')


def verify_raw_precheck(report, execution_dir, matrix_path, expected_count, expected_identity,
                        certificate_sha256, oracle=None):
    """One complete raw round is a semantic gate, never performance evidence."""
    verify_report(report)
    matrix = read(matrix_path)
    if (not isinstance(matrix, list) or len(matrix) != expected_count or
            any(not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'] for c in matrix)):
        raise ValueError('Raw precheck requires the complete frozen matrix')
    names = [c['name'] for c in matrix]
    if len(set(names)) != len(names) or read(Path(execution_dir) / 'matrix.json') != matrix:
        raise ValueError('Raw precheck matrix changed or contains duplicate cases')
    if (report.get('matrixScope') != 'FULL_MATRIX' or type(report.get('rounds')) is not int or
            report['rounds'] != 1 or report.get('originalCaseNames') != names or
            report.get('passed') != expected_count or report.get('total') != expected_count):
        raise ValueError('Raw precheck must execute every frozen case exactly once')
    before = report.get('sourceStateBefore')
    if (report.get('cleanup') != 'DONE' or report.get('cleanupErrors') != [] or
            not isinstance(before, list) or len(before) != 2 or not before[0] or before[1] != [] or
            report.get('sourceStateAfter') != before or
            not isinstance(report.get('environment'), dict) or not report['environment']):
        raise ValueError('Raw precheck source/environment preservation and cleanup evidence required')
    if (report.get('jarSha256') != expected_identity['compilerJarSha256'] or
            report.get('certificateSha256') != certificate_sha256):
        raise ValueError('Raw precheck JAR or certificate identity differs')
    if expected_identity.get('dorisEnvironment') is not None:
        if report['environment'] != expected_identity['dorisEnvironment']:
            raise ValueError('Raw precheck environment differs from the frozen run environment')
    required_checks = {'strict-registry-empty', 'raw-reference-lock', 'http-started',
        'sources-unchanged', 'environment-unchanged', 'artifacts-unchanged', 'field-oracle-unchanged'}
    if oracle:
        required_checks.add('combination-oracle-unchanged')
    checks = report.get('checks', [])
    if (not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks) or
            len({c.get('name') for c in checks}) != len(checks) or
            not required_checks.issubset({c.get('name') for c in checks}) or
            any(c.get('status') != 'PASS' for c in checks)):
        raise ValueError('Raw precheck required preservation checks are incomplete')
    executions = report.get('executions', [])
    required_flags = {'keysEqual', 'inputsEqual', 'samplesEqual', 'observedEqual',
        'missingExtensionEqual', 'coverageStatusEqual', 'completeResult', 'internalAuthority',
        'certificateEqual', 'resourcePolicyEqual'}
    limits = dict(queryTimeoutSeconds=10, maxEstimatedScanRows=100000000,
                  maxReturnRows=10000, maxExecutionMemoryBytes=2147483648)
    if not isinstance(executions, list) or len(executions) != expected_count:
        raise ValueError('Raw precheck execution coverage is incomplete')
    observed = []
    for entry in executions:
        if not isinstance(entry, dict):
            raise ValueError('Raw precheck execution record must be an object')
        flags, actual_limits = entry.get('checks', {}), entry.get('limits', {})
        if (type(entry.get('round')) is not int or entry['round'] != 1 or
                entry.get('httpStatus') != 200 or entry.get('status') != 'PASS' or
                not isinstance(flags, dict) or not required_flags.issubset(flags) or
                any(value is not True for value in flags.values()) or
                not isinstance(actual_limits, dict) or any(actual_limits.get(k) != v for k, v in limits.items())):
            raise ValueError('Raw precheck correctness/resource evidence is incomplete')
        observed.append(entry.get('case'))
    if observed != names:
        raise ValueError('Raw precheck execution cases/order differ from the frozen matrix')


def verify_rsi_precision(report, expected_identity):
    """Keep exact normal fixtures and the observed finite-precision limit separate."""
    verify_report(report, ('PASS_WITH_FINITE_PRECISION_LIMIT',))
    if (report.get('passed') != 24 or report.get('total') != 24 or
            report.get('fixtureCleanup') != 'DONE' or report.get('cleanupErrors') != [] or
            report.get('sourceStateUnchanged') is not True or report.get('artifactsUnchanged') is not True or
            report.get('formalRegistryUnchanged') is not True or
            report.get('jarSha256') != expected_identity['compilerJarSha256'] or
            report.get('declaredOutputType') != 'DECIMAL(38,12)' or
            report.get('notInfiniteRationalProof') is not True or
            report.get('notAllSignedBigintStrictComparisonProof') is not True):
        raise ValueError('Incomplete or incorrectly scoped RSI precision evidence')
    before = report.get('sourceStateBefore')
    if (not isinstance(before, dict) or not before.get('rows') or before.get('formalRegistry') != [] or
            report.get('sourceStateAfter') != before):
        raise ValueError('RSI precision source/registry preservation evidence required')
    expected = {(f'rsi{n}-{op}-50', mode) for n in (5, 5000)
                for op in ('=', '!=', '>', '>=', '<', '<=') for mode in ('project', 'reference')}
    checks = report.get('checks', [])
    if (len(checks) != 24 or {(c.get('case'), c.get('mode')) for c in checks} != expected or
            any(c.get('strictExactActual') != c.get('strictExactExpected') for c in checks)):
        raise ValueError('RSI normal-fixture strict comparisons are incomplete')
    limits = report.get('finitePrecisionLimitEvidence', [])
    if (len(limits) != 24 or {(c.get('case'), c.get('mode')) for c in limits} != expected or
            any(c.get('declaredOutputMatches') is not True or
                c.get('actual') != c.get('declared12PlaceExpected') or
                c.get('exactKeysEqual') is not (c.get('actual') == c.get('exactRationalExpected'))
                for c in limits) or report.get('precisionLimitComparisons') != 8 or
            sum(c.get('actual') != c.get('exactRationalExpected') for c in limits) != 8 or
            sum(c.get('status') == 'PRECISION_LIMIT_OBSERVED' for c in limits) != 8):
        raise ValueError('RSI finite-precision limit must be observed and explicitly retained')
    projections = report.get('projections', [])
    if (len(projections) != 4 or {(c.get('n'), c.get('mode')) for c in projections} !=
            {(n, mode) for n in (5, 5000) for mode in ('project', 'reference')} or
            any(c.get(key) is not True for c in projections
                for key in ('decimalScale12', 'keysEqual', 'finiteOutputValuesEqual'))):
        raise ValueError('RSI finite-value native projection evidence is incomplete')


def artifact_hashes(folder):
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob('*')) if p.is_file()}


class StageRunner:
    """Immutable attempt directories, fail-fast reporting, verified phase resume."""
    def __init__(self, folder, run_identity, resume=False, environment_probe=None):
        self.folder = Path(folder).resolve()
        self.identity = run_identity
        self.environment_probe = environment_probe
        path = self.folder / 'project-summary.json'
        if resume:
            old = read(path)
            if old.get('identity') != run_identity:
                raise ValueError('Resume refused: code, JAR, registry, rules, manifest, matrices or reference database changed')
            self.report = old
            self.report['status'] = 'RUNNING'
            self.report.setdefault('attempts', []).append(dict(startedAtUtc=datetime.now(timezone.utc).isoformat()))
        else:
            if self.folder.exists():
                raise ValueError('Use a new output directory; existing evidence will not be overwritten')
            self.folder.mkdir(parents=True)
            self.report = dict(formatVersion='project-acceptance-v1', status='RUNNING', identity=run_identity,
                officialAcceptanceEligible=False, formalAcceptanceStatus='NOT_RUN', stages=[],
                startedAtUtc=datetime.now(timezone.utc).isoformat(), attempts=[])
        self.save()

    def check_environment(self, boundary):
        if self.environment_probe is None:
            return
        frozen = self.identity.get('dorisEnvironment')
        try:
            observed = self.environment_probe()
        except Exception as error:
            self.report.setdefault('environmentChecks', []).append(dict(boundary=boundary,
                status='FAIL', reason='Owned runtime unavailable: ' + type(error).__name__))
            self.save()
            raise ValueError('Owned runtime unavailable at stage boundary: ' + boundary) from None
        ok = frozen is not None and observed == frozen
        self.report.setdefault('environmentChecks', []).append(dict(boundary=boundary,
            status='PASS' if ok else 'FAIL', observed=observed))
        self.save()
        if not ok:
            raise ValueError('Frozen Doris environment changed at stage boundary: ' + boundary)

    def save(self):
        path = self.folder / 'project-summary.json'
        pending = path.with_suffix('.pending.json')
        pending.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Windows readers / antivirus can briefly deny DELETE sharing during an
        # atomic replacement. Retry only that transient permission class; keep
        # the previous summary and pending evidence if the lock does not clear.
        for attempt in range(20):
            try:
                pending.replace(path)
                break
            except PermissionError:
                if attempt==19:raise
                time.sleep(.05)
        rows = ['# 项目优化清单验收结果', '', f"状态：`{self.report['status']}`。正式验收：`{self.report['formalAcceptanceStatus']}`。", '',
                '| 阶段 | 状态 | 证据 |', '|---|---|---|']
        for stage in self.report['stages']:
            detail = str(stage.get('reason', stage.get('directory', ''))).replace('|', '\\|').replace('\n', ' ')
            rows.append(f"| {stage['name']} | {stage['status']} | {detail} |")
        rows.extend(['', 'NOT_RUN 不计为通过。项目内部参考一致性不替代外部盲测；BLOCKED 不等于准确率 0%。',
                     '', 'raw-*-precheck 为完整矩阵单轮语义预检，不纳入每例至少 30 次的性能样本。',
                     '', f"代码：`{self.identity.get('gitCommit')}`；工作树有改动：`{self.identity.get('gitDirty')}`。",
                     f"源码 SHA256：`{self.identity['sourceSha256']}`。", f"JAR SHA256：`{self.identity.get('compilerJarSha256')}`。", ''])
        (self.folder / 'REPORT.md').write_text('\n'.join(rows), encoding='utf-8')

    def not_run(self, name, reason):
        if not any(s['name'] == name and s['status'] == 'NOT_RUN' for s in self.report['stages']):
            self.report['stages'].append(dict(name=name, status='NOT_RUN', reason=reason))
        self.save()

    def stage(self, name, command_factory, report_name='result.json', expected=('PASS',),
              exit_codes=(0,), timeout=7200, formal_blocked=False, proof_validator=None):
        self.check_environment(name + ':before')
        for prior in reversed(self.report['stages']):
            if prior['name'] == name and prior['status'] in ('PASS', 'EXPECTED_BLOCKED'):
                folder = self.folder / prior['directory']
                if not folder.is_dir() or artifact_hashes(folder) != prior['artifactHashes']:
                    raise ValueError('Resume refused: phase artifacts changed: ' + name)
                proof = read(folder / report_name)
                verify_report(proof, expected, formal_blocked)
                if self.environment_probe is not None:
                    verify_environment_report(proof, self.identity['dorisEnvironment'])
                if proof_validator:
                    proof_validator(proof, folder)
                self.check_environment(name + ':reused-after')
                print('Reusing verified phase ' + name, flush=True)
                return folder
        attempt = sum(s['name'] == name for s in self.report['stages']) + 1
        folder = self.folder / f'{name}-attempt-{attempt:03}'
        folder.mkdir()
        stage = dict(name=name, status='RUNNING', directory=folder.name)
        self.report['stages'].append(stage)
        self.save()
        print('Starting ' + name, flush=True)
        start = time.monotonic()
        try:
            with (folder / 'command.log').open('wb') as log:
                result = subprocess.run(command_factory(folder), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            stage['exitCode'] = result.returncode
            self.check_environment(name + ':after')
            if result.returncode not in exit_codes:
                raise RuntimeError(f'{name}: command exit {result.returncode}; see {folder / "command.log"}')
            proof = read(folder / report_name)
            verify_report(proof, expected, formal_blocked)
            if self.environment_probe is not None:
                verify_environment_report(proof, self.identity['dorisEnvironment'])
            if proof_validator:
                proof_validator(proof, folder)
            stage.update(status='EXPECTED_BLOCKED' if formal_blocked else 'PASS',
                         machineStatus=proof['status'], artifactHashes=artifact_hashes(folder))
        except Exception as error:
            stage.update(status='FAIL', reason=str(error), artifactHashes=artifact_hashes(folder))
            raise
        finally:
            stage['elapsedSeconds'] = round(time.monotonic() - start, 3)
            self.save()
        print('Completed ' + name, flush=True)
        return folder


def preflight(args):
    checks = []
    for module in ('duckdb', 'openpyxl'):
        checks.append(dict(name=module, status='PASS' if importlib.util.find_spec(module) else 'NOT_RUN', reason='Install scripts/doris/requirements-selftest.txt'))
    try:
        java = subprocess.run([args.java, '-version'], capture_output=True, timeout=20)
        checks.append(dict(name='java', status='PASS' if java.returncode == 0 else 'NOT_RUN'))
    except (OSError, subprocess.TimeoutExpired) as error:
        checks.append(dict(name='java', status='NOT_RUN', reason=str(error)))
    if not (ROOT / 'target/dsl-doris-compiler.jar').is_file():
        checks.append(dict(name='compiler-jar', status='NOT_RUN', reason='Build the current source first: mvn test package'))
    if args.with_doris:
        if not args.restart:
            checks.append(dict(name='requested-restart-validation', status='NOT_RUN', reason='Complete project acceptance requires explicit --restart for the labelled private container'))
        from run_correctness import WslDoris
        try:
            client = WslDoris(args.distribution, 'dsl-doris-official')
            if client.query('SELECT 1') != [('1',)]:
                raise ValueError('Doris health response invalid')
            checks.append(dict(name='owned-real-doris', status='PASS'))
        except Exception as error:
            checks.append(dict(name='owned-real-doris', status='NOT_RUN', reason=str(error)))
        if not args.reference_database.is_file():
            checks.append(dict(name='raw-independent-reference', status='NOT_RUN', reason='Verified raw DuckDB reference is missing: ' + str(args.reference_database)))
        elif reference_identity(args.reference_database)['pendingWal']:
            checks.append(dict(name='raw-independent-reference', status='FAIL', reason='Reference has an uncheckpointed WAL; freeze a closed reference before acceptance'))
        manifest = read(ROOT / 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json')
        for table, item in manifest['files'].items():
            path = args.data_root / item['relativePath']
            if not path.is_file():
                checks.append(dict(name='source-' + table, status='NOT_RUN', reason=str(path)))
            else:
                actual=digest(path)
                checks.append(dict(name='source-' + table, status='PASS' if actual==item['sha256'] and path.stat().st_size==item['bytes'] else 'FAIL',
                                   reason=str(path),sha256=actual,expectedSha256=item['sha256']))
    status='FAIL' if any(c['status']=='FAIL' for c in checks) else 'PASS' if all(c['status']=='PASS' for c in checks) else 'NOT_RUN'
    return dict(status=status, checks=checks)


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True, type=Path)
    parser.add_argument('--java', default='java')
    parser.add_argument('--with-doris', action='store_true')
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--data-root', type=Path, default=ROOT.parent)
    parser.add_argument('--reference-database', type=Path, default=ROOT / 'target/data-audit/acceptance-a0f7260.duckdb')
    parser.add_argument('--rounds', type=int, default=30)
    parser.add_argument('--matrix-timeout-seconds',type=int,default=43200,
                        help='Wall-clock cap for each full 30-round matrix; does not change the Doris 10-second query limit')
    parser.add_argument('--restart', action='store_true', help='Restart only the labelled private diagnostic container; never a cold-cache claim')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-certificate-age-hours', type=float, default=24)
    args = parser.parse_args()
    if args.rounds < 30 or args.max_certificate_age_hours <= 0 or args.matrix_timeout_seconds<=0:
        parser.error('Performance evidence requires >=30 rounds and a positive certificate lifetime')
    # Imports after --help, so environment prechecks work without test dependencies.
    sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
    selected = dict(withDoris=args.with_doris, distribution=args.distribution, dataRoot=str(args.data_root.resolve()),
                    referenceDatabase=str(args.reference_database.resolve()), rounds=args.rounds, restart=args.restart,
                    matrixTimeoutSeconds=args.matrix_timeout_seconds,
                    maxCertificateAgeHours=args.max_certificate_age_hours, java=args.java, python=sys.executable,
                    rawPrecheck=dict(RAW_PRECHECK_CONTRACT, enabled=args.with_doris),
                    environmentFreezeVersion='owned-runtime-v2-fe-process',
                    automaticSleepPrevention=dict(SYSTEM_SLEEP_PREVENTION))
    run_identity = identity()
    run_identity['executionOptions'] = selected
    run_identity['rawReference'] = reference_identity(args.reference_database, args.with_doris)
    runtime = dict(status='DISABLED', environment=None)
    if args.with_doris:
        try:
            runtime = dict(status='PASS', environment=capture_doris_environment(args.distribution))
        except Exception as error:
            runtime = dict(status='NOT_RUN', environment=None,
                           reason='Owned runtime unavailable: ' + type(error).__name__)
    run_identity['dorisEnvironment'] = runtime['environment']
    # Preserve an existing immutable binding when the current daemon is absent;
    # no stage may execute in this path. Available-but-changed state is refused.
    try:
        if args.resume and runtime['status'] == 'NOT_RUN':
            run_identity['dorisEnvironment'] = read(args.report_dir / 'project-summary.json')['identity'].get('dorisEnvironment')
        runner = StageRunner(args.report_dir, run_identity, args.resume,
            environment_probe=(lambda: capture_doris_environment(args.distribution)) if args.with_doris else None)
    except (ValueError, OSError, KeyError) as error:
        if not args.resume:
            raise
        if not args.report_dir.is_dir():
            print('Resume refused: saved report directory is unavailable', file=sys.stderr)
            return 1
        refusal = args.report_dir / ('resume-refusal-' + str(time.time_ns()) + '.json')
        refusal.write_text(json.dumps(dict(status='FAIL', reason=str(error), observedRuntime=runtime),
            ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Resume refused; see ' + str(refusal), file=sys.stderr)
        return 1
    py = [sys.executable, '-X', 'utf8']
    real_stages = ('sources', 'native-numeric-comparisons', 'native-ma-precision', 'native-rsi-precision', 'native-fields', 'native-combinations', 'native-rank-combinations',
                   'raw-official-field-matrix-precheck', 'raw-official-combinations-precheck', 'raw-official-rank-combinations-precheck',
                   'official-field-matrix', 'official-field-verification', 'official-combinations',
                   'official-combination-explanations', 'official-rank-combinations', 'official-rank-explanations',
                   'official-field-matrix-timings','official-combinations-timings','official-rank-combinations-timings',
                   'resource-stability', 'strict-gates', 'formal-gate')
    try:
        environment = preflight(args)
        environment['runtimeFreeze'] = runtime
        if args.with_doris and runtime['status'] != 'PASS':
            environment['checks'].append(dict(name='frozen-owned-runtime', status='NOT_RUN', reason=runtime['reason']))
            if environment['status'] != 'FAIL':
                environment['status'] = 'NOT_RUN'
        (runner.folder / 'environment-preflight.json').write_text(json.dumps(environment, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if environment['status']=='FAIL':
            raise ValueError('Immutable raw source verification failed; see environment-preflight.json')
        if environment['status'] != 'PASS':
            runner.not_run('environment', '; '.join(c.get('reason', c['name']) for c in environment['checks'] if c['status'] != 'PASS'))
            for name in real_stages:
                runner.not_run(name, 'Required real environment or raw source unavailable')
            runner.report.update(status='NOT_RUN', completedAtUtc=datetime.now(timezone.utc).isoformat())
            runner.save()
            return 2
        for label, filename in (('portable-fields', 'check_project_fields.py'),
                                ('portable-combinations', 'check_project_combinations.py'),
                                ('portable-rank-combinations', 'check_project_rank_combinations.py')):
            runner.stage(label, lambda f, file=filename: py + ['scripts/doris/' + file, '--output', str(f / 'result.json'), '--java', args.java,
                                                              '--matrix-output', str(f / 'matrix.json')])
        # The compiler benchmark's machine format has no status; a dedicated verifier publishes its status.
        runner.stage('compiler-performance', lambda f: py + ['scripts/doris/check_project_performance_evidence.py',
            '--compiler', '--java', args.java, '--output-dir', str(f)])
        if not args.with_doris:
            for name in real_stages:
                runner.not_run(name, 'Run explicitly with --with-doris and the immutable raw sources')
            if identity()['sourceSha256'] != run_identity['sourceSha256'] or digest(ROOT/'target/dsl-doris-compiler.jar') != run_identity['compilerJarSha256']:
                raise ValueError('Source or JAR changed during acceptance')
            runner.report.update(status='PASS_OFFLINE_REAL_NOT_RUN', completedAtUtc=datetime.now(timezone.utc).isoformat())
            runner.save()
            return 0
        sources = runner.stage('sources', lambda f: py + ['scripts/doris/validate_project_sources.py', '--output-dir', str(f),
            '--distribution', args.distribution, '--java', args.java, '--data-root', str(args.data_root.resolve())],
            report_name='source-validation-report.json', expected=('PROJECT_READY_WITH_LIMITATIONS',))
        runner.report['certificateSha256'] = verify_certificate(sources, run_identity, args.max_certificate_age_hours)
        cert = sources / 'project-validation.json'
        runner.stage('native-numeric-comparisons', lambda f: py + ['scripts/doris/check_project_numeric_comparisons.py',
            '--output', str(f / 'result.json'), '--java', args.java, '--distribution', args.distribution])
        runner.stage('native-ma-precision', lambda f: py + ['scripts/doris/check_project_ma_precision.py',
            '--execute', '--output-dir', str(f / 'execution'), '--java', args.java, '--distribution', args.distribution],
            report_name='execution/result.json')
        runner.stage('native-rsi-precision', lambda f: py + ['scripts/doris/check_project_rsi_precision.py',
            '--execute', '--report-dir', str(f / 'execution'), '--java', args.java,
            '--distribution', args.distribution], report_name='execution/result.json',
            expected=('PASS_WITH_FINITE_PRECISION_LIMIT',),
            proof_validator=lambda proof, folder: verify_rsi_precision(proof, run_identity))
        runner.report['numericLimitations'] = [dict(indicator='RSI(N)', outputType='DECIMAL(38,12)',
            precisionLimitComparisons=8, notAllSignedBigintStrictComparisonProof=True,
            reason='Extreme raw BIGINT ratios strictly above 50 can truncate to 50; retained in native-rsi-precision, not counted as exact normal-fixture PASS.')]
        for label, file in (('native-fields', 'check_project_fields.py'), ('native-combinations', 'check_project_combinations.py'),
                            ('native-rank-combinations', 'check_project_rank_combinations.py')):
            runner.stage(label, lambda f, file=file: py + ['scripts/doris/' + file, '--output', str(f / 'result.json'),
                '--java', args.java, '--native-fixture', '--distribution', args.distribution])
        suites = [('official-field-matrix', 'portable-fields', 'official-field-verification', 'check_project_fields.py',None),
                  ('official-combinations', 'portable-combinations', 'official-combination-explanations', 'check_project_combinations.py','project_combination_reference'),
                  ('official-rank-combinations', 'portable-rank-combinations', 'official-rank-explanations', 'check_project_rank_combinations.py','project_rank_reference')]
        # Complete all raw semantic gates before spending 30 rounds on any one
        # matrix. The precheck attempt directories are never timing inputs.
        for label, portable_label, _, _, oracle in suites:
            phase = next(s for s in runner.report['stages'] if s['name'] == portable_label and s['status'] == 'PASS')
            matrix = runner.folder / phase['directory'] / 'matrix.json'
            expected_count = RAW_PRECHECK_CONTRACT['caseCounts'][label]
            runner.stage('raw-' + label + '-precheck', lambda f, matrix=matrix, oracle=oracle: py + [
                'scripts/doris/check_project_window_performance.py', '--certificate', str(cert),
                '--output-dir', str(f / 'execution'), '--rounds', '1', '--matrix', str(matrix),
                '--field-oracle', '--explain', '--distribution', args.distribution, '--java', args.java,
                '--reference-database', str(args.reference_database.resolve()),
                *(['--oracle-module', oracle] if oracle else [])], report_name='execution/result.json',
                timeout=args.matrix_timeout_seconds,
                proof_validator=lambda proof, folder, matrix=matrix, count=expected_count, oracle=oracle:
                    verify_raw_precheck(proof, folder / 'execution', matrix, count, run_identity,
                                        runner.report['certificateSha256'], oracle))
        for label, portable_label, verification_label, verifier,oracle in suites:
            phase = next(s for s in runner.report['stages'] if s['name'] == portable_label and s['status'] == 'PASS')
            matrix = runner.folder / phase['directory'] / 'matrix.json'
            output = runner.stage(label, lambda f: py + ['scripts/doris/check_project_window_performance.py',
                '--certificate', str(cert), '--output-dir', str(f / 'execution'), '--rounds', str(args.rounds),
                '--matrix', str(matrix), '--field-oracle', '--explain', '--distribution', args.distribution,
                '--java', args.java, '--reference-database', str(args.reference_database.resolve()),
                *(['--oracle-module',oracle] if oracle else [])], report_name='execution/result.json',timeout=args.matrix_timeout_seconds)
            command = ['--execution-dir', str(output / 'execution'), '--certificate', str(cert)]
            if verifier == 'check_project_fields.py':
                command += ['--values-native']
            runner.stage(verification_label, lambda f: py + ['scripts/doris/' + verifier, '--output', str(f / 'result.json'),
                '--java', args.java, '--distribution', args.distribution, '--reference-database', str(args.reference_database.resolve()), *command])
            runner.stage(label+'-timings',lambda f:py+['scripts/doris/check_project_performance_evidence.py',
                '--execution-dir',str(output/'execution'),'--output-dir',str(f)])
        runner.stage('resource-stability', lambda f: py + ['scripts/doris/check_project_resource_stability.py',
            '--certificate', str(cert), '--output-dir', str(f / 'execution'), '--distribution', args.distribution,
            '--java', args.java, '--matrix', str(ROOT / MATRICES[0]), '--reference-database', str(args.reference_database.resolve()),
            *(['--restart'] if args.restart else [])], report_name='execution/result.json')
        runner.stage('strict-gates', lambda f: py + ['scripts/doris/check_wsl_execution_gate.py', '--report-dir', str(f),
            '--distribution', args.distribution, '--java', args.java], report_name='controlled-execution-gate.json')
        runner.stage('formal-gate', lambda f: py + ['scripts/accuracy/run_correctness.py', '--output-dir', str(f),
            '--wsl-distribution', args.distribution, '--container', 'dsl-doris-official', '--java', args.java],
            expected=('BLOCKED',), exit_codes=(3,), formal_blocked=True)
        verify_certificate(sources, run_identity, args.max_certificate_age_hours)
        final_environment=preflight(args)
        runner.check_environment('final')
        (runner.folder/'environment-final.json').write_text(json.dumps(final_environment,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if final_environment['status']!='PASS':raise ValueError('Source files or execution environment changed during acceptance')
        if reference_identity(args.reference_database) != run_identity['rawReference']:
            raise ValueError('Independent reference database changed during acceptance')
        if identity()['sourceSha256'] != run_identity['sourceSha256'] or digest(ROOT / 'target/dsl-doris-compiler.jar') != run_identity['compilerJarSha256']:
            raise ValueError('Source or JAR changed during acceptance')
        runner.report.update(status='PROJECT_PASS_FORMAL_BLOCKED', formalAcceptanceStatus='BLOCKED', completedAtUtc=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        runner.report.update(status='FAIL', error=str(error), completedAtUtc=datetime.now(timezone.utc).isoformat())
        runner.save()
        print(str(error), file=sys.stderr)
        return 1
    runner.save()
    return 0


def main():
    global SYSTEM_SLEEP_PREVENTION
    with AutomaticSleepPrevention() as evidence:
        SYSTEM_SLEEP_PREVENTION = dict(evidence)
        return _main()


if __name__ == '__main__':
    raise SystemExit(main())
