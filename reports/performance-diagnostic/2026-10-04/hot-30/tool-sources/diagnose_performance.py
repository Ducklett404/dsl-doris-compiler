"""Repeatable HOT diagnostic on unchanged official data; never grants acceptance."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--iterations', type=int, default=30)
    parser.add_argument('--matrix', type=Path, default=ROOT / 'benchmarks/doris-matrix-v1.json')
    parser.add_argument('--audit', type=Path, default=ROOT / 'reports/data-inspection/2026-10-04/全量数据检查.json')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports/performance-diagnostic/2026-10-04')
    args = parser.parse_args()
    if args.iterations < 1: parser.error('--iterations must be positive')
    folder = args.report_dir.resolve(); folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'diagnostic-summary.json').exists():
        raise ValueError('Choose a new report directory to preserve existing measurements')
    client = WslDoris(args.distribution, 'dsl-doris-official')
    registry_before = client.query('SELECT * FROM newzl.data_snapshot_registry')
    if registry_before: raise ValueError('Expected the unregistered diagnostic instance')
    matrix = json.loads(args.matrix.read_text(encoding='utf-8'))
    manifest_path = ROOT / 'data/doris/snapshots' / matrix['snapshotId'] / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    audit = json.loads(args.audit.read_text(encoding='utf-8'))
    if audit['snapshotId'] != manifest['snapshotId'] or any(
            audit['tables'][name]['sha256'] != item['sha256'] or audit['tables'][name]['rows'] != item['rows']
            for name, item in manifest['files'].items()):
        raise ValueError('Full-data audit provenance does not match the frozen manifest')
    loaded = {name: int(count) for name, count in client.query("SELECT 'hsj_stock_code_info',COUNT(*) FROM newzl.hsj_stock_code_info UNION ALL SELECT 'hsj_stock_hq_basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'hsj_stock_hq_ext',COUNT(*) FROM newzl.hsj_stock_hq_ext")}
    if loaded != {name: item['rows'] for name, item in manifest['files'].items()}:
        raise ValueError('Loaded row counts do not match the frozen manifest')
    address = subprocess.run(['wsl.exe', '-d', args.distribution, '--exec', 'hostname', '-I'],
        text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=15)
    hosts = re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', address.stdout)
    if address.returncode or not hosts: raise RuntimeError('Cannot resolve WSL IPv4')
    runtime = subprocess.run(['java', '-XshowSettings:properties', '-version'],
        text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=15)
    java_home = re.search(r'^\s*java.home\s*=\s*(.+)$', runtime.stderr, re.MULTILINE)
    if runtime.returncode or java_home is None: raise RuntimeError('Cannot locate Java')
    java = Path(java_home.group(1).strip()) / 'bin/java.exe'
    report = {'purpose': 'OFFICIAL_DATA_HOT_PERFORMANCE_DIAGNOSTIC', 'acceptanceEligible': False,
        'sourceAuditStatus': audit['status'],
        'unmatchedExtensionRows': audit['relationships']['extensionWithoutBasic']['rows'], 'sourceRows': loaded,
        'registeredSnapshotsBefore': len(registry_before), 'distribution': args.distribution,
        'dorisVersion': client.query("SHOW VARIABLES LIKE 'version_comment'")[0][1],
        'cacheLimitations': ['SQL result cache disabled; OS/BE page caches are warm.',
            'Single connection and isolated single-node diagnostic environment; no cold cache or concurrent load.',
            'Path equivalence checks the complete DSL-limited result including order; it is not independent official semantics.'],
        'hashes': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in {
            'compilerJar': ROOT/'target/dsl-doris-compiler.jar', 'manifest': manifest_path,
            'matrix': args.matrix, 'audit': args.audit, 'javaDiagnostic': ROOT/'scripts/doris/DorisPerformanceDiagnostic.java',
            'pythonDiagnostic': Path(__file__)}.items()}}
    username = 'dsl_perf_read_' + secrets.token_hex(6); password = secrets.token_hex(24)
    created = False
    try:
        client.query(f"CREATE USER '{username}' IDENTIFIED BY '{password}'"); created = True
        client.query(f"GRANT SELECT_PRIV ON newzl.* TO '{username}'")
        environment = os.environ.copy()
        environment.update(DORIS_DIAGNOSTIC_URL=f'jdbc:mysql://{hosts[0]}:9030/newzl?useSSL=false&allowPublicKeyRetrieval=true&connectTimeout=5000&socketTimeout=70000',
            DORIS_DIAGNOSTIC_USER=username, DORIS_DIAGNOSTIC_PASSWORD=password)
        command = [str(java), '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8',
            '-cp', str(ROOT/'target/dsl-doris-compiler.jar'),
            str(ROOT/'scripts/doris/DorisPerformanceDiagnostic.java'), str(args.matrix), str(folder), str(args.iterations)]
        with (folder/'progress.log').open('wb') as log:
            completed = subprocess.run(command, env=environment, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=7200)
        report['exitCode'] = completed.returncode
        result_path = folder/'jdbc-results.json'
        if result_path.exists(): report['measurements'] = json.loads(result_path.read_text(encoding='utf-8'))
    finally:
        if created:
            client.query(f"DROP USER '{username}'")
            report['temporaryReaderRemoved'] = True
        registry_after = client.query('SELECT * FROM newzl.data_snapshot_registry')
        report['registeredSnapshotsAfter'] = len(registry_after)
        report['officialRegistryUnchanged'] = registry_before == registry_after
        report['completedAtUtc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (folder/'diagnostic-summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    measurements = report.get('measurements', {})
    print(f"Measured {measurements.get('passed', 0)}/{measurements.get('total', 0)} cases; report: {folder}")
    return report.get('exitCode', 1)


if __name__ == '__main__': sys.exit(main())
