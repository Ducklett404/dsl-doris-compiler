"""Real, read-only JDBC smoke test; credentials never enter reports or arguments."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='D:/java/bin/java.exe')
    parser.add_argument('--certificate', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    client = WslDoris(args.distribution, 'dsl-doris-official')
    secret = subprocess.run(['wsl.exe', '-d', args.distribution, '--exec', 'sed', '-n',
        's/^password=//p', '/var/lib/dsl-doris/reader.cnf'], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=20)
    password = secret.stdout.strip()
    if secret.returncode or re.fullmatch('[0-9a-f]{48}', password) is None:
        raise ValueError('Read-only runtime credential is unavailable')
    address = subprocess.run(['wsl.exe', '-d', args.distribution, '--exec', 'hostname', '-I'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, timeout=20)
    host = address.stdout.split()[0]
    if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', host) is None:
        raise ValueError('Unexpected WSL address')
    environment = os.environ.copy()
    environment['DSL_RECOVERY_READER_PASSWORD'] = password
    base = [args.java, '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8',
        '-jar', str(ROOT / 'target/dsl-doris-compiler.jar'), 'execute-stock-slot-sql',
        str(ROOT / 'examples/project-basic.dsl'), '--host', host, '--port', str(client.query_port),
        '--database', 'newzl', '--user', 'dsl_project_reader', '--password-env', 'DSL_RECOVERY_READER_PASSWORD',
        '--project-validation', str(args.certificate.resolve()), '--max-scan-rows', '100000000',
        '--max-exec-memory-bytes', '536870912', '--max-return-rows', '20', '--max-rows', '20']
    with (ROOT / 'target/dsl-doris-compiler.jar').open('rb') as stream:
        jar_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = {'purpose': 'REAL_READ_ONLY_JDBC_RECOVERY_SMOKE_NOT_ACCURACY_ACCEPTANCE', 'checks': [],
        'jarSha256': jar_digest}
    for name, format_name in [('query-json', 'json'), ('query-markdown', 'markdown')]:
        result = subprocess.run(base + ['--format', format_name], env=environment, cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        clean_error = result.stderr.replace(password, '[REDACTED]')
        record = dict(name=name, exitCode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
        if clean_error:
            record['stderr'] = clean_error
        if result.returncode == 0:
            content = result.stdout.replace(password, '[REDACTED]')
            (args.output_dir / ('result.json' if format_name == 'json' else 'result.md')).write_text(content, encoding='utf-8')
            if format_name == 'json':
                artifact = json.loads(content)
                report['returnedRows'] = len(artifact.get('rows', []))
                report['queryMillis'] = artifact.get('timings', {}).get('dorisExecutionMillis')
                report['timings'] = artifact.get('timings')
                report['dataQuality'] = artifact.get('dataQuality')
                record['status'] = 'PASS' if 0 < report['returnedRows'] <= 20 else 'FAIL'
                # Independent reference deliberately reads RAW integer prices,
                # not the derived view or the compiler's generated SQL.
                reference_sql = ("SELECT mktcode,tgtcode FROM newzl.hsj_stock_hq_basic "
                    "WHERE bizdate='2026-04-14' AND closePx>10000 ORDER BY mktcode,tgtcode LIMIT 20")
                reference = [list(row) for row in client.query(reference_sql)]
                report['checks'].append(dict(name='raw-price-reference-result-and-order',
                    status='PASS' if artifact['rows'] == reference else 'FAIL',
                    sql=reference_sql, expected=reference, actual=artifact['rows']))
            else:
                record['status'] = 'PASS' if '| ' in content else 'FAIL'
        report['checks'].append(record)
    report['status'] = 'PASS' if all(item['status'] == 'PASS' for item in report['checks']) else 'FAIL'
    (args.output_dir / 'execution-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report.get(key) for key in ('status', 'returnedRows', 'queryMillis')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
