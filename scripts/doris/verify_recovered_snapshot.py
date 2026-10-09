"""Read-only verification of a recovered, project-owned Doris diagnostic snapshot.

PASS means restored rows and sampled formulas agree with the frozen project
contract. It never registers an official VALIDATED snapshot or modifies Doris.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris

TABLES = ('hsj_stock_code_info', 'hsj_stock_hq_basic', 'hsj_stock_hq_ext')
KEYS = {table: ('mktcode', 'tgtcode') + (() if table == TABLES[0] else ('bizdate',)) for table in TABLES}
CLEAN_COLUMNS = ('ZJLXMainNetTurInDays', 'ZJLXMainNetTurOutDays',
                 'ZJLXMainNetTurInSeries', 'ZJLXMainNetTurOutSeries',
                 'pxMkTopDays', 'mainTurMkTopDays')
ABS_TOLERANCE, REL_TOLERANCE = 1e-8, 1e-12


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identifier(value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError('Unsafe SQL identifier')
    return '`' + value + '`'


def qualified(table):
    if table not in TABLES and table not in ('v_hsj_stock_hq_basic', 'v_hsj_stock_hq_ext', 'data_snapshot_registry'):
        raise ValueError('Source table is outside the frozen recovery contract')
    return 'newzl.' + identifier(table)


def literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if '\0' in text:
        raise ValueError('NUL is not permitted in a sample key')
    return "'" + text.replace('\\', '\\\\').replace("'", "''") + "'"


def ddl_schema(path=ROOT / 'data/doris/ddl/001_rebuild_tables.sql'):
    schemas = {}
    for table, body in re.findall(r'CREATE TABLE\s+(\w+)\s*\((.*?)\n\)', Path(path).read_text(encoding='utf-8'), re.S):
        if table not in TABLES:
            continue
        fields = re.findall(r'(?:^|,)\s*(\w+)\s+([A-Z]+(?:\([^)]*\))?)\s+(NOT\s+NULL|NULL)', body, re.S)
        schemas[table] = {name: dict(type=kind, nullable=nullable == 'NULL') for name, kind, nullable in fields}
    if set(schemas) != set(TABLES) or any(not schemas[name] for name in TABLES):
        raise ValueError('Cannot read all three frozen DDL schemas')
    return schemas


def type_family(kind):
    base = kind.upper().split('(')[0].strip()
    return {'INTEGER': 'INT', 'DATETIMEV2': 'DATETIME', 'DATEV2': 'DATE', 'BOOL': 'BOOLEAN'}.get(base, base)


def matching_type(expected, actual):
    first, second = expected.upper().replace(' ', ''), actual.upper().replace(' ', '')
    # Doris' MySQL metadata exposes canonical display widths, not storage
    # precision. Keep the allow-list exact: tinyint(1) means BOOLEAN here,
    # while ordinary TINYINT is tinyint(4). Never strip arbitrary parentheses
    # from VARCHAR/DECIMAL/DATETIME or admit an unknown integer width.
    aliases = {'DATETIMEV2(0)': 'DATETIME', 'DATETIMEV2': 'DATETIME', 'DATEV2': 'DATE', 'INTEGER': 'INT', 'BOOL': 'BOOLEAN',
               'INT(11)': 'INT', 'BIGINT(20)': 'BIGINT', 'TINYINT(4)': 'TINYINT', 'TINYINT(1)': 'BOOLEAN'}
    return aliases.get(first, first) == aliases.get(second, second)


def typed_value(value, kind, *, null=False, empty_is_null=True):
    if null or value is None or (empty_is_null and value == ''):
        return None
    family = type_family(kind)
    text = str(value)
    if family in ('TINYINT', 'SMALLINT', 'INT', 'BIGINT', 'LARGEINT'):
        number = Decimal(text)
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError('Non-integral CSV value for an integer field')
        return int(number)
    if family in ('DOUBLE', 'FLOAT', 'DECIMAL'):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError('Non-finite numeric value')
        return number
    if family == 'BOOLEAN':
        lowered = text.lower()
        if lowered not in ('0', '1', 'true', 'false'):
            raise ValueError('Invalid boolean field')
        return lowered in ('1', 'true')
    if family == 'DATE':
        return date.fromisoformat(text).isoformat()
    if family == 'DATETIME':
        parsed = datetime.fromisoformat(text.replace('T', ' '))
        if parsed.tzinfo is not None:
            raise ValueError('Timezone is not part of the frozen DATETIME contract')
        return parsed.isoformat(sep=' ')
    if family in ('VARCHAR', 'CHAR', 'STRING'):
        return text
    raise ValueError('Unsupported frozen field type: ' + family)


def equivalent(expected, actual):
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, float) or isinstance(actual, float):
        return math.isclose(expected, actual, abs_tol=ABS_TOLERANCE, rel_tol=REL_TOLERANCE)
    return expected == actual


def semantic_values(raw):
    """Independent Python oracle, using each SQL operand's DOUBLE conversion."""
    def price(field):
        return None if raw[field] is None else float(raw[field]) / 10000.0

    def adjusted(field, prefix):
        values = (price(field), raw[prefix + 'Multi'], raw[prefix + 'Add'])
        return None if any(value is None for value in values) else values[0] * float(values[1]) + float(values[2])

    values = {name + 'Price': price(field) for name, field in (
        ('last', 'lastPx'), ('preClose', 'preClosePx'), ('open', 'openPx'),
        ('high', 'highPx'), ('low', 'lowPx'), ('close', 'closePx'))}
    values['quanRatio'] = raw['quantRatio']
    for target, source, divisor in (('turnoverAmount', 'turnover', 100.0),
                                    ('quantityRatio', 'quantRatio', 10000.0),
                                    ('turnoverRatio', 'turnRatio', 10000.0),
                                    ('trueTurnoverRatio', 'trueTurnRatio', 10000.0)):
        values[target] = None if raw[source] is None else float(raw[source]) / divisor
    for target, shares in (('marketValue', 'totalShare'), ('listedMarketValue', 'listedShare')):
        values[target] = None if raw['lastPx'] is None or raw[shares] is None else float(raw['lastPx']) / 10000.0 * raw[shares]
    values['risePct'] = (None if raw['preClosePx'] in (None, 0) or raw['lastPx'] is None
                         else (float(raw['lastPx']) - float(raw['preClosePx'])) * 100.0 / float(raw['preClosePx']))
    values['avgPx'] = (None if raw['volume'] in (None, 0) or raw['turnover'] is None
                       else float(raw['turnover']) / (100.0 * float(raw['volume'])))
    for name in ('open', 'high', 'low', 'close'):
        for prefix in ('qfq', 'hfq'):
            values[name + prefix.title()] = adjusted(name + 'Px', prefix)
    return values


def clean_value(raw):
    return None if raw is None or raw == -999999 else raw


def year_shards(table, expected):
    """Disjoint, exhaustive calendar-year ranges, never a sample of the rows."""
    if table not in TABLES:
        raise ValueError('Unexpected recovery table')
    if table == TABLES[0]:
        return [dict(year=None, startInclusive=None, endExclusive=None, where='')]
    start, end = date.fromisoformat(expected['dateMin']), date.fromisoformat(expected['dateMax'])
    if start > end or end.year == 9999:
        raise ValueError('Invalid manifest date range for year partitioning')
    result = []
    for year in range(start.year, end.year + 1):
        low, high = f'{year:04}-01-01', f'{year + 1:04}-01-01'
        result.append(dict(year=year, startInclusive=low, endExclusive=high,
                           where=' WHERE `bizdate`>=' + literal(low) + ' AND `bizdate`<' + literal(high)))
    return result


def validate_prepared(prepared_dir, manifest_path, schemas):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    certificate_path = Path(prepared_dir) / 'prepared-snapshot.json'
    prepared = json.loads(certificate_path.read_text(encoding='utf-8'))
    manifest_hash = digest(manifest_path)
    if set(manifest['files']) != set(TABLES) or set(prepared['files']) != set(TABLES):
        raise ValueError('Recovery needs exactly the three frozen source tables')
    if prepared.get('status') != 'PASS' or prepared.get('snapshotId') != manifest['snapshotId'] or prepared.get('manifestSha256') != manifest_hash:
        raise ValueError('Prepared source certificate does not match the frozen manifest')
    integrity = []
    for table in TABLES:
        original, source = manifest['files'][table], prepared['files'][table]
        header = original['header']
        if header != list(schemas[table]) or source.get('header') != header:
            raise ValueError('CSV header differs from the real DDL: ' + table)
        if not set(original.get('nullCounts', {})) <= set(header) or not set(original.get('sentinelMinus999999Counts', {})) <= set(header):
            raise ValueError('Manifest names an unknown count field: ' + table)
        if source.get('rows') != original['rows'] or source.get('sourceSha256') != original['sha256']:
            raise ValueError('Prepared original source identity mismatch: ' + table)
        parts = source.get('parts', [])
        if not parts or sum(part['rows'] for part in parts) != original['rows']:
            raise ValueError('Prepared part row counts do not cover the source: ' + table)
        seen = set()
        for index, part in enumerate(parts):
            if part.get('file') != f'part-{index:05}.csv' or part['rows'] <= 0 or re.fullmatch(r'[0-9a-f]{64}', part.get('sha256', '')) is None:
                raise ValueError('Unsafe or incomplete normalized part metadata: ' + table)
            path = Path(prepared_dir) / table / part['file']
            if path.is_symlink() or not path.is_file() or digest(path) != part['sha256']:
                raise ValueError('Normalized CSV part changed or is missing: ' + table + '/' + part['file'])
        samples = source.get('samples', [])
        if not samples:
            raise ValueError('No deterministic RAW samples: ' + table)
        for sample in samples:
            if set(sample) != set(header) or any(not isinstance(value, str) for value in sample.values()):
                raise ValueError('Incomplete RAW sample: ' + table)
            raw = {field: typed_value(sample[field], kind['type']) for field, kind in schemas[table].items()}
            key = tuple(raw[field] for field in KEYS[table])
            if None in key or key in seen:
                raise ValueError('Null or repeated sample key: ' + table)
            seen.add(key)
        integrity.append(dict(table=table, sourceSha256=source['sourceSha256'], parts=len(parts),
                              rows=source['rows'], sampledRows=len(samples), normalizedPartsStatus='PASS'))
    return manifest, prepared, dict(manifestSha256=manifest_hash, preparedCertificateSha256=digest(certificate_path), files=integrity)


class ReadOnlyQueries:
    def __init__(self, client):
        self.client, self.evidence = client, []

    def query(self, sql):
        if not sql.startswith('SELECT ') or ';' in sql or re.search(r'\b(INTO|OUTFILE|DUMPFILE)\b', sql, re.I):
            raise ValueError('Recovery verifier permits only one generated read-only SELECT')
        started = time.perf_counter()
        try:
            rows = self.client.query(sql)
            self.evidence.append(dict(sql=sql, elapsedMs=(time.perf_counter() - started) * 1000, returnedRows=len(rows), status='PASS'))
            return rows
        except Exception:
            self.evidence.append(dict(sql=sql, elapsedMs=(time.perf_counter() - started) * 1000, status='BLOCKED'))
            raise


def select_row(query, table, columns, key):
    fields = ','.join(identifier(column) for column in columns)
    flags = ','.join(identifier(column) + ' IS NULL' for column in columns)
    where = ' AND '.join(identifier(column) + '=' + literal(value) for column, value in key.items())
    rows = query.query('SELECT ' + fields + ',' + flags + ' FROM ' + qualified(table) + ' WHERE ' + where + ' LIMIT 2')
    if len(rows) != 1 or len(rows[0]) != 2 * len(columns):
        raise ValueError('Expected exactly one full sample row from ' + table)
    values, nulls = rows[0][:len(columns)], rows[0][len(columns):]
    if any(flag not in ('0', '1') for flag in nulls):
        raise ValueError('Malformed explicit NULL indicators')
    return {column: (None if flag == '1' else value) for column, value, flag in zip(columns, values, nulls)}


def verify(client, manifest, prepared, schemas, integrity):
    query = ReadOnlyQueries(client)
    report = dict(formatVersion='recovered-snapshot-verification-v1', status='BLOCKED',
                  purpose='PROJECT_INTERNAL_RECOVERY_NOT_OFFICIAL_ACCEPTANCE', snapshotId=manifest['snapshotId'],
                  contractVersion=manifest['contractVersion'], sourceIntegrity=integrity, tables={}, checks=[],
                  sqlEvidence=query.evidence, formulaTolerance=dict(absolute=ABS_TOLERANCE, relative=REL_TOLERANCE),
                  globalAssociationCheck='NOT_RUN_DELEGATED_TO_validate_project_sources.py',
                  officialRegistrationAction='NONE_READ_ONLY', limitations=[
                      'PASS only verifies this recovery against the frozen project contract, not an official VALIDATED snapshot.',
                      'RAW values are verified on deterministic prepared samples; aggregate counts cover all restored rows.',
                      'Global extension-to-basic orphan checks must run separately, without concurrent large joins.'],
                  aggregationStrategy='SEQUENTIAL_CALENDAR_YEAR_SHARDS', resourceBudgetChange='NONE_2GIB_RETAINED')

    def check(name, passed, **detail):
        report['checks'].append(dict(name=name, status='PASS' if passed else 'BLOCKED', **detail))

    try:
        registry_sql = 'SELECT snapshot_id,contract_version,manifest_sha256,status,loaded_at FROM ' + qualified('data_snapshot_registry') + ' ORDER BY snapshot_id'
        registry_before = query.query(registry_sql)
        report['snapshotRegistryBefore'] = registry_before
        check('diagnostic-not-officially-registered', not any(row[3] == 'VALIDATED' for row in registry_before))
        for table in TABLES:
            schema, expected = schemas[table], manifest['files'][table]
            header, keys = list(schema), KEYS[table]
            observed = query.query('SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE FROM information_schema.columns '
                                   "WHERE TABLE_SCHEMA='newzl' AND TABLE_NAME=" + literal(table) + ' ORDER BY ORDINAL_POSITION')
            schema_ok = (len(observed) == len(header) and all(
                len(row) == 3 and row[0] == field and matching_type(schema[field]['type'], row[1])
                and row[2] == ('YES' if schema[field]['nullable'] else 'NO') for field, row in zip(header, observed)))
            check(table + ':schema', schema_ok, expected=schema, actual=observed)
            if not schema_ok:
                continue
            numeric = [field for field in header if type_family(schema[field]['type']) in
                       ('TINYINT', 'SMALLINT', 'INT', 'BIGINT', 'LARGEINT', 'FLOAT', 'DOUBLE', 'DECIMAL')]
            full_expressions = ['COUNT(*)'] + (['MIN(bizdate)', 'MAX(bizdate)'] if 'bizdate' in keys else [])
            full_stats = query.query('SELECT ' + ','.join(full_expressions) + ' FROM ' + qualified(table))
            if len(full_stats) != 1 or len(full_stats[0]) != len(full_expressions):
                raise ValueError('Unexpected full-table count/date result for ' + table)
            count = int(full_stats[0][0])
            dates = None
            if 'bizdate' in keys:
                dates = list(full_stats[0][1:3])
                check(table + ':date-range', dates == [expected['dateMin'], expected['dateMax']], actual=dates,
                      expected=[expected['dateMin'], expected['dateMax']])
            check(table + ':row-count', count == expected['rows'], expected=expected['rows'], actual=count)
            nullkey_rows = query.query('SELECT COUNT(*) FROM ' + qualified(table) + ' WHERE ' + ' OR '.join(identifier(key) + ' IS NULL' for key in keys))
            if len(nullkey_rows) != 1 or len(nullkey_rows[0]) != 1:
                raise ValueError('Unexpected null-key result')
            nullkeys = int(nullkey_rows[0][0])
            check(table + ':non-null-keys', nullkeys == 0, actual=nullkeys)
            nulls, sentinels = dict.fromkeys(header, 0), dict.fromkeys(numeric, 0)
            table_report = dict(rows=count, dateRange=dates, nullCounts=nulls, sentinelMinus999999Counts=sentinels,
                                duplicateKeyGroups=0, duplicateExcessRows=0, nullKeys=nullkeys,
                                aggregationShards=[], shardRows=0, samples=[])
            report['tables'][table] = table_report
            expressions = ['COUNT(*)']
            expressions += ['COALESCE(SUM(CASE WHEN ' + identifier(field) + ' IS NULL THEN 1 ELSE 0 END),0)' for field in header]
            expressions += ['COALESCE(SUM(CASE WHEN ' + identifier(field) + '=-999999 THEN 1 ELSE 0 END),0)' for field in numeric]
            shards = year_shards(table, expected)
            for shard in shards:
                where = shard['where']
                aggregate_rows = query.query('SELECT ' + ','.join(expressions) + ' FROM ' + qualified(table) + where)
                if len(aggregate_rows) != 1 or len(aggregate_rows[0]) != len(expressions):
                    raise ValueError('Unexpected year-shard aggregate result for ' + table)
                aggregate = list(map(int, aggregate_rows[0]))
                if any(value < 0 for value in aggregate):
                    raise ValueError('Negative aggregate count')
                shard_nulls = dict(zip(header, aggregate[1:1 + len(header)]))
                shard_sentinels = dict(zip(numeric, aggregate[1 + len(header):]))
                for field in header:
                    nulls[field] += shard_nulls[field]
                for field in numeric:
                    sentinels[field] += shard_sentinels[field]
                table_report['shardRows'] += aggregate[0]
                # bizdate is part of the unique key: the same key cannot
                # occur in two disjoint years, so per-year groups are exact.
                duplicates = query.query('SELECT COUNT(*),COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) AS n FROM ' + qualified(table)
                                         + where + ' GROUP BY ' + ','.join(identifier(key) for key in keys) + ' HAVING COUNT(*)>1) duplicate_keys')
                if len(duplicates) != 1 or len(duplicates[0]) != 2:
                    raise ValueError('Malformed year-shard duplicate key result')
                duplicate_groups, duplicate_excess = map(int, duplicates[0])
                if duplicate_groups < 0 or duplicate_excess < 0:
                    raise ValueError('Negative duplicate count')
                table_report['duplicateKeyGroups'] += duplicate_groups
                table_report['duplicateExcessRows'] += duplicate_excess
                table_report['aggregationShards'].append(dict(
                    year=shard['year'], startInclusive=shard['startInclusive'], endExclusive=shard['endExclusive'],
                    rows=aggregate[0], nullCounts=shard_nulls, sentinelMinus999999Counts=shard_sentinels,
                    duplicateKeyGroups=duplicate_groups, duplicateExcessRows=duplicate_excess))
            check(table + ':year-shard-row-coverage', table_report['shardRows'] == count,
                  expectedFullTableRows=count, actualShardRows=table_report['shardRows'], shardCount=len(shards))
            check(table + ':primary-key-unique', table_report['duplicateKeyGroups'] == table_report['duplicateExcessRows'] == 0,
                  duplicateGroups=table_report['duplicateKeyGroups'], duplicateExcessRows=table_report['duplicateExcessRows'])
            for field in header:
                check(table + ':null:' + field, nulls[field] == expected.get('nullCounts', {}).get(field, 0),
                      expected=expected.get('nullCounts', {}).get(field, 0), actual=nulls[field])
            sentinel_expectations = expected.get('sentinelMinus999999Counts', {})
            if not set(sentinel_expectations) <= set(numeric):
                raise ValueError('Manifest sentinel field is not numeric')
            for field in numeric:
                check(table + ':sentinel:' + field, sentinels[field] == sentinel_expectations.get(field, 0),
                      expected=sentinel_expectations.get(field, 0), actual=sentinels[field])
            for index, sample in enumerate(prepared['files'][table]['samples']):
                raw = {field: typed_value(sample[field], schema[field]['type']) for field in header}
                key = {field: raw[field] for field in keys}
                actual_raw = select_row(query, table, header, key)
                sample_report = dict(index=index, key=key, rawFields=[], semanticFields=[])
                table_report['samples'].append(sample_report)
                for field in header:
                    actual = typed_value(actual_raw[field], schema[field]['type'], empty_is_null=False)
                    passed = equivalent(raw[field], actual)
                    sample_report['rawFields'].append(dict(field=field, expected=raw[field], actual=actual, status='PASS' if passed else 'BLOCKED'))
                raw_ok = all(item['status'] == 'PASS' for item in sample_report['rawFields'])
                check(table + ':sample-raw:' + str(index), raw_ok, key=key)
                oracle = semantic_values(raw) if table == TABLES[1] else (
                    {field + 'Clean': clean_value(raw[field]) for field in CLEAN_COLUMNS} if table == TABLES[2] else {})
                if oracle:
                    actual_view = select_row(query, 'v_' + table, list(oracle), key)
                    for field, value in oracle.items():
                        kind = (schema[field[:-5]]['type'] if field.endswith('Clean') else
                                schema['quantRatio']['type'] if field == 'quanRatio' else 'DOUBLE')
                        actual = typed_value(actual_view[field], kind, empty_is_null=False)
                        passed = equivalent(value, actual)
                        sample_report['semanticFields'].append(dict(field=field, expected=value, actual=actual, status='PASS' if passed else 'BLOCKED'))
                    check(table + ':sample-semantic:' + str(index), all(item['status'] == 'PASS' for item in sample_report['semanticFields']), key=key)
            if table == TABLES[2]:
                clean_aggregates = []
                for field in CLEAN_COLUMNS:
                    raw_name, clean_name = identifier(field), identifier(field + 'Clean')
                    clean_aggregates += ['COALESCE(SUM(CASE WHEN ' + clean_name + ' IS NULL THEN 1 ELSE 0 END),0)',
                        'COALESCE(SUM(CASE WHEN ' + raw_name + '=-999999 AND ' + clean_name + ' IS NOT NULL THEN 1 ELSE 0 END),0)',
                        'COALESCE(SUM(CASE WHEN ' + raw_name + ' IS NOT NULL AND ' + raw_name + '<>-999999 AND (' + clean_name
                        + ' IS NULL OR ' + clean_name + '<>' + raw_name + ') THEN 1 ELSE 0 END),0)']
                summed_clean = [0] * (3 * len(CLEAN_COLUMNS))
                table_report['cleanAggregationShards'] = []
                for shard in shards:
                    observed_clean = query.query('SELECT ' + ','.join(clean_aggregates) + ' FROM ' + qualified('v_hsj_stock_hq_ext') + shard['where'])
                    if len(observed_clean) != 1 or len(observed_clean[0]) != len(summed_clean):
                        raise ValueError('Malformed Clean year-shard aggregate result')
                    shard_clean = list(map(int, observed_clean[0]))
                    if any(value < 0 for value in shard_clean):
                        raise ValueError('Negative Clean aggregate count')
                    summed_clean = [total + value for total, value in zip(summed_clean, shard_clean)]
                    table_report['cleanAggregationShards'].append(dict(year=shard['year'], values=shard_clean))
                table_report['cleanChecks'] = []
                for index, field in enumerate(CLEAN_COLUMNS):
                    clean_nulls, sentinel_leaks, normal_changes = summed_clean[3 * index:3 * index + 3]
                    expected_clean_nulls = nulls[field] + sentinels[field]
                    passed = clean_nulls == expected_clean_nulls and sentinel_leaks == normal_changes == 0
                    detail = dict(field=field + 'Clean', expectedNulls=expected_clean_nulls, actualNulls=clean_nulls,
                                  sentinelLeaks=sentinel_leaks, normalValueChanges=normal_changes)
                    table_report['cleanChecks'].append(detail)
                    check(table + ':global-clean:' + field, passed, **detail)
        registry_after = query.query(registry_sql)
        report['snapshotRegistryAfter'] = registry_after
        check('official-snapshot-registry-unchanged', registry_before == registry_after)
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
        check('complete-verification', False)
    report['passed'] = sum(check['status'] == 'PASS' for check in report['checks'])
    report['total'] = len(report['checks'])
    report['status'] = 'PASS' if len(report['tables']) == len(TABLES) and report['total'] > 0 and report['passed'] == report['total'] else 'BLOCKED'
    report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
    return report


def markdown(report):
    lines = ['# 专用 Doris 恢复核验', '', '**状态：' + report['status'] + '**', '',
             '这是项目内部恢复证据；不登记官方 VALIDATED。关联孤儿检查另由 validate_project_sources.py 执行。', '',
             '| 表 | 行数 | 日期范围 | 重复键组 | 空关联键 | 样本 |',
             '|---|---:|---|---:|---:|---:|']
    for table, item in report.get('tables', {}).items():
        dates = '～'.join(item['dateRange']) if item.get('dateRange') else '—'
        lines.append(f'| {table} | {item["rows"]:,} | {dates} | {item["duplicateKeyGroups"]} | {item["nullKeys"]} | {len(item["samples"])} |')
    lines += ['', f'检查通过：{report.get("passed", 0)}/{report.get("total", 0)}。', '',
              '完整 JSON 保存所有字段的空值/哨兵计数、逐样本 RAW/公式核对及 SELECT 耗时。', '']
    failures = [item for item in report.get('checks', []) if item['status'] != 'PASS']
    if failures:
        lines += ['## 未通过项', ''] + ['- ' + item['name'] for item in failures] + ['']
    if 'error' in report:
        lines += ['错误：' + report['error']['type'] + '：' + report['error']['message'].replace('\n', ' '), '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-dir', type=Path, default=Path('D:/DorisProjectRuntime/normalized'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json')
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = dict(formatVersion='recovered-snapshot-verification-v1', status='BLOCKED',
                  purpose='PROJECT_INTERNAL_RECOVERY_NOT_OFFICIAL_ACCEPTANCE', officialRegistrationAction='NONE_READ_ONLY',
                  distribution=args.distribution, passed=0, total=0, checks=[], tables={})
    try:
        schemas = ddl_schema()
        manifest, prepared, integrity = validate_prepared(args.prepared_dir, args.manifest, schemas)
        client = WslDoris(args.distribution, 'dsl-doris-official')
        report = verify(client, manifest, prepared, schemas, integrity)
        report.update(distribution=args.distribution, ports=dict(query=client.query_port, feHttp=client.fe_http_port, beHttp=client.be_http_port))
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
        report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
    report['elapsedMs'] = (time.perf_counter() - started) * 1000
    (args.output_dir / 'recovered-snapshot-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output_dir / 'recovered-snapshot-verification.md').write_text(markdown(report), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('status', 'passed', 'total')}, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
