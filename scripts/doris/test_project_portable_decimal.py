"""Portable decimal adapter contracts, using only in-memory DuckDB fixtures."""
import ast
from decimal import Decimal, getcontext, localcontext
from pathlib import Path
import unittest
from unittest.mock import Mock

import duckdb

import project_portable_decimal as adapter


ROOT = Path(__file__).resolve().parents[2]
DDL = (ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8')
BIGINT_MAX = (1 << 63) - 1


def rsi_expression(n=5):
    frame = 'CURRENT ROW' if n == 1 else f'{n - 1} PRECEDING'
    window = f'(PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN {frame} AND CURRENT ROW)'
    return (f'CASE WHEN COUNT(price_delta) OVER {window} = {n} '
        f'AND (SUM(GREATEST(-price_delta,0)) OVER {window}) > 0 '
        f'THEN CAST((SUM(GREATEST(price_delta,0)) OVER {window}) * 100 AS DECIMAL(30,8)) '
        f'/ NULLIF(CAST(SUM(ABS(price_delta)) OVER {window} AS DECIMAL(24,4)),0) ELSE NULL END')


class PortableDecimalTest(unittest.TestCase):
    def fixture(self, price_type='BIGINT'):
        con = duckdb.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('CREATE SCHEMA newzl')
        columns = ['mktcode INTEGER', 'tgtcode VARCHAR', 'bizdate DATE']
        columns += [f'{name} {price_type}' for name in adapter.PRICE_COLUMNS]
        columns += [f'{name} BIGINT' for name in ['turnover', 'volume', 'quantRatio', 'turnRatio',
                    'trueTurnRatio', 'totalShare', 'listedShare', 'amplitude']]
        columns += [f'{name} DOUBLE' for name in ['qfqMulti', 'qfqAdd', 'hfqMulti', 'hfqAdd']]
        con.execute('CREATE TABLE newzl.hsj_stock_hq_basic(' + ','.join(columns) + ')')
        con.execute('CREATE TABLE newzl.hsj_stock_hq_ext(mktcode INTEGER,tgtcode VARCHAR,bizdate DATE,' +
                    ','.join(name + ' BIGINT' for name in ['ZJLXMainNetTur', 'ZJLXMainNetTurInDays',
                        'ZJLXMainNetTurOutDays', 'ZJLXMainNetTurInSeries', 'ZJLXMainNetTurOutSeries',
                        'pxMkTopDays', 'mainTurMkTopDays']) + ')')
        return con

    def insert(self, con, code, turnover, volume, raw_price):
        columns = ['tgtcode', 'turnover', 'volume', *adapter.PRICE_COLUMNS]
        con.execute('INSERT INTO newzl.hsj_stock_hq_basic(' + ','.join(columns) + ') VALUES(' +
                    ','.join('?' for _ in columns) + ')', [code, turnover, volume, *([raw_price] * 6)])

    def test_hand_calculated_cents_and_exact_average_close_comparison(self):
        con = self.fixture()
        self.insert(con, 'equal', 9999, 100, 9999)
        self.insert(con, 'cents', 9999, 1, 999900)
        evidence = adapter.install_semantic_views(con, DDL)
        rows = con.execute('SELECT tgtcode,avgPx,closePrice,avgPx=closePrice FROM newzl.v_hsj_stock_hq_basic ORDER BY tgtcode').fetchall()
        self.assertEqual(rows, [('cents', Decimal('99.99'), Decimal('99.99'), True),
                                ('equal', Decimal('0.9999'), Decimal('0.9999'), True)])
        self.assertEqual(evidence['purpose'], 'PORTABLE_DORIS_DECIMAL_EMULATION')
        self.assertTrue(evidence['notNativeDorisProof'])
        self.assertFalse(evidence['officialAcceptanceEligible'])
        self.assertEqual(evidence['positionCompanions'], 'UNCHANGED')
        types = con.execute('SELECT typeof(avgPx),' + ','.join('typeof(' + alias + ')' for alias in adapter.PRICE_COLUMNS.values()) +
                            ' FROM newzl.v_hsj_stock_hq_basic LIMIT 1').fetchone()
        self.assertEqual(types, ('DECIMAL(38,21)', *(('DECIMAL(19,4)',) * 6)))

    def test_adjacent_integers_above_double_precision_remain_distinct(self):
        con = self.fixture()
        raw = 1 << 53
        self.insert(con, 'first', raw, 1, raw)
        self.insert(con, 'second', raw + 1, 1, raw + 1)
        adapter.install_semantic_views(con, DDL)
        self.assertEqual(con.execute('SELECT tgtcode,avgPx,closePrice FROM newzl.v_hsj_stock_hq_basic ORDER BY tgtcode').fetchall(), [
            ('first', Decimal('90071992547409.92'), Decimal('900719925474.0992')),
            ('second', Decimal('90071992547409.93'), Decimal('900719925474.0993'))])
        self.assertEqual(con.execute("SELECT a.avgPx < b.avgPx AND a.closePrice < b.closePrice FROM newzl.v_hsj_stock_hq_basic a CROSS JOIN newzl.v_hsj_stock_hq_basic b WHERE a.tgtcode='first' AND b.tgtcode='second'").fetchone(), (True,))

    def test_null_and_zero_volume_preserve_null_results(self):
        con = self.fixture()
        for code, turnover, volume, price in [('null-turnover', None, 1, None),
                ('null-volume', 9999, None, 9999), ('zero-volume', 9999, 0, 9999), ('zero-turnover', 0, 1, 0)]:
            self.insert(con, code, turnover, volume, price)
        adapter.install_semantic_views(con, DDL)
        rows = dict(con.execute('SELECT tgtcode,avgPx FROM newzl.v_hsj_stock_hq_basic').fetchall())
        self.assertEqual(rows, {'null-turnover': None, 'null-volume': None, 'zero-volume': None, 'zero-turnover': Decimal(0)})
        self.assertIsNone(con.execute("SELECT closePrice FROM newzl.v_hsj_stock_hq_basic WHERE tgtcode='null-turnover'").fetchone()[0])

    def test_tiny_values_and_signed_round_down_are_exact(self):
        con = self.fixture()
        for code, turnover, volume in [('tiny', 1, BIGINT_MAX), ('positive', 1, 6), ('negative', -1, 6)]:
            self.insert(con, code, turnover, volume, 0)
        adapter.install_semantic_views(con, DDL)
        rows = dict(con.execute('SELECT tgtcode,avgPx FROM newzl.v_hsj_stock_hq_basic').fetchall())
        self.assertEqual(rows, {'tiny': Decimal('0.000000000000000000001'),
            'positive': Decimal('0.001666666666666666666'), 'negative': Decimal('-0.001666666666666666666')})
        self.assertEqual(con.execute("SELECT avgPx > CAST(0 AS DECIMAL(38,21)) FROM newzl.v_hsj_stock_hq_basic WHERE tgtcode='tiny'").fetchone(), (True,))

    def test_full_signed_bigint_price_domain_and_local_context(self):
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(adapter._plain_price(BIGINT_MAX), Decimal('922337203685477.5807'))
            self.assertEqual(adapter._plain_price(-(1 << 63)), Decimal('-922337203685477.5808'))
            self.assertEqual(adapter._average_price(BIGINT_MAX, 1), Decimal('92233720368547758.07'))
            self.assertEqual(getcontext().prec, 6)

    def test_changed_or_unrecognized_ddl_is_rejected_before_any_database_call(self):
        changed = [DDL.replace('DECIMAL(38,21)', 'DECIMAL(38,20)'),
                   DDL.replace('DECIMAL(19,4)) AS closePrice', 'DECIMAL(19,3)) AS closePrice'),
                   DDL.replace('/ 100 AS DECIMAL(36,19)', '/ 10 AS DECIMAL(36,19)'),
                   DDL.replace('b.turnover AS DECIMAL(24,2)', 'b.closePx AS DECIMAL(24,2)'),
                   DDL + '\nDROP TABLE hsj_stock_hq_basic;',
                   DDL.replace('END AS avgPx,', 'END AS avgPxChanged,'),
                   DDL.replace('CAST(b.closePx AS DECIMAL(24,4)) / 10000 AS closePricePosition',
                               'CAST(b.closePx AS DECIMAL(24,4)) / 100 AS closePricePosition')]
        for ddl in changed:
            with self.subTest(ddl=ddl):
                con = Mock()
                with self.assertRaisesRegex(ValueError, 'Unrecognized semantic-view DDL shape'):
                    adapter.install_semantic_views(con, ddl)
                con.execute.assert_not_called()
                con.create_function.assert_not_called()

    def test_comments_case_whitespace_and_optional_use_are_recognized(self):
        con = self.fixture()
        self.insert(con, 'equal', 9999, 100, 9999)
        ddl = '-- portable formatting only\n' + DDL.replace('USE newzl;', '').lower().replace(' AS ', '  as  ')
        evidence = adapter.install_semantic_views(con, ddl)
        self.assertEqual(evidence['trustedDdlSha256'], adapter.TRUSTED_DDL_SHA256)
        self.assertEqual(con.execute('SELECT avgPx=closePrice FROM newzl.v_hsj_stock_hq_basic').fetchone(), (True,))

    def test_position_companion_expression_is_preserved(self):
        adapted, _ = adapter._adapt_ddl(DDL)
        original = 'ELSE CAST(b.turnover AS DECIMAL(30,10)) / 100 / CAST(b.volume AS DECIMAL(20,0)) END AS avgPxPosition'
        self.assertIn(' '.join(adapter._tokens(original)), adapted)

    def test_non_bigint_fixture_input_is_rejected(self):
        con = self.fixture(price_type='DOUBLE')
        with self.assertRaisesRegex(ValueError, 'Expected raw BIGINT fixture column'):
            adapter.install_semantic_views(con, DDL)
        self.assertEqual(con.execute("SELECT count(*) FROM information_schema.views WHERE table_schema='newzl'").fetchone(), (0,))

    def test_persistent_connection_is_refused_without_registering_functions(self):
        con = Mock()
        con.execute.return_value.fetchall.return_value = [(0, 'reference', 'DO_NOT_OPEN.duckdb')]
        with self.assertRaisesRegex(ValueError, 'in-memory fixture only'):
            adapter.install_semantic_views(con, DDL)
        con.create_function.assert_not_called()
        self.assertEqual(con.execute.call_count, 1)

    def test_rsi_exact_boundary_and_raw_integer_neighbors_on_in_memory_duckdb(self):
        con = self.fixture()
        evidence = adapter.install_semantic_views(con, DDL)
        con.execute('CREATE TABLE changes(mktcode INTEGER,tgtcode VARCHAR,bizdate DATE,price_delta DECIMAL(19,4))')
        histories = [('000903', [400, -700, 0, 200, 100]),
                     ('300135', [500, -1000, 400, 600, -500]),
                     ('below', [400, -700, 0, 200, 99]),
                     ('above', [400, -700, 0, 200, 101]),
                     ('only-gains', [100] * 5), ('flat', [0] * 5),
                     ('null-change', [400, -700, None, 200, 100]),
                     ('short', [400, -700, 200, 100])]
        rows = [(0, code, f'2026-04-{10 + i:02}',
                 None if change is None else Decimal(change) / 10000)
                for code, changes in histories for i, change in enumerate(changes)]
        con.executemany('INSERT INTO changes VALUES(?,?,?,?)', rows)
        sql = ('SELECT tgtcode,value,typeof(value),value>=? FROM (SELECT tgtcode,bizdate,' +
            rsi_expression() + ' AS value FROM changes) x WHERE bizdate=? ORDER BY tgtcode')
        transformed = adapter.adapt_compiler_sql(con, sql, evidence)
        self.assertEqual(sql.count('?'), transformed.count('?'))
        self.assertIn('value>=?', transformed)
        result = {row[0]: row[1:] for row in con.execute(transformed, [50, '2026-04-14']).fetchall()}
        self.assertEqual(result['000903'], (Decimal('50'), 'DECIMAL(38,12)', True))
        self.assertEqual(result['300135'], (Decimal('50'), 'DECIMAL(38,12)', True))
        self.assertEqual(result['below'], (Decimal('49.964260185847'), 'DECIMAL(38,12)', False))
        self.assertEqual(result['above'], (Decimal('50.035688793718'), 'DECIMAL(38,12)', True))
        for name in ('only-gains', 'flat', 'null-change'):
            self.assertEqual(result[name], (None, 'DECIMAL(38,12)', None))
        self.assertIsNone(con.execute(adapter.adapt_compiler_sql(con,
            'SELECT ' + rsi_expression() + " FROM changes WHERE tgtcode='short' ORDER BY bizdate DESC LIMIT 1")).fetchone()[0])
        self.assertEqual(evidence['rsiDivisionTransforms'], 1)
        self.assertEqual(evidence['rsiDivision']['precision'], 80)
        self.assertEqual(evidence['rsiDivision']['rounding'], 'ROUND_DOWN')
        self.assertTrue(evidence['notNativeDorisProof'])

    def test_rsi_typed_decimal_udf_truncates_toward_zero_with_local_precision(self):
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(adapter._rsi_ratio(Decimal('100'), Decimal('6')), Decimal('16.666666666666'))
            self.assertEqual(adapter._rsi_ratio(Decimal('-100'), Decimal('6')), Decimal('-16.666666666666'))
            self.assertEqual(adapter._rsi_ratio(Decimal('7'), Decimal('0.14')), Decimal('50'))
            self.assertIsNone(adapter._rsi_ratio(Decimal('0'), Decimal('0')))
            self.assertIsNone(adapter._rsi_ratio(None, Decimal('1')))
            self.assertIsNone(adapter._rsi_ratio(Decimal('1'), None))
            self.assertEqual(getcontext().prec, 6)
        for numerator, denominator in ((1.0, Decimal('1')), (Decimal('1'), 1.0),
                (Decimal('NaN'), Decimal('1')), (Decimal('1'), Decimal('Infinity')),
                (Decimal('1e22'), Decimal('1')), (Decimal('1'), Decimal('1e20')),
                (Decimal('0.000000001'), Decimal('1')), (Decimal('1'), Decimal('0.00001'))):
            with self.subTest(numerator=numerator, denominator=denominator), self.assertRaises(ValueError):
                adapter._rsi_ratio(numerator, denominator)

    def test_rsi_transform_requires_same_alias_frame_guards_and_reviewed_casts(self):
        con = self.fixture()
        adapter.install_semantic_views(con, DDL)
        original = 'SELECT ' + rsi_expression() + ' AS value FROM changes'
        for changed in (original.replace('ABS(price_delta)', 'ABS(other_delta)'),
                original.replace('DECIMAL(30,8)', 'DECIMAL(30,7)'),
                original.replace('DECIMAL(24,4)', 'DECIMAL(24,3)'),
                original.replace('NULLIF(CAST', 'COALESCE(CAST'),
                original.replace(')) > 0 THEN', ')) >= 0 THEN'),
                original.replace('COUNT(price_delta)', 'COUNT(other_delta)'),
                original.replace('price_delta', 'other_delta'),
                original.replace('price_delta', '`price_delta`'),
                original.replace('price_delta', 'COALESCE(price_delta,0)'),
                original.replace(' = 5 AND', ' = 4 AND'),
                original.replace('SUM(ABS(price_delta)) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 4 PRECEDING',
                    'SUM(ABS(price_delta)) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 3 PRECEDING'),
                'SELECT ' + rsi_expression(5001) + ' FROM changes'):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'RSI'):
                adapter.adapt_compiler_sql(con, changed)
        unrelated = 'SELECT CAST(SUM(other_delta) AS DECIMAL(30,8)) / 2 FROM changes'
        self.assertEqual(adapter.adapt_compiler_sql(con, unrelated), unrelated)
        self.assertIn(adapter.RSI_UDF, adapter.adapt_compiler_sql(con, 'SELECT ' + rsi_expression(1)))

    def test_rsi_transform_preserves_unmatched_sql_literals_comments_and_bindings(self):
        con = self.fixture()
        adapter.install_semantic_views(con, DDL)
        expression = rsi_expression()
        for unchanged in ('SELECT ? >= ? AND ? != ?', "SELECT '" + expression + "' AS text",
                'SELECT "' + expression + '" FROM changes', 'SELECT `' + expression + '` FROM changes',
                'SELECT 1 -- ' + expression, 'SELECT 1 /* ' + expression + ' */'):
            with self.subTest(unchanged=unchanged):
                self.assertEqual(adapter.adapt_compiler_sql(con, unchanged), unchanged)
        sql = 'SELECT ' + expression + ' AS first,' + expression + ' AS second FROM changes WHERE tgtcode=?'
        adapted = adapter.adapt_compiler_sql(con, sql)
        self.assertEqual(adapted.count(adapter.RSI_UDF), 2)
        self.assertEqual(adapted.count('COUNT(price_delta)'), 2)
        self.assertEqual(adapted.count('SUM(GREATEST(-price_delta,0))'), 2)
        self.assertEqual(adapted.count('NULLIF(CAST(SUM(ABS(price_delta))'), 2)
        self.assertEqual(adapted.count('?'), 1)
        self.assertNotIn(' / NULLIF', adapted)
        self.assertIn(adapter.RSI_UDF, adapter.adapt_compiler_sql(con, sql.lower()))
        for malformed in ("SELECT 'unterminated", 'SELECT /* unterminated'):
            with self.assertRaises(ValueError):
                adapter.adapt_compiler_sql(con, malformed)

    def test_rsi_transform_refuses_persistent_or_attached_raw_reference(self):
        con = Mock()
        con.execute.return_value.fetchall.return_value = [(0, 'memory', None), (1, 'raw', 'reference.duckdb')]
        with self.assertRaisesRegex(ValueError, 'in-memory fixture only'):
            adapter.adapt_compiler_sql(con, 'SELECT ' + rsi_expression())
        con.create_function.assert_not_called()

    def test_portable_rsi_transform_calls_are_exclusively_in_native_none_branches(self):
        for name in ('check_project_fields.py', 'check_project_combinations.py', 'check_project_rank_combinations.py'):
            tree = ast.parse((ROOT / 'scripts/doris' / name).read_text(encoding='utf-8'))
            def calls(nodes):
                return [n for node in nodes for n in ast.walk(node) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'adapt_compiler_sql']
            transforms = calls([tree])
            guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
                and ast.unparse(n.test) == 'native is None' and calls(n.body)]
            self.assertEqual(len(transforms), 1, name)
            self.assertEqual(len(guards), 1, name)
            self.assertFalse(calls(guards[0].orelse), name)


if __name__ == '__main__':
    unittest.main()
