"""Recheck memory-cancelled cases, preserving all previous evidence and provenance."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

import check_official_field_acceptance as oracle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='D:/Java/jdk-21/bin/java.exe')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve existing test evidence; use a fresh output path')
    report = json.loads(args.previous.read_text(encoding='utf-8'))
    root = oracle.ROOT
    jar = root / 'target/dsl-doris-compiler.jar'
    manifest = root / 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json'
    assert report['jarSha256'] == oracle.digest(jar)
    assert report['manifestSha256'] == oracle.digest(manifest)
    assert report['oracleSha256'] == oracle.digest(root / 'scripts/doris/check_official_position_values.py')
    assert 'fatalError' not in report and report['total'] == 171
    assert len(report['fieldDomainChecks']) == 19 and all(r['status'] == 'PASS' for r in report['fieldDomainChecks'])
    pending = [r for r in report['results'] if r['status'] != 'PASS']
    assert pending and all(r['status'] == 'ERROR' and '[MEM_LIMIT_EXCEEDED]' in r['error'] for r in pending)
    integrity = []
    for table, item in json.loads(manifest.read_text())['files'].items():
        path = root.parent / item['relativePath']
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert digest == item['sha256'] and path.stat().st_size == item['bytes']
        integrity.append({'table': table, 'sha256': digest, 'status': 'PASS'})
    con = oracle.duckdb.connect(str(args.database), read_only=True)
    client = oracle.WslDoris(args.distribution, 'dsl-doris-official')
    report['retryEvidence'] = {'previousReportSha256': oracle.digest(args.previous),
        'previousReport': str(args.previous.resolve()), 'previousPassed': report['passed'],
        'retriedCases': len(pending), 'sourceIntegrity': integrity, 'results': [],
        'policy': 'Only resource-cancelled ERROR cases may be retried; result mismatches require a fresh diagnostic.'}
    try:
        lock = con.execute('SELECT snapshot_id,manifest_sha256 FROM audit_source_lock').fetchone()
        assert lock == ('stock-20060104-20260414-v1', report['manifestSha256'])
        with tempfile.TemporaryDirectory(prefix='position-resource-retry-') as directory:
            for date in sorted({row['date'] for row in pending}):
                rows = con.execute('WITH tail AS MATERIALIZED (SELECT mktcode,tgtcode,bizdate,' + ','.join(oracle.RAW_COLUMNS) +
                    ' FROM newzl.hsj_stock_hq_basic WHERE bizdate<=CAST(? AS DATE) QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=5) '
                    'SELECT t.*,e.ZJLXMainNetTur net FROM tail t LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) ORDER BY mktcode,tgtcode,bizdate', [date]).fetchall()
                histories = defaultdict(list)
                for market, code, day, *values in rows:
                    histories[(int(market), code)].append((str(day), oracle.raw_values(dict(zip((*oracle.RAW_COLUMNS, 'net'), values)))))
                for record in [row for row in pending if row['date'] == date]:
                    index = next(i for i, item in enumerate(oracle.FIELDS) if item[0] == record['metric'])
                    expected = []
                    for key, history in sorted(histories.items()):
                        if history[-1][0] != date or len(history) < 5:
                            continue
                        values = [r[1][index] for r in history[-5:]]
                        if any(v is None for v in values):
                            continue
                        low, high, current = min(values), max(values), values[-1]
                        if low == high:
                            continue
                        label = '低' if 3 * (current - low) <= high - low else ('高' if 3 * (current - low) >= 2 * (high - low) else '中')
                        if label == record['category']:
                            expected.append(key)
                    assert len(expected) == record['referenceRows']
                    original = dict(record)
                    artifact = oracle.compile_case(args.java, jar, record['dsl'], Path(directory) / 'case.dsl', lock[0])
                    actual = [(int(m), code) for m, code in client.query(oracle.bind_sql(artifact['sql'], artifact['bindings']))]
                    record.pop('error')
                    record.update(status='PASS' if actual == expected else 'FAIL', actualRows=len(actual),
                        onlyActual=sorted(set(actual) - set(expected))[:10], onlyExpected=sorted(set(expected) - set(actual))[:10],
                        sql=artifact['sql'], bindings=artifact['bindings'])
                    report['retryEvidence']['results'].append({'original': original, 'retestedStatus': record['status']})
                    print(f"{date} {record['metric']} {record['category']}: {record['status']}", flush=True)
        assert oracle.digest(jar) == report['jarSha256']
        assert client.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry') == [('0',)]
    except Exception as error:
        report['fatalError'] = str(error)
        raise
    finally:
        con.close()
        report['passed'] = sum(row['status'] == 'PASS' for row in report['results'])
        report['status'] = 'PASS' if 'fatalError' not in report and report['passed'] == 171 else 'FAIL'
        report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'passed', 'total')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
