"""Read-only consumer compatibility over a frozen RAW reference; not blind accuracy."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re

import duckdb
from build_reference_duckdb import READY, file_identity, read_json
from project_field_reference import KEYS, load
from project_rank_reference import reference


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report', type=Path, required=True)
    parser.add_argument('--doris-result', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--memory-limit', default='1GB')
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError('Do not overwrite previous compatibility evidence')
    if re.fullmatch(r'[1-9][0-9]*(?:MB|GB)', args.memory_limit) is None:
        raise ValueError('Use a bounded MB/GB memory limit')
    report = dict(purpose='READ_ONLY_REFERENCE_CONSUMER_AND_DORIS_SMOKE_COMPARISON',
                  status='FAIL', officialAcceptanceEligible=False, checks=[],
                  generatedSqlUsedForOracle=False, dorisExportUsedForDatabase=False)
    try:
        build = read_json(args.build_report)
        artifact = read_json(args.doris_result)
        if build['status'] not in READY or build['buildStatus'] != 'PASS':
            raise ValueError('Reference construction is not ready')
        database = Path(build['database'])
        before = file_identity(database)
        if before != build['databaseIdentity'] or before['pendingWal']:
            raise ValueError('Closed RAW reference identity changed after construction')

        def check(name, actual, expected):
            passed = actual == expected
            report['checks'].append(dict(name=name, status='PASS' if passed else 'FAIL', actual=actual, expected=expected))
            if not passed:
                raise AssertionError(name)

        check('same-doris-snapshot', artifact['dataVersion']['snapshotId'], build['snapshotId'])
        check('same-doris-manifest', artifact['dataVersion']['manifestSha256'], build['manifestSha256'])
        with duckdb.connect(str(database), read_only=True) as con:
            con.execute("SET memory_limit='" + args.memory_limit + "'")
            con.execute('SET threads=1')
            con.execute('SET preserve_insertion_order=false')
            con.execute("SET temp_directory='" + (str(database) + '.tmp').replace('\\', '/').replace("'", "''") + "'")
            lock = con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchall()
            check('legacy-consumer-source-lock', [list(row) for row in lock],
                  [[build['snapshotId'], build['manifestSha256'], 'FAIL']])
            # Exercise the existing 19-field Decimal oracle on every latest-day
            # security; two observed rows keep Python's object memory bounded.
            source = load(con, '2026-04-14', retained_rows=2)
            expected_observed = con.execute("SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic WHERE bizdate=DATE '2026-04-14'").fetchone()[0]
            check('raw-history-consumer-population', len(source['histories']), expected_observed)
            check('history-date-and-budget', all(1 <= len(h) <= 2 and h[-1]['date'] == '2026-04-14' for h in source['histories'].values()), True)
            check('all-19-manual-metrics-available', all(set(h[-1]['normalized']) == set(KEYS) for h in source['histories'].values()), True)
            raw_sample = con.execute("SELECT mktcode,tgtcode FROM newzl.hsj_stock_hq_basic WHERE bizdate=DATE '2026-04-14' AND closePx>10000 ORDER BY mktcode,tgtcode LIMIT 20").fetchall()
            raw_sample = [[str(m), code] for m, code in raw_sample]
            case = dict(calls=[dict(kind='field', metric='close')], market='',
                        expr=('cmp', 0, '>', Decimal(1)), limit=20)
            manual = reference(case, source)
            check('manual-oracle-vs-raw-integer-reference', manual['rows'], raw_sample)
            check('independent-reference-vs-real-doris-stock-order', manual['rows'], artifact['rows'])
            missing_close = sum(h[-1]['normalized']['close'] is None for h in source['histories'].values())
            expected_missing = con.execute("SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic WHERE bizdate=DATE '2026-04-14' AND closePx IS NULL").fetchone()[0]
            check('raw-null-preservation-through-manual-oracle', missing_close, expected_missing)
            report.update(observedSecurities=expected_observed, sourceNullClose=missing_close, returnedRows=len(manual['rows']))
        after = file_identity(database)
        check('reference-bytes-unchanged-after-read-only-consumer', after, before)
        report['databaseIdentity'] = after
        report['status'] = 'PASS'
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
    report['total'] = len(report['checks'])
    report['passed'] = sum(c['status'] == 'PASS' for c in report['checks'])
    report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: report.get(key) for key in ('status', 'passed', 'total', 'observedSecurities', 'returnedRows')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
