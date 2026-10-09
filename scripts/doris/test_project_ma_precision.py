"""Offline MA precision hand calculations and owned-fixture safety checks."""
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_DOWN
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_project_ma_precision as ma


DATABASE = 'dsl_ma_precision_012345abcdef'
CLOSE = 'CAST(CAST(b.closePx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4))'


def compiled_artifact():
    return dict(sql='WITH history AS (\n  SELECT b.mktcode,b.tgtcode,b.bizdate,b.closePrice AS `v1`\n'
        '  FROM newzl.v_hsj_stock_hq_basic b WHERE b.bizdate<=?\n),\n'
        'features AS (\n SELECT history.*,AVG(CAST(`v1` AS DECIMAL(38,18))) OVER () AS `f1`,\n'
        'AVG(CAST(`v1` AS DECIMAL(38,18))) OVER () AS `f2` FROM history\n),\n'
        'current_rows AS (SELECT * FROM features WHERE bizdate=?)\n'
        'SELECT mktcode,tgtcode\nFROM current_rows\nWHERE (`f1` > `f2`) ORDER BY mktcode,tgtcode;',
        bindings=[ma.EVALUATION_DATE, ma.EVALUATION_DATE])


class FakeClient:
    def __init__(self, case, *, wrong_rows=False, collision=False, fail_insert=False,
                 bad_type=False, changed_registry=False, fail_drop=False):
        self.case = case
        self.wrong_rows = wrong_rows
        self.collision = collision
        self.fail_insert = fail_insert
        self.bad_type = bad_type
        self.changed_registry = changed_registry
        self.fail_drop = fail_drop
        self.calls = []
        self.registry_reads = 0

    def query(self, sql):
        self.calls.append(sql)
        if sql == ma.SOURCE_STATE_SQL:
            return [('basic', '5', '2006-01-04', ma.EVALUATION_DATE)]
        if sql == 'SELECT * FROM newzl.data_snapshot_registry':
            self.registry_reads += 1
            return [('changed',)] if self.changed_registry and self.registry_reads > 1 else [('preserved',)]
        if sql.startswith('SHOW DATABASES'):
            return [(DATABASE,)] if self.collision else []
        if sql.startswith('INSERT INTO') and self.fail_insert:
            raise RuntimeError('mock insert failure')
        if sql.startswith('DROP DATABASE') and self.fail_drop:
            raise RuntimeError('mock drop failure')
        if sql.startswith('SELECT COUNT(*)'):
            return [(str(sum(len(v['observations']) for v in ma.vectors())),)]
        if sql.startswith('DESC ') and '.ma_probe_' in sql:
            return [('f1', 'double' if self.bad_type else 'decimal(38,18)'), ('f2', 'decimal(38,18)')]
        if sql.startswith('DESC '):
            return [('closePx', 'bigint'), ('closePrice', 'decimal(19,4)')]
        if sql.startswith('EXPLAIN VERBOSE '):
            return [('fixed synthetic explain',)]
        if sql.startswith('WITH '):
            if 'SELECT mktcode,tgtcode,`f1`,`f2`' not in sql:
                return [] if self.wrong_rows else [tuple(r) for r in ma.expected(self.case)]
            result = []
            for vector in sorted(ma.vectors(), key=lambda v: (v['market'], v['code'])):
                values = [ma.mean(vector['observations'], n) for n in self.case['windows']]
                result.append((str(vector['market']), vector['code'], *(
                    'NULL' if v is None else ma.rational_evidence(v)['decimal80'] for v in values)))
            return result
        return []


class MaPrecisionOracleTest(unittest.TestCase):
    def test_original_900924_raw_values_and_exact_hand_averages(self):
        specimen = ma.vectors()[0]
        self.assertEqual(specimen['code'], '900924')
        self.assertEqual([r['closePx'] for r in specimen['observations'][-3:]], [3550, 3530, 3530])
        self.assertEqual(ma.mean(specimen['observations'], 3), Fraction(1061, 3000))
        self.assertEqual(ma.mean(specimen['observations'], 5), Fraction(221, 625))
        self.assertEqual(ma.mean(specimen['observations'], 20), Fraction(141, 400))
        self.assertGreater(ma.mean(specimen['observations'], 3), ma.mean(specimen['observations'], 5))

    def test_fixture_domains_unique_names_keys_dates_and_signed_bigints(self):
        specimens = ma.vectors()
        self.assertEqual(len(specimens), 11)
        self.assertEqual(len({v['name'] for v in specimens}), 11)
        self.assertEqual(len({v['code'] for v in specimens}), 11)
        for vector in specimens:
            observations = vector['observations']
            days = [r['date'] for r in observations]
            self.assertEqual(days, sorted(set(days)))
            self.assertEqual(days[-1], ma.EVALUATION_DATE)
            for row in observations:
                if row['closePx'] is not None:
                    self.assertIs(type(row['closePx']), int)
                    self.assertTrue(-(2 ** 63) <= row['closePx'] < 2 ** 63)

    def test_all_six_operators_preserve_exact_three_vs_five_hand_keys(self):
        codes = {'=': ['MA0002', 'MA0005', 'MA0010'],
                 '!=': ['900924', 'MA0001', 'MA0003', 'MA0004', 'MA0007', 'MA0009'],
                 '>': ['900924', 'MA0003', 'MA0007', 'MA0009'],
                 '>=': ['900924', 'MA0002', 'MA0003', 'MA0005', 'MA0007', 'MA0009', 'MA0010'],
                 '<': ['MA0001', 'MA0004'],
                 '<=': ['MA0001', 'MA0002', 'MA0004', 'MA0005', 'MA0010']}
        for case in ma.cases()[:6]:
            operator = case['comparisons'][0][1]
            self.assertEqual(ma.expected(case), [['1', code] for code in codes[operator]], operator)

    def test_three_windows_and_has_independently_hand_labelled_keys(self):
        self.assertEqual(ma.expected(ma.cases()[-1]), [['1', '900924'], ['1', 'MA0003']])

    def test_signed_tiny_averages_do_not_collapse_to_four_places(self):
        positive, negative = ma.vectors()[3:5]
        self.assertEqual(ma.mean(positive['observations'], 3), Fraction(1, 7500))
        self.assertEqual(ma.mean(positive['observations'], 5), Fraction(3, 25000))
        self.assertGreater(ma.mean(positive['observations'], 3), ma.mean(positive['observations'], 5))
        self.assertLess(ma.mean(negative['observations'], 3), ma.mean(negative['observations'], 5))
        for specimen in (ma.vectors()[0], positive, negative):
            with localcontext() as context:
                context.prec = 80
                means = [ma.mean(specimen['observations'], n) for n in (3, 5)]
                rounded = [(Decimal(v.numerator) / v.denominator).quantize(Decimal('.0001'), rounding=ROUND_DOWN)
                           for v in means]
            self.assertNotEqual(means[0], means[1])
            self.assertEqual(rounded[0], rounded[1])

    def test_null_and_new_security_never_match_even_not_equal(self):
        specimens = ma.vectors()
        for vector in (specimens[6], specimens[8]):
            for operator in ma.OPERATORS:
                case = dict(windows=[3, 5], comparisons=[(0, operator, 1)])
                self.assertEqual(ma.expected(case, [vector]), [])
        self.assertIsNotNone(ma.mean(specimens[7]['observations'], 3))
        self.assertIsNone(ma.mean(specimens[7]['observations'], 20))
        self.assertIsNone(ma.mean(specimens[9]['observations'], 20))

    def test_maximum_5000_window_bigint_upper_preserves_adjacent_integer_difference(self):
        vector = ma.vectors()[-1]
        self.assertEqual(len(vector['observations']), 5000)
        self.assertEqual(vector['observations'][0]['closePx'], 2 ** 63 - 2)
        self.assertEqual(vector['observations'][-1]['closePx'], 2 ** 63 - 1)
        short, long = (ma.mean(vector['observations'], n) for n in (4999, 5000))
        self.assertEqual(short - long, Fraction(1, 50000000))
        self.assertEqual(float(short), float(long), 'DOUBLE cannot preserve this boundary')
        for case in ma.cases()[12:24]:
            selected = [['1', 'MA0010']] if case['comparisons'][0][1] in ('!=', '>', '>=') else []
            self.assertEqual(ma.expected(case), selected)

    def test_fixed_case_inventory_and_strict_comparators_have_no_epsilon(self):
        suite = ma.cases()
        self.assertEqual(len(suite), 25)
        self.assertEqual(len({c['name'] for c in suite}), 25)
        self.assertEqual({c['comparisons'][0][1] for c in suite}, set(ma.OPERATORS))
        self.assertFalse(any('~=' in c['dsl'] for c in suite))
        for n in (0, -1, 5001, True, '3'):
            with self.assertRaises(ValueError):
                ma.indicator(n)
            with self.assertRaises(ValueError):
                ma.mean([], n)

    def test_oracle_is_independent_of_files_java_sql_views_and_database(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('file oracle')), \
                patch.object(ma, 'compiled_paths', side_effect=AssertionError('compiler oracle')), \
                patch.object(ma, 'WslDoris', side_effect=AssertionError('database oracle')):
            self.assertEqual(ma.expected(ma.cases()[-1]), [['1', '900924'], ['1', 'MA0003']])

    def test_rational_evidence_is_exact_and_decimal_only_display_metadata(self):
        evidence = ma.rational_evidence(Fraction(1, 3))
        self.assertEqual((evidence['numerator'], evidence['denominator']), ('1', '3'))
        self.assertEqual(len(evidence['decimal80'].split('.')[1]), 80)
        self.assertIsNone(ma.rational_evidence(None))


class MaPrecisionSafetyTest(unittest.TestCase):
    def test_owned_database_names_reject_broad_scopes_and_injection(self):
        self.assertEqual(ma.owned_database(DATABASE), DATABASE)
        for name in ('newzl', 'dsl_ma_precision_abcdef', DATABASE + ';DROP DATABASE newzl',
                     'dsl_ma_precision_012345ABCDEF', DATABASE + '\n', None):
            with self.assertRaises(ValueError):
                ma.owned_database(name)

    def test_only_exact_audited_close_projection_is_accepted(self):
        self.assertEqual(ma.close_projection('  ' + CLOSE + ' AS closePrice,\n'), CLOSE)
        for text in ('CAST(b.closePx AS DOUBLE)/10000 AS closePrice,',
                     CLOSE + ' AS closePrice,\n' + CLOSE + ' AS closePrice,',
                     CLOSE + ' AS closePrice, DROP TABLE newzl.x;'):
            with self.assertRaises(ValueError):
                ma.close_projection(text)

    def test_artifact_gate_rejects_other_sources_user_values_comments_and_second_statement(self):
        valid = compiled_artifact()
        rewritten = ma.checked_sql(valid, DATABASE)
        self.assertIn(DATABASE + '.v_hsj_stock_hq_basic', rewritten)
        self.assertNotIn('newzl.', rewritten)
        mutations = []
        for replacement in ('newzl.hsj_stock_hq_ext', 'some_db.v_hsj_stock_hq_basic',
                            'newzl.v_hsj_stock_hq_basic JOIN dangerous.remote'):
            value = deepcopy(valid)
            value['sql'] = value['sql'].replace('newzl.v_hsj_stock_hq_basic', replacement)
            mutations.append(value)
        mutations.extend([dict(valid, sql=valid['sql'] + ' DROP DATABASE newzl;'),
                          dict(valid, sql=valid['sql'].replace('WHERE', 'WHERE /*x*/', 1)),
                          dict(valid, bindings=["2026-04-14' OR TRUE", ma.EVALUATION_DATE]),
                          dict(valid, bindings=[]), dict(valid, sql='SELECT * FROM newzl.x')])
        for value in mutations:
            with self.assertRaises(ValueError):
                ma.checked_sql(value, DATABASE)

    def test_projection_shape_and_aliases_fail_closed(self):
        case = ma.cases()[2]
        sql = ma.checked_sql(compiled_artifact(), DATABASE)
        probe, aliases = ma.projection_sql(sql, case)
        self.assertEqual(aliases, ['f1', 'f2'])
        self.assertIn('SELECT mktcode,tgtcode,`f1`,`f2`', probe)
        for sql in (sql.replace('AS `f2`', 'AS `f1`'), sql.replace('current_rows', 'changed_rows')):
            with self.assertRaises(ValueError):
                ma.projection_sql(sql, case)

    def run_mock(self, client, report):
        case = ma.cases()[2]
        return ma.run_native(client, DATABASE, [case],
                             [dict(project=compiled_artifact(), reference=compiled_artifact())],
                             ma.vectors(), CLOSE, report)

    def test_success_has_both_paths_scale_sql_explain_and_preserves_formal_registration(self):
        case = ma.cases()[2]
        client, report = FakeClient(case), dict(checks=[])
        self.run_mock(client, report)
        self.assertEqual([c['mode'] for c in report['checks']], ['project', 'reference'])
        self.assertTrue(all(c['status'] == 'PASS' and c['sql'] and c['explain'] for c in report['checks']))
        self.assertTrue(all(p['decimalScale18'] and p['nullPatternEqual'] for p in report['projections']))
        self.assertEqual(report['fixtureCleanup'], 'DONE')
        self.assertEqual(report['cleanupErrors'], [])
        self.assertTrue(report['formalRegistryUnchanged'] and report['sourceStateUnchanged'])
        writes = [s for s in client.calls if s.split()[0] in ('CREATE', 'INSERT', 'DROP')]
        self.assertTrue(writes)
        self.assertTrue(all('newzl' not in s for s in writes))
        self.assertEqual(client.calls.count('DROP DATABASE ' + DATABASE), 1)

    def test_failure_still_removes_only_created_namespace_and_preserves_evidence(self):
        case = ma.cases()[2]
        for options in (dict(wrong_rows=True), dict(fail_insert=True), dict(bad_type=True)):
            client, report = FakeClient(case, **options), dict(checks=[])
            with self.assertRaises((AssertionError, RuntimeError)):
                self.run_mock(client, report)
            self.assertEqual(report['fixtureCleanup'], 'DONE')
            self.assertTrue(report['formalRegistryUnchanged'])
            self.assertEqual(client.calls.count('DROP DATABASE ' + DATABASE), 1)
        self.assertEqual(report['checks'][0]['status'], 'PASS')

    def test_name_collision_is_never_deleted_or_reused(self):
        client, report = FakeClient(ma.cases()[2], collision=True), dict(checks=[])
        with self.assertRaises(ValueError):
            self.run_mock(client, report)
        self.assertFalse(any(s.startswith(('CREATE', 'INSERT', 'DROP')) for s in client.calls))
        self.assertEqual(report['fixtureCleanup'], 'NOT_CREATED')

    def test_unknown_artifact_or_projection_fails_before_mutation(self):
        for paths, expression in ((dict(project=compiled_artifact()), CLOSE),
                                  (dict(project=compiled_artifact(), reference=compiled_artifact()), 'malicious SQL')):
            client = FakeClient(ma.cases()[2])
            with self.assertRaises(ValueError):
                ma.run_native(client, DATABASE, [ma.cases()[2]], [paths], ma.vectors(), expression, dict(checks=[]))
            self.assertEqual(client.calls, [])

    def test_cleanup_and_changed_registry_cannot_be_reported_success(self):
        for options in (dict(fail_drop=True), dict(changed_registry=True)):
            client, report = FakeClient(ma.cases()[2], **options), dict(checks=[])
            with self.assertRaises(AssertionError):
                self.run_mock(client, report)
            self.assertTrue(report['cleanupErrors'])
            if options.get('fail_drop'):
                self.assertEqual(report['fixtureCleanup'], 'FAILED')
            else:
                self.assertFalse(report['formalRegistryUnchanged'])

    def test_explicit_execution_required_and_fresh_output_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory)
            with patch.object(ma, 'WslDoris', side_effect=AssertionError('must not start Doris')):
                with self.assertRaises(SystemExit):
                    ma.main(['--output-dir', str(existing)])
                with self.assertRaises(ValueError):
                    ma.main(['--output-dir', str(existing), '--execute'])


if __name__ == '__main__':
    unittest.main()
