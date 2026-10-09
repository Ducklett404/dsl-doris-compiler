"""Independent RSI integer math, finite precision disclosure and cleanup gates."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_project_ma_precision as ma
import check_project_rsi_precision as rsi

DATABASE = 'dsl_rsi_precision_012345abcdef'


def artifact():
    return dict(sql='WITH history AS (\n SELECT b.mktcode,b.tgtcode,b.bizdate,b.closePrice AS `v1`\n'
        ' FROM newzl.v_hsj_stock_hq_basic b WHERE b.bizdate<=?\n),\n'
        'deltas AS (SELECT history.*,`v1`-LAG(`v1`) OVER () AS price_delta FROM history),\n'
        'features AS (SELECT deltas.*,CAST(100*SUM(GREATEST(price_delta,0)) OVER () AS DECIMAL(30,8))/'
        'NULLIF(CAST(SUM(ABS(price_delta)) OVER () AS DECIMAL(24,4)),0) AS `f1` FROM deltas),\n'
        'current_rows AS (SELECT * FROM features WHERE bizdate=?)\n'
        'SELECT mktcode,tgtcode\nFROM current_rows\nWHERE (`f1`>=?) ORDER BY mktcode,tgtcode;',
        bindings=[rsi.EVALUATION_DATE, rsi.EVALUATION_DATE, 50])


class FakeClient:
    def __init__(self, case, *, wrong_strict=False, wrong_limit=False, wrong_projection=False,
                 collision=False, fail_insert=False, fail_drop=False, bad_type=False, changed_registry=False):
        self.case = case
        self.wrong_strict = wrong_strict
        self.wrong_limit = wrong_limit
        self.wrong_projection = wrong_projection
        self.collision = collision
        self.fail_insert = fail_insert
        self.fail_drop = fail_drop
        self.bad_type = bad_type
        self.changed_registry = changed_registry
        self.calls = []
        self.registry_reads = 0

    def query(self, sql):
        self.calls.append(sql)
        if sql == ma.SOURCE_STATE_SQL:
            return [('basic', '5', '2006-01-04', rsi.EVALUATION_DATE)]
        if sql == 'SELECT * FROM newzl.data_snapshot_registry':
            self.registry_reads += 1
            return [('changed',)] if self.changed_registry and self.registry_reads > 1 else [('preserved',)]
        if sql.startswith('SHOW DATABASES'):
            return [(DATABASE,)] if self.collision else []
        if sql.startswith('INSERT INTO') and self.fail_insert:
            raise RuntimeError('mock RSI insert failure')
        if sql.startswith('DROP DATABASE') and self.fail_drop:
            raise RuntimeError('mock RSI drop failure')
        fixtures = rsi.strict_vectors() + rsi.limit_vectors()
        if sql.startswith('SELECT COUNT(*)'):
            return [(str(sum(len(v['observations']) for v in fixtures)),)]
        if sql.startswith('DESC ') and '.rsi_probe_' in sql:
            return [('f1', 'double' if self.bad_type else 'decimal(38,12)')]
        if sql.startswith('DESC '):
            return [('closePx', 'bigint'), ('closePrice', 'decimal(19,4)')]
        if sql.startswith('EXPLAIN VERBOSE '):
            return [('fixed synthetic RSI explain',)]
        if sql.startswith('WITH '):
            if 'SELECT mktcode,tgtcode,`f1`' not in sql:
                strict = [] if self.wrong_strict else rsi.expected(self.case, rsi.strict_vectors())
                limits = [] if self.wrong_limit else rsi.expected(self.case, rsi.limit_vectors(), finite=True)
                return [tuple(r) for r in sorted(strict + limits)]
            output = []
            for vector in sorted(fixtures, key=lambda v: (v['market'], v['code'])):
                value = rsi.declared_output(rsi.exact_rsi(vector['observations'], self.case['n']))
                text = 'NULL' if value is None else ma.rational_evidence(value)['decimal80']
                output.append((str(vector['market']), vector['code'], text))
            if self.wrong_projection:
                output[-1] = (*output[-1][:2], '49')
            return output
        return []


class RsiPrecisionOracleTest(unittest.TestCase):
    def test_two_real_exact50_gain_loss_raw_integers(self):
        first, second = rsi.strict_vectors()[:2]
        self.assertEqual((first['code'], second['code']), ('000903', '300135'))
        self.assertEqual(rsi.sums(first['observations'], 5), dict(gain=700, loss=700, absolute=1400, completeDeltas=5))
        self.assertEqual(rsi.sums(second['observations'], 5), dict(gain=1500, loss=1500, absolute=3000, completeDeltas=5))
        for vector in (first, second):
            self.assertEqual(rsi.exact_rsi(vector['observations'], 5), 50)
            self.assertEqual([r['date'] for r in vector['observations']],
                ['2026-04-07', '2026-04-08', '2026-04-09', '2026-04-10', '2026-04-13', '2026-04-14'])

    def test_fixture_inventory_unique_keys_domain_dates_signed_bigints(self):
        strict, limits = rsi.strict_vectors(), rsi.limit_vectors()
        self.assertEqual(len(strict), 12)
        self.assertEqual(len(limits), 1)
        self.assertTrue(all(v['evidenceDomain'] == 'STRICT_EXACT_FIXTURE' for v in strict))
        self.assertEqual(limits[0]['evidenceDomain'], 'FINITE_PRECISION_LIMIT')
        fixtures = strict + limits
        self.assertEqual(len({v['code'] for v in fixtures}), len(fixtures))
        for vector in fixtures:
            days = [r['date'] for r in vector['observations']]
            self.assertEqual(days, sorted(set(days)))
            self.assertEqual(days[-1], rsi.EVALUATION_DATE)
            for row in vector['observations']:
                if row['closePx'] is not None:
                    self.assertIs(type(row['closePx']), int)
                    self.assertTrue(-(2 ** 63) <= row['closePx'] < 2 ** 63)

    def test_six_strict_operators_at_50_have_hand_labelled_normal_keys(self):
        codes = {'=': ['000903', '300135', 'RS0009'],
                 '!=': ['RS0001', 'RS0002', 'RS0008', 'RS0010'],
                 '>': ['RS0001'],
                 '>=': ['000903', '300135', 'RS0001', 'RS0009'],
                 '<': ['RS0002', 'RS0008', 'RS0010'],
                 '<=': ['000903', '300135', 'RS0002', 'RS0008', 'RS0009', 'RS0010']}
        for case in rsi.cases()[:6]:
            self.assertEqual(rsi.expected(case, rsi.strict_vectors()),
                             [['0', code] for code in codes[case['operator']]], case['operator'])

    def test_one_raw_unit_neighbors_are_strictly_on_opposite_sides(self):
        above, below = rsi.strict_vectors()[2:4]
        self.assertEqual(rsi.exact_rsi(above['observations'], 5), Fraction(4000100, 80001))
        self.assertEqual(rsi.exact_rsi(below['observations'], 5), Fraction(4000000, 80001))
        self.assertGreater(rsi.exact_rsi(above['observations'], 5), 50)
        self.assertLess(rsi.exact_rsi(below['observations'], 5), 50)

    def test_null_short_zero_loss_are_unknown_for_every_comparator(self):
        for vector in rsi.strict_vectors()[4:9]:
            self.assertIsNone(rsi.exact_rsi(vector['observations'], 5))
            for case in rsi.cases()[:6]:
                self.assertEqual(rsi.expected(case, [vector]), [])

    def test_all_falls_are_zero_and_negative_prices_have_exact50(self):
        falling, negative = rsi.strict_vectors()[9:11]
        self.assertEqual(rsi.exact_rsi(falling['observations'], 5), 0)
        self.assertEqual(rsi.exact_rsi(negative['observations'], 5), 50)

    def test_five_thousand_deltas_preserve_signed_bigint_source_extremes_without_overflow(self):
        vector = rsi.strict_vectors()[-1]
        parts = rsi.sums(vector['observations'], 5000)
        difference = 2 ** 64 - 1
        self.assertEqual(len(vector['observations']), 5001)
        self.assertEqual(parts['gain'], 2500 * difference)
        self.assertEqual(parts['loss'], 2500 * difference)
        self.assertEqual(parts['absolute'], 5000 * difference)
        self.assertEqual(rsi.exact_rsi(vector['observations'], 5000), 50)
        # SUMABS normalized by 1e4 fits 20 integer digits in DECIMAL(24,4).
        self.assertLess(parts['absolute'], 10 ** 24)
        # 100*gain normalized by 1e4, rescaled to 8 places, fits DECIMAL(30,8).
        self.assertLess(100 * parts['gain'] * 10000, 10 ** 30)
        self.assertEqual(rsi.exact_rsi(vector['observations'], 5), 40)

    def test_extreme_diagnostic_is_above50_but_declared12_places_collapse_to50(self):
        vector = rsi.limit_vectors()[0]
        parts = rsi.sums(vector['observations'], 5000)
        difference = 2 ** 64 - 1
        self.assertEqual((parts['gain'], parts['loss']), (2500 * difference, 2500 * difference - 1))
        exact = rsi.exact_rsi(vector['observations'], 5000)
        self.assertEqual(exact - 50, Fraction(50, 5000 * difference - 1))
        self.assertGreater(exact, 50)
        self.assertLess(exact - 50, Fraction(1, 10 ** 21))
        self.assertEqual(rsi.declared_output(exact), 50)
        case = rsi.cases()[8]  # RSI5000 >50.
        self.assertEqual(rsi.expected(case, [vector]), [['0', 'RL0001']])
        self.assertEqual(rsi.expected(case, [vector], finite=True), [])

    def test_limit_has_four_comparator_differences_times_two_paths_not_normal_failures(self):
        mismatches = [c['operator'] for c in rsi.cases()[6:]
                      if rsi.expected(c, rsi.limit_vectors()) != rsi.expected(c, rsi.limit_vectors(), finite=True)]
        self.assertEqual(mismatches, ['=', '!=', '>', '<='])
        self.assertEqual(len(mismatches) * 2, 8)

    def test_normal_keys_are_exact_without_rounding_oracle_or_tolerance(self):
        for case in rsi.cases():
            self.assertEqual(rsi.expected(case, rsi.strict_vectors()),
                             rsi.expected(case, rsi.strict_vectors(), finite=True))
        with patch.object(Path, 'read_text', side_effect=AssertionError('file oracle')), \
                patch.object(rsi, 'compiled_paths', side_effect=AssertionError('SQL oracle')), \
                patch.object(rsi, 'WslDoris', side_effect=AssertionError('database oracle')):
            self.assertEqual(rsi.expected(rsi.cases()[2], rsi.strict_vectors()), [['0', 'RS0001']])

    def test_loss_positive_sum_formula_equals_original_fraction_definition(self):
        for vector in rsi.strict_vectors() + rsi.limit_vectors():
            for n in (5, 5000):
                parts = rsi.sums(vector['observations'], n)
                exact = rsi.exact_rsi(vector['observations'], n)
                if parts is not None and parts['loss']:
                    old = 100 - Fraction(100, 1 + Fraction(parts['gain'], parts['loss']))
                    self.assertEqual(exact, old)
                else:
                    self.assertIsNone(exact)

    def test_case_inventory_and_invalid_windows_operators(self):
        self.assertEqual(len(rsi.cases()), 12)
        self.assertEqual(len({c['name'] for c in rsi.cases()}), 12)
        self.assertEqual({c['operator'] for c in rsi.cases()}, set(rsi.OPERATORS))
        for n in (0, 5001, -1, True, '5'):
            with self.assertRaises(ValueError):
                rsi.sums([], n)
        for value in (Fraction(-1), Fraction(101)):
            with self.assertRaises(ValueError):
                rsi.declared_output(value)
        with self.assertRaises(ValueError):
            rsi.compare(50, '~=')


class RsiPrecisionSafetyTest(unittest.TestCase):
    def test_database_names_are_exact_owned_not_ma_newzl_or_injectable(self):
        self.assertEqual(rsi.owned_database(DATABASE), DATABASE)
        for name in ('newzl', 'dsl_ma_precision_012345abcdef', DATABASE + '\n',
                     DATABASE + '; DROP DATABASE newzl', 'dsl_rsi_precision_012345ABCDEF', None):
            with self.assertRaises(ValueError):
                rsi.owned_database(name)

    def test_fixed_artifacts_reject_other_sources_values_and_binary_floating_accumulation(self):
        compiled = artifact()
        self.assertIn(DATABASE + '.v_hsj_stock_hq_basic', rsi.checked_sql(compiled, DATABASE))
        altered = [dict(compiled, bindings=[rsi.EVALUATION_DATE, rsi.EVALUATION_DATE, 50.0]),
                   dict(compiled, bindings=[rsi.EVALUATION_DATE, rsi.EVALUATION_DATE, True]),
                   dict(compiled, bindings=[rsi.EVALUATION_DATE, rsi.EVALUATION_DATE, 51]),
                   dict(compiled, sql=compiled['sql'].replace('newzl.v_hsj_stock_hq_basic', 'other.private_table')),
                   dict(compiled, sql=compiled['sql'].replace('DECIMAL(30,8)', 'DOUBLE')),
                   dict(compiled, sql=compiled['sql'] + ' DROP DATABASE newzl;'),
                   dict(compiled, sql=compiled['sql'].replace('WHERE', 'WHERE /*bad*/', 1))]
        for value in altered:
            with self.assertRaises(ValueError):
                rsi.checked_sql(value, DATABASE)

    def test_projection_shape_and_alias_fail_closed(self):
        sql = rsi.checked_sql(artifact(), DATABASE)
        self.assertIn('SELECT mktcode,tgtcode,`f1`', rsi.projection_sql(sql))
        for altered in (sql.replace('AS `f1`', 'AS `f2`'), sql.replace('current_rows', 'changed_rows')):
            with self.assertRaises(ValueError):
                rsi.projection_sql(altered)

    def run_mock(self, client, report):
        return rsi.run_native(client, DATABASE, [client.case],
            [dict(project=artifact(), reference=artifact())], report)

    def test_success_records_both_paths_no_source_writes_and_formal_registry_unchanged(self):
        client, report = FakeClient(rsi.cases()[9]), dict(checks=[])
        self.run_mock(client, report)
        self.assertEqual([c['mode'] for c in report['checks']], ['project', 'reference'])
        self.assertTrue(all(c['status'] == 'PASS' and c['explain'] and c['sql'] for c in report['checks']))
        self.assertTrue(all(p['decimalScale12'] and p['finiteOutputValuesEqual'] for p in report['projections']))
        self.assertEqual(report['fixtureCleanup'], 'DONE')
        self.assertEqual(report['cleanupErrors'], [])
        self.assertTrue(report['sourceStateUnchanged'] and report['formalRegistryUnchanged'])
        writes = [s for s in client.calls if s.split()[0] in ('CREATE', 'INSERT', 'DROP')]
        self.assertTrue(all('newzl' not in s for s in writes))
        self.assertEqual(client.calls.count('DROP DATABASE ' + DATABASE), 1)

    def test_precision_limit_is_retained_not_added_to_strict_pass_or_discarded(self):
        client, report = FakeClient(rsi.cases()[8]), dict(checks=[])
        self.run_mock(client, report)
        self.assertTrue(all(c['status'] == 'PASS' for c in report['checks']))
        for evidence in report['finitePrecisionLimitEvidence']:
            self.assertEqual(evidence['status'], 'PRECISION_LIMIT_OBSERVED')
            self.assertFalse(evidence['exactKeysEqual'])
            self.assertTrue(evidence['declaredOutputMatches'])
            self.assertEqual(evidence['exactRationalExpected'], [['0', 'RL0001']])
            self.assertEqual(evidence['actual'], [])

    def test_runtime_failures_cleanup_owned_namespace_and_never_hide_wrong_values(self):
        for options in (dict(wrong_strict=True), dict(wrong_limit=True), dict(wrong_projection=True),
                        dict(fail_insert=True), dict(bad_type=True)):
            client, report = FakeClient(rsi.cases()[9], **options), dict(checks=[])
            with self.assertRaises((AssertionError, RuntimeError)):
                self.run_mock(client, report)
            self.assertEqual(report['fixtureCleanup'], 'DONE')
            self.assertEqual(client.calls.count('DROP DATABASE ' + DATABASE), 1)
            self.assertTrue(report['formalRegistryUnchanged'])

    def test_collision_never_reused_or_deleted_and_preflight_precedes_mutation(self):
        client, report = FakeClient(rsi.cases()[9], collision=True), dict(checks=[])
        with self.assertRaises(ValueError):
            self.run_mock(client, report)
        self.assertEqual(report['fixtureCleanup'], 'NOT_CREATED')
        self.assertFalse(any(s.startswith(('CREATE', 'INSERT', 'DROP')) for s in client.calls))
        client = FakeClient(rsi.cases()[9])
        with self.assertRaises(ValueError):
            rsi.run_native(client, DATABASE, [client.case], [dict(project=artifact())], dict(checks=[]))
        self.assertEqual(client.calls, [])

    def test_cleanup_failure_or_formal_registration_change_is_failure(self):
        for options in (dict(fail_drop=True), dict(changed_registry=True)):
            client, report = FakeClient(rsi.cases()[9], **options), dict(checks=[])
            with self.assertRaises(AssertionError):
                self.run_mock(client, report)
            self.assertTrue(report['cleanupErrors'])
            if options.get('fail_drop'):
                self.assertEqual(report['fixtureCleanup'], 'FAILED')
            else:
                self.assertFalse(report['formalRegistryUnchanged'])

    def test_execute_required_and_report_directory_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(rsi, 'WslDoris', side_effect=AssertionError('must not start Doris')):
                with self.assertRaises(SystemExit):
                    rsi.main(['--report-dir', folder])
                with self.assertRaises(ValueError):
                    rsi.main(['--report-dir', folder, '--execute'])


if __name__ == '__main__':
    unittest.main()
