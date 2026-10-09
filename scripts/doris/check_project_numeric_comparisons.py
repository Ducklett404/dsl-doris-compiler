"""Isolated native regressions for exact normalized price comparisons.

Expected sets are calculated from original integers with Decimal, never from
generated SQL or semantic views. Historical failures remain separate evidence.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
import secrets

from check_project_combinations import compiled_paths
from validate_project_sources import ROOT, WslDoris, digest
from run_correctness import bind_sql, sql_literal


def vectors():
    # Equal, adjacent, signed, beyond DOUBLE's integer precision, NULL and zero.
    return [
        ('equal-below-one', 9999, 100, 9999),
        ('equal-one', 10000, 100, 10000),
        ('equal-above-one', 10001, 100, 10001),
        ('below', 9998, 100, 9999),
        ('above', 10000, 100, 9999),
        ('negative-equal', -9999, 100, -9999),
        ('large-equal', 9007199254740993, 100, 9007199254740993),
        ('large-below', 9007199254740992, 100, 9007199254740993),
        ('large-above', 9007199254740994, 100, 9007199254740993),
        ('huge-volume-equal', 92233720368547700, 9223372036854770000, 1),
        ('huge-volume-below', 92233720368547699, 9223372036854770000, 1),
        ('huge-volume-above', 92233720368547701, 9223372036854770000, 1),
        ('tiny-positive', 1, 9223372036854775807, 0),
        ('null-turnover', None, 100, 9999),
        ('null-volume', 9999, None, 9999),
        ('zero-volume', 9999, 0, 9999),
        ('null-close', 9999, 100, None),
    ]


def expected(operator):
    result = []
    with localcontext() as context:
        context.prec = 80
        for index, (_, amount, volume, close) in enumerate(vectors()):
            if amount is None or volume in (None, 0) or close is None:
                continue
            a, b = Decimal(amount) / 100 / volume, Decimal(close) / 10000
            matches = {'=': a == b, '!=': a != b, '>': a > b,
                       '>=': a >= b, '<': a < b, '<=': a <= b}
            if matches[operator]:
                result.append(['1', f'{index + 1:06}'])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='java')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a fresh evidence file')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    client = WslDoris(args.distribution, 'dsl-doris-official')
    database = 'dsl_numeric_' + secrets.token_hex(6)
    registry = client.query('SELECT * FROM newzl.data_snapshot_registry')
    report = dict(purpose='SYNTHETIC_EXACT_COMPARISON_REGRESSION',
                  officialAcceptanceEligible=False, fixtureDatabase=database,
                  startedAtUtc=datetime.now(timezone.utc).isoformat(),
                  jarSha256=digest(ROOT / 'target/dsl-doris-compiler.jar'),
                  viewSha256=digest(ROOT / 'data/doris/ddl/002_semantic_view.sql'),
                  vectors=vectors(), checks=[])
    created = False
    try:
        client.query('CREATE DATABASE ' + database)
        created = True
        client.query((ROOT / 'data/doris/ddl/001_rebuild_tables.sql').read_text(encoding='utf-8')
                     .replace('newzl', database).replace('BUCKETS 16', 'BUCKETS 1'))
        client.query((ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8')
                     .replace('USE newzl;', 'USE ' + database + ';'))
        rows = [(1, f'{i + 1:06}', '2026-04-14', amount, volume, close)
                for i, (_, amount, volume, close) in enumerate(vectors())]
        client.query('INSERT INTO ' + database + '.hsj_stock_hq_basic'
                     '(mktcode,tgtcode,bizdate,turnover,volume,closePx) VALUES ' +
                     ','.join('(' + ','.join(sql_literal(v) for v in r) + ')' for r in rows))
        report['projection'] = client.query('SELECT tgtcode,avgPx,closePrice,'
            'CAST(avgPx AS DECIMAL(38,20)),CAST(closePrice AS DECIMAL(38,20)) FROM ' +
            database + '.v_hsj_stock_hq_basic ORDER BY tgtcode')
        report['types'] = [r for r in client.query('DESC ' + database + '.v_hsj_stock_hq_basic')
                           if r[0] in ('avgPx', 'closePrice')]
        # Portable emulation's signed ROUND_DOWN must be proven on native Doris,
        # not inferred from Python Decimal or positive-only division evidence.
        rounding_probes = [(1, 6, '0.001666666666666666666'),
                           (-1, 6, '-0.001666666666666666666'),
                           (1, -6, '-0.001666666666666666666')]
        report['nativeDecimalRounding'] = []
        for amount, volume, hand_value in rounding_probes:
            sql = ('SELECT CAST(CAST(CAST(' + str(amount) + ' AS DECIMAL(24,2))'
                   ' / 100 AS DECIMAL(36,19)) / CAST(' + str(volume) +
                   ' AS DECIMAL(20,0)) AS DECIMAL(38,21))')
            actual = client.query(sql)[0][0]
            ok = Decimal(actual) == Decimal(hand_value)
            report['nativeDecimalRounding'].append(dict(rawTurnover=amount, rawVolume=volume,
                expected=hand_value, actual=actual, status='PASS' if ok else 'FAIL'))
            if not ok:
                raise AssertionError('Native signed decimal rounding differs from hand definition')
        operators = ['=', '!=', '>', '>=', '<', '<=']
        suite = [dict(dsl="indicator('', '', '均价', '2026-04-14', '', '', '') " + op +
                           " indicator('', '', '收盘价', '2026-04-14', '', '', '')")
                 for op in operators]
        for operator, paths in zip(operators, compiled_paths(suite, args.java)):
            for mode, artifact in paths.items():
                sql = bind_sql(artifact['sql'], artifact['bindings']).replace('newzl.', database + '.')
                actual = [list(r) for r in client.query(sql)]
                reference = expected(operator)
                report['checks'].append(dict(operator=operator, mode=mode,
                    status='PASS' if actual == reference else 'FAIL',
                    actual=actual, expected=reference, sql=artifact['sql'],
                    bindings=artifact['bindings']))
                if operator == '>=' and mode == 'project':
                    report['explain'] = client.query('EXPLAIN VERBOSE ' + sql)
        # A NULL average must not remove a security selected by the RSI branch.
        # Last five deltas: +2,-1,+2,-3,+0.0001; RSI is strictly above 50.
        closes = [20000, 40000, 10000, 30000, 20000, 40000, 10000, 10001]
        history = [(1, 'W00001', '2026-04-' + f'{i + 7:02}', close)
                   for i, close in enumerate(closes)]
        client.query('INSERT INTO ' + database + '.hsj_stock_hq_basic'
            '(mktcode,tgtcode,bizdate,closePx) VALUES ' +
            ','.join('(' + ','.join(sql_literal(v) for v in r) + ')' for r in history))
        rsi_dsl = "((indicator('', '', '均价', '2026-04-14', '', '', '') > 0) and " + \
            "(indicator('', '', '3日均线', '2026-04-14', '', '', '') > 1)) or " + \
            "(indicator('', '', 'RSI(5)', '2026-04-14', '', '', '') > 50)"
        with localcontext() as context:
            context.prec = 80
            rsi_expected = Decimal(100) - Decimal(100) / (1 + Decimal('4.0001') / 4)
        report['rsiHandExpected'] = str(rsi_expected)
        for mode, artifact in compiled_paths([dict(dsl=rsi_dsl)], args.java)[0].items():
            sql = bind_sql(artifact['sql'], artifact['bindings']).replace('newzl.', database + '.')
            actual = [list(r) for r in client.query(sql)]
            reference = [['1', 'W00001']]
            prefix = sql.rsplit('SELECT mktcode,tgtcode\nFROM current_rows', 1)[0]
            report.setdefault('rsiProjection', {})[mode] = client.query(prefix +
                "SELECT tgtcode,f1,f2,f3 FROM current_rows WHERE tgtcode='W00001'")
            report['checks'].append(dict(operator='RSI_OR_NULL', mode=mode,
                status='PASS' if actual == reference else 'FAIL', actual=actual, expected=reference,
                sql=artifact['sql'], bindings=artifact['bindings']))
        if client.query('SELECT * FROM newzl.data_snapshot_registry') != registry:
            raise AssertionError('Formal snapshot registry changed')
    except Exception as error:
        report['fatalError'] = str(error)
        raise
    finally:
        if created:
            client.query('DROP DATABASE ' + database)
            if client.query("SHOW DATABASES LIKE '" + database + "'"):
                raise AssertionError('Fixture cleanup failed')
            report['fixtureCleanup'] = 'DONE'
        report.update(completedAtUtc=datetime.now(timezone.utc).isoformat(),
            passed=sum(c['status'] == 'PASS' for c in report['checks']), total=len(report['checks']))
        report['status'] = 'PASS' if 'fatalError' not in report and report['total'] == 14 and report['passed'] == 14 else 'FAIL'
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'passed', 'total', 'fixtureCleanup')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
