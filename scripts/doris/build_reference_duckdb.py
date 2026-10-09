"""Build a new, immutable RAW CSV reference, not a replica of Doris query results.

This safe entry point never replaces an existing database or report. Known source
anomalies retain their original audit FAIL/WARN status; they are not SQL accuracy.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

import duckdb
from audit_official_data import ROOT, NAMES, KEYS, ddl_columns, digest, qi, run_audit

DEFAULT_MANIFEST = ROOT / 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json'
DEFAULT_KNOWN_AUDIT = ROOT / 'reports/data-inspection/2026-10-04/全量数据检查.json'
KNOWN_SOURCE_CHECKS = {'extensionWithoutBasic', 'close_price_range'}
READY = {'REFERENCE_READY', 'REFERENCE_READY_WITH_SOURCE_LIMITATIONS'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def file_identity(path):
    path = Path(path)
    wal = Path(str(path) + '.wal')
    return dict(path=str(path.resolve()), sha256=digest(path), bytes=path.stat().st_size,
                pendingWal=wal.exists() and wal.stat().st_size > 0)


def preflight_sources(data_root, manifest, schema):
    """Validate every input before any database connection or data conversion."""
    root = Path(data_root).resolve(strict=True)
    if not root.is_dir() or set(manifest.get('files', {})) != set(NAMES):
        raise ValueError('Expected exactly the frozen three RAW CSV sources')
    if not isinstance(manifest.get('snapshotId'), str) or not manifest['snapshotId']:
        raise ValueError('Snapshot identity is required')
    sources = {}
    for name in NAMES:
        item = manifest['files'][name]
        relative = item.get('relativePath')
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError('A source requires a relativePath inside the supplied root')
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or path.name != name + '.csv' or not path.is_file():
            raise ValueError('Source escapes the selected root or has an unexpected name: ' + name)
        candidates = list(root.rglob(name + '.csv'))
        if len(candidates) != 1 or candidates[0].resolve() != path:
            raise ValueError('Ambiguous or incorrectly located source: ' + name)
        if isinstance(item.get('bytes'), bool) or not isinstance(item.get('bytes'), int) or item['bytes'] < 1:
            raise ValueError('Source size must be an explicit positive integer')
        if path.stat().st_size != item['bytes']:
            raise ValueError('Source byte size differs from the frozen manifest: ' + name)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            header = next(csv.reader(stream))
        if header != item.get('header') or len(header) != len(set(header)) or set(header) != set(schema[name]):
            raise ValueError('CSV header / typed RAW schema differs from the frozen manifest: ' + name)
        if not re.fullmatch(r'[0-9a-f]{64}', item.get('sha256', '')) or digest(path) != item['sha256']:
            raise ValueError('Source SHA256 differs from the frozen manifest: ' + name)
        if isinstance(item.get('rows'), bool) or not isinstance(item.get('rows'), int) or item['rows'] < 1:
            raise ValueError('Source row count must be an explicit positive integer')
        for key in ('nullCounts', 'sentinelMinus999999Counts'):
            if not isinstance(item.get(key), dict) or not set(item[key]).issubset(header):
                raise ValueError('Missing or invalid frozen field profile: ' + name)
            if any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= item['rows'] for n in item[key].values()):
                raise ValueError('Invalid frozen field count: ' + name)
        sources[name] = dict(path=str(path), bytes=item['bytes'], sha256=item['sha256'])
        print('[preflight] ' + name + ' SHA256 / bytes / header PASS', flush=True)
    return sources


def known_anomalies(path, manifest):
    if path is None:
        return {}, None
    report = read_json(path)
    if report.get('snapshotId') != manifest['snapshotId'] or set(report.get('tables', {})) != set(NAMES):
        raise ValueError('Historical audit is not for this complete frozen snapshot')
    for name, item in manifest['files'].items():
        observed = report['tables'][name]
        if any(observed.get(k) != item[k] for k in ('sha256', 'bytes', 'rows')):
            raise ValueError('Historical audit RAW identity differs: ' + name)
    checks = report.get('checks', [])
    if not isinstance(checks, list) or len({c.get('name') for c in checks}) != len(checks):
        raise ValueError('Historical checks are missing or ambiguous')
    allowed = {c['name']: dict(status=c['status'], detail=c['detail']) for c in checks
               if c.get('name') in KNOWN_SOURCE_CHECKS and c.get('status') in ('WARN', 'FAIL')}
    return allowed, dict(path=str(Path(path).resolve()), sha256=digest(Path(path)))


def assess_audit(audit, allowed):
    if audit.get('status') not in ('PASS_WITH_LIMITATIONS', 'FAIL') or audit.get('error'):
        raise ValueError('RAW audit did not complete successfully')
    checks = audit.get('checks', [])
    if not checks or len({c.get('name') for c in checks}) != len(checks):
        raise ValueError('RAW audit checks are missing or ambiguous')
    required = {name + ':' + suffix for name in NAMES
                for suffix in ('sha256', 'row_count', 'types', 'profile_counts', 'primary_keys')}
    required |= {name + ':dates' for name in NAMES[1:]}
    required |= {'extensionWithoutBasic', 'basicWithoutSecurityInfo', 'extensionWithoutSecurityInfo',
                 'basic_numeric_gate', 'close_price_range', 'price_amount_scale_cross_check'}
    if {c.get('name') for c in checks} != required:
        raise ValueError('RAW audit did not run the complete expected gate set')
    observed = {c['name']: dict(status=c.get('status'), detail=c.get('detail')) for c in checks}
    if any(observed.get(name) != expected for name, expected in allowed.items()):
        raise ValueError('Known source anomaly changed or disappeared from the audit')
    anomalies = []
    for check in checks:
        if check.get('status') == 'PASS':
            continue
        expected = allowed.get(check.get('name'))
        if check.get('name') not in KNOWN_SOURCE_CHECKS or expected != dict(status=check.get('status'), detail=check.get('detail')):
            raise ValueError('New / unapproved audit failure or warning: ' + str(check.get('name')))
        anomalies.append(check)
    if (audit['status'] == 'FAIL') != any(c['status'] == 'FAIL' for c in checks):
        raise ValueError('Audit status and detailed checks disagree')
    return anomalies


def reopen_and_verify(database, manifest, schema, audit_status, memory_limit, threads, temp_directory):
    """Read-only re-open verifies stored RAW values, never compiler SQL / views."""
    evidence, tables = [], {}
    with duckdb.connect(str(database), read_only=True) as con:
        con.execute("SET memory_limit='" + memory_limit + "'")
        con.execute('SET threads=' + str(threads))
        con.execute("SET temp_directory='" + Path(temp_directory).resolve().as_posix().replace("'", "''") + "'")

        def check(name, actual, expected):
            passed = actual == expected
            evidence.append(dict(name=name, status='PASS' if passed else 'FAIL', expected=expected, actual=actual))
            if not passed:
                raise ValueError('Closed reference verification failed: ' + name)

        lock = con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchall()
        check('audit-source-lock', [list(row) for row in lock],
              [[manifest['snapshotId'], manifest['_manifestSha256'], audit_status]])
        objects = con.execute("SELECT table_schema,table_name,table_type FROM information_schema.tables WHERE table_schema IN ('main','newzl') ORDER BY table_schema,table_name").fetchall()
        check('raw-only-persistent-objects', [list(row) for row in objects],
              [['main', 'audit_source_lock', 'BASE TABLE']] + [['newzl', name, 'BASE TABLE'] for name in sorted(NAMES)])
        for name in NAMES:
            item, columns = manifest['files'][name], manifest['files'][name]['header']
            relation = 'newzl.' + qi(name)
            observed_schema = con.execute('SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position', ['newzl', name]).fetchall()
            expected_schema = [[f, 'VARCHAR' if schema[name][f].startswith('VARCHAR') else
                               {'INT': 'INTEGER', 'DATETIME': 'TIMESTAMP'}.get(schema[name][f], schema[name][f])] for f in columns]
            check(name + ':stored-schema', [list(row) for row in observed_schema], expected_schema)
            expressions, labels = ['COUNT(*)'], ['rows']
            for field in columns:
                col = qi(field)
                expressions.append('COUNT(*) FILTER(WHERE ' + col + ' IS NULL)')
                labels.append('null:' + field)
                # Numeric sentinels are compared numerically: DOUBLE string casts
                # would render -999999.0 and miss a genuine sentinel.
                typ = schema[name][field]
                predicate = col + '=-999999' if typ in ('INT', 'BIGINT', 'TINYINT', 'DOUBLE') else "CAST(" + col + " AS VARCHAR)='-999999'"
                expressions.append('COUNT(*) FILTER(WHERE ' + predicate + ')')
                labels.append('sentinel:' + field)
            values = dict(zip(labels, con.execute('SELECT ' + ','.join(expressions) + ' FROM ' + relation).fetchone()))
            check(name + ':stored-row-count', values['rows'], item['rows'])
            nulls = {f: values['null:' + f] for f in columns}
            sentinels = {f: values['sentinel:' + f] for f in columns}
            check(name + ':stored-null-profile', nulls, {f: item['nullCounts'].get(f, 0) for f in columns})
            check(name + ':stored-sentinel-profile', sentinels, {f: item['sentinelMinus999999Counts'].get(f, 0) for f in columns})
            keys = ','.join(qi(field) for field in KEYS[name])
            null_keys = con.execute('SELECT COUNT(*) FROM ' + relation + ' WHERE ' +
                                    ' OR '.join(qi(field) + ' IS NULL' for field in KEYS[name])).fetchone()[0]
            duplicate_keys = con.execute('SELECT COUNT(*) FROM (SELECT ' + keys + ' FROM ' + relation +
                                         ' GROUP BY ' + keys + ' HAVING COUNT(*)>1)').fetchone()[0]
            check(name + ':stored-null-keys', null_keys, 0)
            check(name + ':stored-duplicate-key-groups', duplicate_keys, 0)
            date_range = [str(d) for d in con.execute('SELECT MIN(bizdate),MAX(bizdate) FROM ' + relation).fetchone()] if 'bizdate' in columns else None
            if date_range is not None:
                check(name + ':stored-date-range', date_range, [item['dateMin'], item['dateMax']])
            tables[name] = dict(rows=values['rows'], dateRange=date_range, nullCounts=nulls, sentinelCounts=sentinels,
                               nullKeys=null_keys, duplicateKeyGroups=duplicate_keys)
            print('[read-only reopen] ' + name + ' all stored profiles PASS', flush=True)
    return tables, evidence


def markdown(report):
    rows = ['# 独立参考 DuckDB 重建', '', '状态：`' + report['status'] + '`；构建：`' + report['buildStatus'] +
            '`；原始审计：`' + str(report.get('auditStatus', 'NOT_RUN')) + '`。', '',
            '从原 CSV 直接读取，仅存 RAW typed 表和审计锁；不从 Doris 导出，不使用编译器 SQL 构造期望。', '',
            '| 表 | 行数 | 日期范围 |', '|---|---:|---|']
    for name, item in report.get('tables', {}).items():
        rows.append('| ' + name + ' | ' + format(item['rows'], ',') + ' | ' + ('～'.join(item['dateRange']) if item['dateRange'] else '—') + ' |')
    identity = report.get('databaseIdentity', {})
    rows += ['', '数据库：`' + str(report['database']) + '`。', 'SHA256：`' + str(identity.get('sha256', 'NOT_FROZEN')) + '`。',
             '已知源异常继续保留原 FAIL/WARN；参考库可用不代表官方验收通过。',
             '用于后续只读差分时显式传入 `--reference-database`，不要自行修改 `audit_source_lock` 状态。', '']
    for anomaly in report.get('retainedSourceAnomalies', []):
        rows.append('- ' + anomaly['name'] + '：' + anomaly['status'] + '，' + str(anomaly['detail']))
    if report.get('error'):
        rows += ['', '阻断原因：' + str(report['error']), '部分数据库和失败证据均保留；不要将其用于验收。']
    return '\n'.join(rows) + '\n'


def build_reference(data_root, manifest_path, database, output_dir, *, memory_limit='2GB', threads=2, known_audit=None):
    database, output_dir, manifest_path = Path(database).resolve(), Path(output_dir).resolve(), Path(manifest_path).resolve()
    if output_dir.exists():
        raise FileExistsError('Preserve existing reports; use a new output directory')
    for path in (database, Path(str(database) + '.wal'), Path(str(database) + '.tmp'), Path(str(database) + '.build-lock.json')):
        if path.exists():
            raise FileExistsError('Preserve existing database / WAL / temporary evidence: ' + str(path))
    output_dir.mkdir(parents=True, exist_ok=False)
    report = dict(formatVersion='independent-raw-reference-build-v1', status='BLOCKED', buildStatus='BLOCKED',
                  auditStatus='NOT_RUN', officialAcceptanceEligible=False, database=str(database),
                  startedAtUtc=datetime.now(timezone.utc).isoformat(), checks=[], tables={},
                  sourceKind='IMMUTABLE_ORIGINAL_CSV', dorisExportUsed=False, compilerSqlUsed=False,
                  resources=dict(memoryLimit=memory_limit, threads=threads, tempDirectory=str(database) + '.tmp'),
                  limitations=['RAW source anomalies are retained, not silently cleaned or called official acceptance.',
                               'Observed market dates are not an authoritative suspension calendar.'])
    started = time.monotonic()
    try:
        if not re.fullmatch(r'[1-9][0-9]*(?:MB|GB)', memory_limit) or isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 32:
            raise ValueError('Invalid bounded resource settings')
        manifest_hash = digest(manifest_path)
        schema_hash = digest(ROOT / 'data/doris/ddl/001_rebuild_tables.sql')
        manifest = read_json(manifest_path)
        schema = ddl_columns()
        report.update(snapshotId=manifest['snapshotId'], contractVersion=manifest.get('contractVersion'),
                      manifestSha256=manifest_hash, schemaSha256=schema_hash)
        sources = preflight_sources(data_root, manifest, schema)
        report['sourcesBefore'] = sources
        allowed, known_identity = known_anomalies(known_audit, manifest)
        report['knownAuditIdentity'] = known_identity
        database.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive claim remains as evidence; never truncate a concurrently claimed DB.
        with Path(str(database) + '.build-lock.json').open('x', encoding='utf-8') as stream:
            json.dump(dict(snapshotId=manifest['snapshotId'], manifestSha256=manifest_hash,
                           database=str(database), outputDirectory=str(output_dir)), stream, indent=2)
        if database.exists() or Path(str(database) + '.wal').exists() or Path(str(database) + '.tmp').exists():
            raise FileExistsError('Database appeared after preflight; refusing to replace it')
        audit = run_audit(Path(data_root), manifest_path, database, output_dir / 'raw-audit',
                          memory_limit=memory_limit, threads=threads, temp_directory=Path(str(database) + '.tmp'))
        report['auditStatus'] = audit.get('status')
        if digest(manifest_path) != manifest_hash or digest(ROOT / 'data/doris/ddl/001_rebuild_tables.sql') != schema_hash:
            raise ValueError('Manifest / RAW DDL changed during construction')
        if known_identity and digest(Path(known_identity['path'])) != known_identity['sha256']:
            raise ValueError('Historical anomaly definition changed during construction')
        report['sourcesAfter'] = preflight_sources(data_root, manifest, schema)
        if report['sourcesAfter'] != sources:
            raise ValueError('Source files changed during construction')
        report['retainedSourceAnomalies'] = assess_audit(audit, allowed)
        with duckdb.connect(str(database)) as con:
            con.execute('CHECKPOINT')
        report['checkpoint'] = 'PASS'
        manifest['_manifestSha256'] = manifest_hash
        report['tables'], report['checks'] = reopen_and_verify(database, manifest, schema, audit['status'], memory_limit, threads, Path(str(database) + '.tmp'))
        report['readOnlyReopen'] = 'PASS'
        report['databaseIdentity'] = file_identity(database)
        if report['databaseIdentity']['pendingWal']:
            raise ValueError('Nonempty WAL remains; reference is not frozen')
        report['passed'] = sum(c['status'] == 'PASS' for c in report['checks'])
        report['total'] = len(report['checks'])
        report['buildStatus'] = 'PASS'
        report['status'] = 'REFERENCE_READY_WITH_SOURCE_LIMITATIONS' if report['retainedSourceAnomalies'] else 'REFERENCE_READY'
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
        report['partialDatabaseRetained'] = database.exists()
    report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
    report['elapsedSeconds'] = round(time.monotonic() - started, 3)
    # The directory was exclusively created by this call; no prior evidence is replaced.
    with (output_dir / 'reference-build.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    with (output_dir / 'REPORT.md').open('x', encoding='utf-8') as stream:
        stream.write(markdown(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--memory-limit', default='2GB')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--known-audit', type=Path, default=DEFAULT_KNOWN_AUDIT)
    args = parser.parse_args(argv)
    try:
        report = build_reference(args.data_root, args.manifest, args.database, args.output_dir,
                                 memory_limit=args.memory_limit, threads=args.threads, known_audit=args.known_audit)
    except FileExistsError as error:
        print(json.dumps(dict(status='BLOCKED', error=str(error))))
        return 2
    print(json.dumps({key: report.get(key) for key in ('status', 'buildStatus', 'auditStatus', 'passed', 'total')}, ensure_ascii=False))
    return 0 if report['status'] in READY else 2


if __name__ == '__main__':
    raise SystemExit(main())
