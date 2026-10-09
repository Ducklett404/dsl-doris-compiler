"""Narrow-window raw loading matches the former wide-window oracle query.

Only disposable synthetic DuckDB tables are used, in memory or in a fresh
temporary file. No official source, CSV, Doris instance, semantic view, registry
or generated compiler SQL is accessed.
"""
from collections import defaultdict
import os
from pathlib import Path
import tempfile
import unittest

import duckdb

from check_official_field_acceptance import RAW_COLUMNS
from project_field_reference import configure_reference_connection, load, observation
from project_matrix_reference import load as load_matrix


ANCHOR = '2026-04-14'
FACTOR_COLUMNS = {'qfqMulti', 'qfqAdd', 'hfqMulti', 'hfqAdd'}


def old_load(con, day, retained_rows=64):
    """Preserved prior SQL solely for independent row-selection regression."""
    rows = con.execute(
        'WITH tail AS (SELECT mktcode,tgtcode,bizdate,' + ','.join(RAW_COLUMNS)
        + ' FROM newzl.hsj_stock_hq_basic WHERE bizdate<=CAST(? AS DATE) '
          'QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=?) '
          'SELECT b.*,e.tgtcode,e.ZJLXMainNetTur FROM tail b '
          'LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) '
          'ORDER BY b.mktcode,b.tgtcode,b.bizdate',
        [day, retained_rows],
    ).fetchall()
    histories = defaultdict(list)
    for market, code, observed_day, *values in rows:
        ext, net = values[-2:]
        raw = dict(zip(RAW_COLUMNS, values[:-2]))
        raw['net'] = net
        histories[(str(market), code)].append(observation(observed_day, raw, ext is not None))
    names = {(str(m), c): name for m, c, name in con.execute(
        'SELECT mktcode,tgtcode,name FROM newzl.hsj_stock_code_info').fetchall()}
    return dict(histories={k: h for k, h in histories.items() if h[-1]['date'] == day}, names=names)


class CapturingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.calls = []

    def execute(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        return self.connection.execute(sql, parameters) if parameters is not None else self.connection.execute(sql)


class ProjectReferenceLoadingTest(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(':memory:')
        self.addCleanup(self.con.close)
        self.con.execute('CREATE SCHEMA newzl')
        columns = ','.join(column + (' DOUBLE' if column in FACTOR_COLUMNS else ' BIGINT') for column in RAW_COLUMNS)
        self.con.execute('CREATE TABLE newzl.hsj_stock_hq_basic '
                         '(mktcode INTEGER,tgtcode VARCHAR,bizdate DATE,' + columns + ')')
        self.con.execute('CREATE TABLE newzl.hsj_stock_hq_ext '
                         '(mktcode INTEGER,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT)')
        self.con.execute('CREATE TABLE newzl.hsj_stock_code_info '
                         '(mktcode INTEGER,tgtcode VARCHAR,name VARCHAR)')
        self._add(0, '000001', '2006-01-04', 1)
        self._add(0, '000001', '2026-04-10', 2)
        self._add(0, '000001', '2026-04-13', 3, closePx=None, qfqMulti=None)
        self._add(0, '000001', ANCHOR, 4, turnover=None, preClosePx=0)
        self._add(0, '000001', '2026-04-15', 99)
        # The same code in a different market must retain its own observed tail.
        self._add(1, '000001', '2018-08-20', 5)
        self._add(1, '000001', '2026-04-12', 6, volume=0)
        self._add(1, '000001', ANCHOR, 7)
        # Sparse observations count as rows, never as synthesized calendar days.
        self._add(103, '000003', '2006-01-04', 8)
        self._add(103, '000003', '2026-04-02', 9)
        self._add(103, '000003', ANCHOR, 10)
        # This suspended security has history but no observation at the anchor.
        self._add(1, '000004', '2026-04-10', 11)
        self._add(1, '000004', '2026-04-13', 12)
        self._add(1, '000004', '2026-04-15', 13)
        self._add(0, '000005', ANCHOR, 14)  # Newly listed: one observed row.
        self._add(0, '000006', '2026-04-15', 15)  # Future-only security.
        self._add(1, '000007', ANCHOR, 16)  # No security-info entry.
        self._add(103, '000008', ANCHOR, 17, **dict.fromkeys(RAW_COLUMNS))
        ext = [(0, '000001', '2006-01-04', -5),
               (0, '000001', '2026-04-13', None),
               (0, '000001', ANCHOR, -999999),
               (0, '000001', '2026-04-15', 999999),
               (1, '000001', '2018-08-20', 12),
               (1, '000001', ANCHOR, -999998),
               (103, '000003', ANCHOR, 0),
               (0, '000005', ANCHOR, None),
               (1, '000007', ANCHOR, -123),
               (103, '000008', ANCHOR, None),
               (103, '000009', ANCHOR, 123),  # Extension orphan, no basic row.
               (1, '000001', '2026-04-13', 456)]  # Missing basic key of a valid security.
        self.con.executemany('INSERT INTO newzl.hsj_stock_hq_ext VALUES(?,?,?,?)', ext)
        self.con.executemany('INSERT INTO newzl.hsj_stock_code_info VALUES(?,?,?)',
                             [(0, '000001', '深一'), (1, '000001', '沪一'),
                              (103, '000003', '京三'), (1, '000004', '停牌四'),
                              (0, '000005', '新股五'), (0, '000006', '未来六'),
                              (103, '000008', None), (1, '000099', '无行情信息')])

    def _add(self, market, code, day, value, **changes):
        raw = {column: value * 10000 for column in RAW_COLUMNS}
        raw.update(volume=value * 10, turnover=value * 1000,
                   totalShare=value * 100, listedShare=value * 50,
                   qfqMulti=1.25, qfqAdd=-0.5, hfqMulti=2.5, hfqAdd=0.75)
        raw.update(changes)
        parameters = [market, code, day, *[raw[column] for column in RAW_COLUMNS]]
        self.con.execute('INSERT INTO newzl.hsj_stock_hq_basic VALUES('
                         + ','.join('?' for _ in parameters) + ')', parameters)

    def test_full_old_and_new_output_match_across_dates_and_budgets(self):
        for day in ['2005-12-31', '2006-01-04', '2018-08-20', '2026-04-10',
                    '2026-04-12', '2026-04-13', ANCHOR, '2026-04-15', '2026-04-16']:
            for budget in [1, 2, 3, 4, 21, 64, 250]:
                with self.subTest(day=day, retained_rows=budget):
                    self.assertEqual(load(self.con, day, budget), old_load(self.con, day, budget))

    def test_fixture_has_the_non_null_unique_raw_key_contract_required_for_refetch(self):
        # Real reference rebuild independently checks these same invariants before
        # consumers run. A composite-key refetch must not be used for an unaudited
        # basic source with duplicate keys or NULL key components.
        self.assertEqual(self.con.execute(
            'SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic '
            'WHERE mktcode IS NULL OR tgtcode IS NULL OR bizdate IS NULL').fetchone()[0], 0)
        self.assertEqual(self.con.execute(
            'SELECT COUNT(*) FROM (SELECT mktcode,tgtcode,bizdate '
            'FROM newzl.hsj_stock_hq_basic GROUP BY mktcode,tgtcode,bizdate '
            'HAVING COUNT(*)>1) duplicate_keys').fetchone()[0], 0)

    def test_latest_real_rows_keep_sparse_null_and_new_security_observations(self):
        actual = load(self.con, ANCHOR, 2)
        self.assertEqual(set(actual['histories']),
                         {('0', '000001'), ('1', '000001'), ('103', '000003'),
                          ('0', '000005'), ('1', '000007'), ('103', '000008')})
        self.assertEqual([row['date'] for row in actual['histories'][('103', '000003')]],
                         ['2026-04-02', ANCHOR])
        self.assertEqual([row['date'] for row in actual['histories'][('0', '000001')]],
                         ['2026-04-13', ANCHOR])
        self.assertIsNone(actual['histories'][('0', '000001')][0]['close'])
        self.assertEqual(len(actual['histories'][('0', '000005')]), 1)
        self.assertNotIn(('1', '000004'), actual['histories'])
        self.assertNotIn(('0', '000006'), actual['histories'])

    def test_extension_null_missing_sentinel_legal_negative_and_orphans_stay_distinct(self):
        histories = load(self.con, ANCHOR, 4)['histories']
        deep = histories[('0', '000001')]
        self.assertEqual([(row['ext'], row['rawNet'], row['net']) for row in deep],
                         [(True, -5, -5), (False, None, None),
                          (True, None, None), (True, -999999, None)])
        self.assertEqual(histories[('1', '000001')][-1]['net'], -999998)
        self.assertFalse(histories[('1', '000001')][-2]['ext'])
        self.assertNotIn(('103', '000009'), histories)

    def test_no_code_info_inner_join_or_name_universe_filter_is_added(self):
        actual = load(self.con, ANCHOR, 2)
        self.assertIn(('1', '000007'), actual['histories'])
        self.assertNotIn(('1', '000007'), actual['names'])
        self.assertEqual(actual['names'][('1', '000099')], '无行情信息')
        self.assertIsNone(actual['names'][('103', '000008')])

    def test_raw_types_leading_zero_codes_factors_and_all_null_operands_survive(self):
        raw = load(self.con, ANCHOR, 2)['histories'][('1', '000001')][-1]['operands']
        self.assertIsInstance(raw['closePx'], int)
        self.assertEqual(raw['closePx'], 70000)
        self.assertEqual((raw['qfqMulti'], raw['qfqAdd'], raw['hfqMulti'], raw['hfqAdd']),
                         (1.25, -0.5, 2.5, 0.75))
        null_row = load(self.con, ANCHOR, 2)['histories'][('103', '000008')][-1]
        self.assertTrue(all(value is None for value in null_row['normalized'].values()))
        self.assertTrue(all(value is None for value in null_row['positions'].values()))

    def test_matrix_overlap_stays_identical_without_sharing_its_loader_sql(self):
        for budget in [1, 2, 64]:
            fields = load(self.con, ANCHOR, budget)
            matrix = load_matrix(self.con, ANCHOR, budget)
            projected = {key: [{column: row[column] for column in
                               ['date', 'close', 'open', 'volume', 'ext', 'net']}
                              for row in history] for key, history in fields['histories'].items()}
            self.assertEqual(projected, matrix['histories'])
            self.assertEqual(fields['names'], matrix['names'])

    def test_only_raw_keys_are_materialized_before_wide_operand_fetch(self):
        captured = CapturingConnection(self.con)
        self.assertEqual(load(captured, ANCHOR, 2), old_load(self.con, ANCHOR, 2))
        sql, bindings = captured.calls[0]
        narrow = sql.split('SELECT b.mktcode', 1)[0]
        self.assertIn('tail_keys AS MATERIALIZED (SELECT mktcode,tgtcode,bizdate ', narrow)
        self.assertIn('PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC', narrow)
        for column in RAW_COLUMNS:
            self.assertNotIn(column, narrow)
        self.assertEqual(bindings, [ANCHOR, 2])
        self.assertIn('JOIN newzl.hsj_stock_hq_basic b USING(mktcode,tgtcode,bizdate)', sql)
        self.assertIn('LEFT JOIN newzl.hsj_stock_hq_ext', sql)
        self.assertEqual(len(captured.calls), 2)

    def test_invalid_budgets_reject_before_executing_any_query(self):
        captured = CapturingConnection(self.con)
        for budget in [0, -1, 2.0, '2', None]:
            with self.subTest(retained_rows=budget), self.assertRaises(ValueError):
                load(captured, ANCHOR, budget)
        self.assertFalse(captured.calls)

    def test_resource_configuration_applies_actual_one_gb_one_thread_and_unordered_insertion(self):
        path = Path('target/reference-resource-contract-not-opened.duckdb')
        captured = CapturingConnection(self.con)
        settings = configure_reference_connection(captured, path)
        self.assertEqual(settings, dict(memory_limit='1GB', threads=1,
                                       preserve_insertion_order=False,
                                       temp_directory=str(path.resolve()) + '.tmp'))
        memory, threads, insertion, temp = self.con.execute(
            "SELECT current_setting('memory_limit'),current_setting('threads'),"
            "current_setting('preserve_insertion_order'),current_setting('temp_directory')").fetchone()
        # DuckDB formats decimal 1GB in binary display units (e.g. 953.6 MiB).
        # Its display is rounded; assert actual scale as well as the exact bound
        # SET value rather than expecting a particular presentation spelling.
        amount, unit = memory.split()
        units = {'B': 1, 'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3,
                 'KB': 1000, 'MB': 1000**2, 'GB': 1000**3}
        self.assertAlmostEqual(float(amount) * units[unit], 1_000_000_000, delta=1_000_000)
        self.assertEqual((threads, insertion, temp), (1, False, settings['temp_directory']))
        self.assertEqual(captured.calls, [('SET ' + name + ' = ?', [value])
                                         for name, value in settings.items()])

    def test_resource_spill_path_is_absolute_and_adjacent_for_d_style_input_without_opening_source(self):
        source = Path('D:/dsl-reference-resource-contract-not-opened/reference.duckdb')
        resolved = source.resolve()
        spill = Path(str(resolved) + '.tmp')
        source_existed, spill_existed = source.exists(), spill.exists()
        settings = configure_reference_connection(self.con, source)
        actual_temp = self.con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        self.assertEqual(actual_temp, str(resolved) + '.tmp')
        self.assertEqual(settings['temp_directory'], actual_temp)
        self.assertTrue(Path(actual_temp).is_absolute())
        self.assertEqual(Path(actual_temp).parent, resolved.parent)
        if os.name == 'nt':
            self.assertEqual(Path(actual_temp).drive.lower(), 'd:')
        # A resource configuration must not open/create its source database.
        self.assertEqual((source.exists(), spill.exists()), (source_existed, spill_existed))

    def test_quoted_sql_like_temp_path_stays_a_bound_setting_not_an_executed_statement(self):
        with tempfile.TemporaryDirectory(prefix='raw-resource-path-contract-') as directory:
            source = Path(directory) / "raw'; SELECT 123; -- reference.duckdb"
            captured = CapturingConnection(self.con)
            settings = configure_reference_connection(captured, source)
            self.assertEqual(captured.calls[-1],
                             ('SET temp_directory = ?', [str(source.resolve()) + '.tmp']))
            for sql, parameters in captured.calls:
                self.assertNotIn(str(source), sql)
                self.assertEqual(len(parameters), 1)
            self.assertEqual(self.con.execute("SELECT current_setting('temp_directory')").fetchone()[0],
                             settings['temp_directory'])
            self.assertEqual(load(self.con, ANCHOR, 2), old_load(self.con, ANCHOR, 2))
            self.assertFalse(source.exists())

    def test_configure_then_load_fresh_read_only_database_preserves_main_bytes_and_no_wal(self):
        expected = old_load(self.con, ANCHOR, 2)
        with tempfile.TemporaryDirectory(prefix='read-only-reference-resource-contract-') as directory:
            source = Path(directory) / "synthetic' reference.duckdb"
            with duckdb.connect(str(source)) as writable:
                writable.execute('CREATE SCHEMA newzl')
                columns = ','.join(column + (' DOUBLE' if column in FACTOR_COLUMNS else ' BIGINT')
                                   for column in RAW_COLUMNS)
                schemas = {
                    'hsj_stock_hq_basic': '(mktcode INTEGER,tgtcode VARCHAR,bizdate DATE,' + columns + ')',
                    'hsj_stock_hq_ext': '(mktcode INTEGER,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT)',
                    'hsj_stock_code_info': '(mktcode INTEGER,tgtcode VARCHAR,name VARCHAR)',
                }
                for name, schema in schemas.items():
                    rows = self.con.execute('SELECT * FROM newzl.' + name).fetchall()
                    writable.execute('CREATE TABLE newzl.' + name + schema)
                    writable.executemany('INSERT INTO newzl.' + name + ' VALUES('
                                         + ','.join('?' for _ in rows[0]) + ')', rows)
                writable.execute('CHECKPOINT')
            before = source.read_bytes()
            wal = Path(str(source) + '.wal')
            self.assertFalse(wal.exists())
            with duckdb.connect(str(source), read_only=True) as read_only:
                settings = configure_reference_connection(read_only, source)
                self.assertEqual(settings['temp_directory'], str(source.resolve()) + '.tmp')
                self.assertEqual(load(read_only, ANCHOR, 2), expected)
                # This write targets only our fresh fixture and must be refused
                # by the real read-only connection, not simulated by a mock.
                with self.assertRaises(duckdb.InvalidInputException):
                    read_only.execute('CREATE TABLE forbidden_write(value INTEGER)')
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(wal.exists())


if __name__ == '__main__':
    unittest.main()
