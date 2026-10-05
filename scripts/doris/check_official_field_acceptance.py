"""Independent raw-value and result-set diagnostics; never registers a snapshot.

The oracle below spells out the project's frozen field definitions directly. It
does not read formulas from the registry, semantic view, or generated SQL. These
definitions are project assumptions, not a substitute for an official dictionary.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris, bind_sql, compile_case, sql_literal

D = Decimal
# name, Doris semantic-view projection, fixed screening threshold
FIELDS = [
    ('最新价', 'b.lastPrice', '10'), ('昨收价', 'b.preClosePrice', '10'),
    ('开盘价', 'b.openPrice', '10'), ('最高价', 'b.highPrice', '10'),
    ('最低价', 'b.lowPrice', '10'), ('收盘价', 'b.closePrice', '10'),
    ('成交量', 'b.volume', '1000000'), ('成交额', 'b.turnoverAmount', '10000000'),
    ('量比', 'b.quantityRatio', '1'), ('换手率', 'b.turnoverRatio', '2.5'),
    ('真实换手率', 'b.trueTurnoverRatio', '2.5'), ('总市值', 'b.marketValue', '10000000000'),
    ('流通市值', 'b.listedMarketValue', '5000000000'), ('涨跌幅', 'b.risePct', '2.5'),
    ('均价', 'b.avgPx', '10'), ('前复权收盘价', 'b.closeQfq', '10'),
    ('后复权收盘价', 'b.closeHfq', '10'), ('主力净流入', 'NULLIF(e.ZJLXMainNetTur,-999999)', '0'),
    ('振幅', 'CAST(b.amplitude AS DOUBLE)/10000.0', '2.5'),
]
RAW_COLUMNS = ('lastPx', 'preClosePx', 'openPx', 'highPx', 'lowPx', 'closePx',
               'volume', 'turnover', 'quantRatio', 'turnRatio', 'trueTurnRatio',
               'totalShare', 'listedShare', 'qfqMulti', 'qfqAdd', 'hfqMulti', 'hfqAdd', 'amplitude')
MARKETS = {'深': 0, '沪': 1, '京': 103}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def raw_values(raw):
    values = {k: None if v is None else D(str(v)) for k, v in raw.items()}
    def scale(name, divisor):
        v = values[name]
        return None if v is None else v / D(divisor)
    def product(a, b):
        return None if a is None or b is None else a * b
    def adjusted(multi, add):
        price = product(scale('closePx', 10000), values[multi])
        return None if price is None or values[add] is None else price + values[add]
    previous = values['preClosePx']
    last = values['lastPx']
    volume = values['volume']
    turnover = scale('turnover', 100)
    net = values['net']
    return [scale('lastPx', 10000), scale('preClosePx', 10000), scale('openPx', 10000),
            scale('highPx', 10000), scale('lowPx', 10000), scale('closePx', 10000),
            volume, turnover, scale('quantRatio', 10000), scale('turnRatio', 10000),
            scale('trueTurnRatio', 10000), product(scale('lastPx', 10000), values['totalShare']),
            product(scale('lastPx', 10000), values['listedShare']),
            None if previous in (None, D(0)) or last is None else (last - previous) * 100 / previous,
            None if volume in (None, D(0)) or turnover is None else turnover / volume,
            adjusted('qfqMulti', 'qfqAdd'), adjusted('hfqMulti', 'hfqAdd'),
            None if net == D(-999999) else net, scale('amplitude', 10000)]


def compare_values(expected, rows):
    actual = {}
    for market, code, *values in rows:
        key = (int(market), code)
        if key in actual:
            raise ValueError('Duplicate result key: ' + str(key))
        if len(values) != len(FIELDS):
            raise ValueError('Wrong projected field count')
        actual[key] = [None if v == 'NULL' else D(v) for v in values]
    if set(actual) != set(expected):
        raise ValueError('Numeric comparison key coverage mismatch')
    errors = []
    nulls = nonnull = 0
    max_error = D(0)
    for key, values in expected.items():
        for index, e in enumerate(values):
            a = actual[key][index]
            nulls += e is None
            nonnull += e is not None
            if e is None:
                correct = a is None
            else:
                correct = a is not None and a.is_finite() and abs(a - e) <= D('1e-10') * max(D(1), abs(e))
                if a is not None and a.is_finite():
                    max_error = max(max_error, abs(a - e))
            if not correct and len(errors) < 20:
                errors.append({'key': key, 'field': FIELDS[index][0], 'expected': str(e), 'actual': str(a)})
    return {'status': 'FAIL' if errors else 'PASS', 'rows': len(expected),
            'valuesChecked': nulls + nonnull, 'nullValuesChecked': nulls,
            'nonNullValuesChecked': nonnull, 'maxAbsoluteError': str(max_error), 'mismatches': errors}


def indicator(metric, date, market='', count=''):
    return f"indicator('{market}', '', '{metric}', '{date}', '', '', '{count}')"


def function_cases(histories, date):
    """Independent Python loops for the frozen 5/20-observation semantics."""
    output = []
    live = {key: h for key, h in histories.items() if h[-1][0] == date}
    def add(name, dsl, predicate, ordered=False):
        keys = sorted(key for key, h in live.items() if predicate(h))
        output.append((f'{name}-{date}', dsl, keys, ordered))
    def pair(h, above):
        if len(h) < 2 or any(v is None for row in h[-2:] for v in row[1:3]):
            return False
        before, now = h[-2:]
        return (now[1] > now[2] and before[1] <= before[2]) if above else (now[1] < now[2] and before[1] >= before[2])
    for name, above in [('cross_above', True), ('cross_down', False), ('reset', True), ('golden_cross', True)]:
        add(name, f"{name}('京', '', '收盘价', '开盘价', '{date}', '', '') = True", lambda h, a=above: pair(h, a))
    def together(h):
        close, opening = h[-1][1:3]
        return close is not None and opening is not None and max(abs(close), abs(opening)) > 0 and abs(close - opening) / max(abs(close), abs(opening)) <= D('.01')
    add('close_together', f"close_together('京', '', '收盘价', '开盘价', '{date}', '', '') = True", together)
    def complete(h, column):
        return len(h) >= 5 and all(r[column] is not None for r in h[-5:])
    for name, metric, column, reducer in [('record_high', '最高价', 3, max), ('record_low', '最低价', 4, min)]:
        add(name, f"{name}('京', '', '{metric}', '5日', '{date}', '', '', '') = True",
            lambda h, c=column, r=reducer: complete(h, c) and h[-1][c] == r(row[c] for row in h[-5:]))
    def position(h):
        if not complete(h, 1):
            return None
        values = [r[1] for r in h[-5:]]
        low, high = min(values), max(values)
        if low == high:
            return None
        return '低' if values[-1] <= low + (high - low) / 3 else ('高' if values[-1] >= low + 2 * (high - low) / 3 else '中')
    for label in ['低', '中', '高']:
        add('position-' + label, f"position('京', '', '收盘价', '5日', '{date}', '', '', '') = '{label}'", lambda h, v=label: position(h) == v)
    add('CONS-ge', indicator('收盘价', date, '京', 'CONS>=3日') + ' > 10',
        lambda h: len(h) >= 3 and all(r[1] is not None and r[1] > 10 for r in h[-3:]))
    add('CONS-eq', indicator('收盘价', date, '京', 'CONS=2日') + ' > 10',
        lambda h: len(h) >= 3 and all(r[1] is not None and r[1] > 10 for r in h[-2:]) and (h[-3][1] is None or h[-3][1] <= 10))
    for operator in ['>=', '=']:
        add('EXIST-' + ('ge' if operator == '>=' else 'eq'), indicator('成交量', date, '京', f'EXIST{operator}3日') + ' > 1000000',
            lambda h, op=operator: len(h) >= 20 and ((sum(r[5] is not None and r[5] > 1000000 for r in h[-20:]) >= 3) if op == '>=' else (sum(r[5] is not None and r[5] > 1000000 for r in h[-20:]) == 3)))
    current = sorted([(key, h[-1][1]) for key, h in live.items() if h[-1][1] is not None], key=lambda v: (-v[1], v[0]))
    for method in ['row_number', 'rank', 'dense_rank']:
        keys = []
        previous = None
        dense = rank = 0
        for index, (key, value) in enumerate(current, 1):
            if value != previous:
                dense += 1
                rank = index
                previous = value
            score = {'row_number': index, 'rank': rank, 'dense_rank': dense}[method]
            if score <= 20:
                keys.append(key)
        output.append((f'rank-{method}-{date}', f"rank('京', '', '收盘价', 'desc:{method}', '{date}', '', '', '') <= 20", keys, True))
    return output


def self_test():
    raw = {name: 10000 for name in RAW_COLUMNS}
    raw.update(volume=0, preClosePx=0, net=-999999, qfqMulti=2, qfqAdd=3)
    values = raw_values(raw)
    assert values[13] is None and values[14] is None and values[17] is None
    assert values[15] == 5 and values[0] == 1 and values[18] == 1
    expected = {(0, '000001'): values}
    row = ['0', '000001'] + ['NULL' if value is None else str(value) for value in values]
    assert compare_values(expected, [row])['status'] == 'PASS'
    changed = row.copy(); changed[2] = '10000'
    assert compare_values(expected, [changed])['status'] == 'FAIL'
    changed = row.copy(); changed[19] = '-999999'
    assert compare_values(expected, [changed])['status'] == 'FAIL'
    for rows in [[], [row, row]]:
        try:
            compare_values(expected, rows)
        except ValueError:
            pass
        else:
            raise AssertionError('Missing or duplicate keys must be rejected')
    histories = {(103, '920001'): [('x', D(1), D(2), D(2), D(1), 0),
                                  ('y', D(3), D(2), D(3), D(1), 100),
                                  ('z', D(4), D(2), D(4), D(1), 100)]}
    cases = {name: keys for name, dsl, keys, ordered in function_cases(histories, 'y')}
    assert all(not keys for keys in cases.values())  # no current observation
    cases = {name: keys for name, dsl, keys, ordered in function_cases(histories, 'z')}
    assert not cases['cross_above-z'] and not cases['record_high-z']  # no crossing / incomplete window
    print('ORACLE_SELFTEST_PASS: scale, NULL, sentinel, mismatch, missing/duplicate keys, temporal boundaries')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path)
    parser.add_argument('--audit-report', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--java', default='D:/Java/jdk-21/bin/java.exe')
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.database or not args.audit_report or not args.output:
        parser.error('--database, --audit-report and --output are required')
    audit = json.loads(args.audit_report.read_text(encoding='utf-8'))
    snapshot = audit['snapshotId']
    manifest_path = ROOT / 'data/doris/snapshots' / snapshot / 'manifest.json'
    manifest_hash = digest(manifest_path)
    jar = ROOT / 'target/dsl-doris-compiler.jar'
    report = {'purpose': 'INDEPENDENT_OFFICIAL_DATA_DIAGNOSTIC', 'acceptanceEligible': False,
              'definitionAuthority': 'PROJECT_SCOPE_ONLY_OFFICIAL_DICTIONARY_PENDING',
              'startedAtUtc': utc(), 'snapshotId': snapshot, 'manifestSha256': manifest_hash,
              'jarSha256': digest(jar), 'oracleSha256': digest(Path(__file__)),
              'sourceAuditSha256': digest(args.audit_report), 'sourceAuditStatus': audit['status'],
              'relativeTolerance': '1e-10', 'dates': [], 'queries': []}
    con = duckdb.connect(str(args.database), read_only=True)
    client = WslDoris(args.distribution, 'dsl-doris-official')
    dates = ['2006-01-04', '2018-08-20', '2026-04-10', '2026-04-13', '2026-04-14']
    try:
        if con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone() != (snapshot, manifest_hash, audit['status']):
            raise ValueError('Independent audit lock mismatch')
        registry = json.loads((ROOT / 'src/main/resources/stock-slot-registry-v1.json').read_text(encoding='utf-8'))
        if {item['name'] for item in registry['indicators']} != {item[0] for item in FIELDS}:
            raise ValueError('Manual oracle does not cover exactly the registry field inventory')
        if client.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry') != [('0',)]:
            raise ValueError('Expected unregistered diagnostic snapshot')
        query_cases = []
        for date in dates:
            rows = con.execute('SELECT b.mktcode,b.tgtcode,' + ','.join('b.' + c for c in RAW_COLUMNS) + ',e.ZJLXMainNetTur net FROM newzl.hsj_stock_hq_basic b LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) WHERE b.bizdate=CAST(? AS DATE)', [date]).fetchall()
            expected = {(int(m), code): raw_values(dict(zip((*RAW_COLUMNS, 'net'), values))) for m, code, *values in rows}
            if len(rows) != len(expected):
                raise ValueError('Duplicate raw source keys')
            sql = 'SELECT b.mktcode,b.tgtcode,' + ','.join(c[1] for c in FIELDS) + ' FROM newzl.v_hsj_stock_hq_basic b LEFT JOIN newzl.v_hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) WHERE b.bizdate=' + sql_literal(date)
            comparison = compare_values(expected, client.query(sql))
            comparison.update(date=date, rawOracleFieldCoverage=len(FIELDS),
                perField=[{'field': name, 'nulls': sum(v[i] is None for v in expected.values()),
                           'nonNull': sum(v[i] is not None for v in expected.values())} for i, (name, _, _) in enumerate(FIELDS)])
            report['dates'].append(comparison)
            print(f"[raw-values {date}] {comparison['status']}: {comparison['valuesChecked']} values", flush=True)
            for market, code in [('', None)] + (list(MARKETS.items()) if date == dates[-1] else []):
                for index, (metric, _, threshold) in enumerate(FIELDS):
                    keys = sorted(k for k, v in expected.items() if (code is None or k[0] == code) and v[index] is not None and v[index] > D(threshold))
                    query_cases.append((f'field-{metric}-{date}-{market or "all"}', indicator(metric, date, market) + ' > ' + threshold, keys, True))
            keys = sorted(k for k, v in expected.items() if v[13] is not None and v[13] > D('2.5'))
            query_cases.append((f'alias-涨幅-{date}', indicator('涨幅', date) + ' > 2.5', keys, True))
            for metric in ['换手率', '涨跌幅', '振幅']:
                index = next(i for i, f in enumerate(FIELDS) if f[0] == metric)
                keys = sorted(k for k, v in expected.items() if v[index] is not None and v[index] > D('2.5'))
                query_cases.append((f'percent-{metric}-{date}', indicator(metric, date) + ' > 2.5%', keys, True))
            target = expected.get((0, '000001'), [None] * len(FIELDS))[5]
            keys = sorted(k for k, v in expected.items() if k[0] == 0 and target is not None and v[5] is not None and v[5] > target)
            query_cases.append((f'queryData-leading-zero-{date}', indicator('收盘价', date, '深') + f" > queryData('深', '000001', '收盘价', '{date}', '')", keys, True))
            query_cases.append((f'queryData-missing-{date}', indicator('收盘价', date, '深') + f" > queryData('深', '000000', '收盘价', '{date}', '')", [], True))
            if date in dates[-3:]:
                rows = con.execute('SELECT mktcode,tgtcode,bizdate,closePx,openPx,highPx,lowPx,volume FROM newzl.hsj_stock_hq_basic WHERE mktcode=103 AND bizdate<=CAST(? AS DATE) QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=20 ORDER BY mktcode,tgtcode,bizdate', [date]).fetchall()
                histories = defaultdict(list)
                for m, code, day, *values in rows:
                    histories[(int(m), code)].append((str(day), *(None if v is None else D(v) / (10000 if i < 4 else 1) for i, v in enumerate(values))))
                query_cases.extend(function_cases(histories, date))
        with tempfile.TemporaryDirectory(prefix='official-field-oracle-') as directory:
            for index, (name, dsl, expected, ordered) in enumerate(query_cases, 1):
                start = time.monotonic()
                row = {'id': name, 'dsl': dsl, 'expectedRows': len(expected), 'expectedRowsSha256': hashlib.sha256(json.dumps(expected, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()}
                try:
                    artifact = compile_case(args.java, jar, dsl, Path(directory) / 'case.dsl', snapshot)
                    actual = [(int(m), code) for m, code in client.query(bind_sql(artifact['sql'], artifact['bindings']))]
                    equal = actual == expected if ordered else set(actual) == set(expected)
                    row.update(status='PASS' if equal else 'FAIL', actualRows=len(actual), orderedCompared=ordered,
                               onlyActual=sorted(set(actual) - set(expected))[:20], onlyExpected=sorted(set(expected) - set(actual))[:20],
                               actualRowsSha256=hashlib.sha256(json.dumps(actual, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
                               sql=artifact['sql'], bindings=artifact['bindings'])
                except Exception as error:
                    row.update(status='ERROR', error=str(error))
                row['elapsedSeconds'] = round(time.monotonic() - start, 3)
                report['queries'].append(row)
                if row['status'] != 'PASS' or index % 20 == 0:
                    print(f"[{index}/{len(query_cases)}] {name}: {row['status']}", flush=True)
        report['registeredSnapshotsAfter'] = int(client.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry')[0][0])
        if digest(jar) != report['jarSha256'] or digest(manifest_path) != manifest_hash:
            raise ValueError('Source or compiler changed during acceptance diagnostics')
    except Exception as error:
        report['fatalError'] = str(error)
        raise
    finally:
        con.close()
        report.update(completedAtUtc=utc(), queryTotal=len(report['queries']),
                      queryPassed=sum(r['status'] == 'PASS' for r in report['queries']),
                      totalValuesChecked=sum(r['valuesChecked'] for r in report['dates']),
                      totalNullValuesChecked=sum(r['nullValuesChecked'] for r in report['dates']))
        report['status'] = 'PASS' if 'fatalError' not in report and len(report['dates']) == len(dates) and all(r['status'] == 'PASS' for r in report['dates']) and report['queryTotal'] > 0 and report['queryTotal'] == report['queryPassed'] and report.get('registeredSnapshotsAfter') == 0 else 'FAIL'
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['status', 'queryTotal', 'queryPassed', 'totalValuesChecked', 'totalNullValuesChecked']}, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
