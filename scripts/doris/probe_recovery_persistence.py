"""Restart only the owned dedicated instance; prove data and old volumes survive."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris
SQL = ("SELECT 'basic',COUNT(*),CAST(MIN(bizdate) AS STRING),CAST(MAX(bizdate) AS STRING) FROM newzl.hsj_stock_hq_basic "
       "UNION ALL SELECT 'extension',COUNT(*),CAST(MIN(bizdate) AS STRING),CAST(MAX(bizdate) AS STRING) FROM newzl.hsj_stock_hq_ext "
       "UNION ALL SELECT 'code',COUNT(*),'','' FROM newzl.hsj_stock_code_info")


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=150, **kwargs)
    if result.returncode:
        raise RuntimeError('Recovery command failed: ' + result.stderr)
    return result.stdout.strip()


def desktop_snapshot(docker):
    host = command([docker, 'inspect', '-f', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', 'doris'])
    if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', host) is None:
        raise ValueError('Unexpected original container address')
    rows = command([docker, 'exec', '-i', 'doris', 'mysql', '--no-defaults', '-uroot', '--host', host,
        '--port', '9030', '--batch', '--skip-column-names', '--raw'], input=SQL + ';\n')
    registry = command([docker, 'exec', '-i', 'doris', 'mysql', '--no-defaults', '-uroot', '--host', host,
        '--port', '9030', '--batch', '--skip-column-names', '--raw'],
        input='SELECT snapshot_id,contract_version,manifest_sha256,status,loaded_at FROM newzl.data_snapshot_registry ORDER BY snapshot_id;\n')
    return dict(identity=command([docker, 'inspect', '-f', '{{.ID}} {{.State.Status}} {{.State.Health.Status}} {{.RestartCount}}', 'doris']),
                volumes=json.loads(command([docker, 'inspect', '-f', '{{json .Mounts}}', 'doris'])), rows=rows, registry=registry)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--docker', default='C:/Program Files/Docker/Docker/resources/bin/docker.exe')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve old evidence; use a new output filename')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    client = WslDoris(args.distribution, 'dsl-doris-official')
    if command(client.prefix + ['info', '--format', '{{.DockerRootDir}}']) != '/var/lib/dsl-doris/docker':
        raise ValueError('Refusing non-project daemon')
    report = dict(purpose='PERSISTENCE_PROBE_ONLY_OWNED_INSTANCE', checks=[])
    report['originalBefore'] = desktop_snapshot(args.docker)
    report['dedicatedBefore'] = client.query(SQL)
    report['viewsBefore'] = client.query("SELECT TABLE_NAME,SHA2(VIEW_DEFINITION,256) FROM information_schema.views WHERE TABLE_SCHEMA='newzl' ORDER BY TABLE_NAME")
    report['registryBefore'] = client.query('SELECT * FROM newzl.data_snapshot_registry')
    try:
        command(client.prefix + ['restart', 'dsl-doris-official'])
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = command(client.prefix + ['inspect', '-f', '{{.State.Status}} {{.State.Health.Status}}', 'dsl-doris-official'])
            if state == 'running healthy':
                break
            time.sleep(1)
        else:
            raise RuntimeError('Dedicated restart did not become healthy')
        report['dedicatedAfter'] = client.query(SQL)
        report['viewsAfter'] = client.query("SELECT TABLE_NAME,SHA2(VIEW_DEFINITION,256) FROM information_schema.views WHERE TABLE_SCHEMA='newzl' ORDER BY TABLE_NAME")
        report['registryAfter'] = client.query('SELECT * FROM newzl.data_snapshot_registry')
        report['originalAfter'] = desktop_snapshot(args.docker)
        for name, passed in [('dedicated-counts-and-dates-preserved', report['dedicatedBefore'] == report['dedicatedAfter']),
                             ('semantic-views-preserved', report['viewsBefore'] == report['viewsAfter']),
                             ('empty-official-registry-preserved', report['registryBefore'] == report['registryAfter'] == []),
                             ('original-container-data-and-volumes-unchanged', report['originalBefore'] == report['originalAfter'])]:
            report['checks'].append(dict(name=name, status='PASS' if passed else 'FAIL'))
        report['status'] = 'PASS' if all(row['status'] == 'PASS' for row in report['checks']) else 'FAIL'
    except Exception as error:
        report.update(status='FAIL', error=str(error))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(report['checks'])}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
