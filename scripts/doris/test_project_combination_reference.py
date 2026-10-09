"""Hand-computed securities, exact unit boundaries and SQL three-valued logic."""
import json
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
import tempfile
import unittest

from check_official_field_acceptance import RAW_COLUMNS
from project_combination_reference import cases, fixture, reference, source_on
from project_field_reference import observation
from project_matrix_reference import value


def row(day='2026-04-14', extension=True, **changes):
    raw = dict.fromkeys(RAW_COLUMNS, 10000)
    raw.update(closePx=10000, lastPx=10000, preClosePx=10000, volume=100,
        turnover=10000, totalShare=1000000, listedShare=500000,
        qfqMulti=2, qfqAdd=3, hfqMulti=3, hfqAdd=-2, net=0)
    raw.update(changes)
    if not extension:
        raw['net'] = None
    return observation(day, raw, extension)


def case(calls, expr, market=''):
    return dict(name='hand', calls=calls, expr=expr, market=market)


class CombinationReferenceTest(unittest.TestCase):
    def test_frozen_inventory_and_percent_literal_normalization(self):
        suite = cases()
        self.assertEqual(len(suite), 79)
        self.assertEqual(len({c['name'] for c in suite}), 79)
        self.assertEqual(sum('%' in c['dsl'] for c in suite), 9)
        self.assertTrue({'average', 'qfq', 'hfq', 'turn', 'cap', 'listedCap', 'net'} <=
            {call.get('metric') for c in suite for call in c['calls']})
        self.assertTrue(any(len({c.get('n') for c in entry['calls'] if c['kind'] == 'ma'}) == 3 for entry in suite))

    def test_exact_field_threshold_and_both_raw_integer_sides(self):
        histories = {('1', f'{i:06}'): [row(closePx=10000 + side, lastPx=10000 + side,
            turnover=10000 + side, turnRatio=10000 + side, net=side)]
            for i, side in enumerate((-1, 0, 1), 1)}
        source = dict(histories=histories, names={})
        for metric, threshold in [('average', 1), ('qfq', 5), ('hfq', 1),
                ('turn', 1), ('cap', 1000000), ('listedCap', 500000), ('net', 0)]:
            for operator, selected in [('=', [2]), ('<', [1]), ('>', [3]), ('<=', [1, 2]), ('>=', [2, 3])]:
                expected = [['1', f'{i:06}'] for i in selected]
                actual = reference(case([dict(kind='field', metric=metric)], ('cmp', 0, operator, threshold)), source)
                self.assertEqual(actual['rows'], expected, (metric, operator))

    def test_json_decimal_literal_is_decimal_not_binary_float(self):
        source = dict(histories={('1', '000001'): [row(turnRatio=1)]}, names={})
        actual = reference(case([dict(kind='field', metric='turn')], ['cmp', 0, '=', 0.0001]), source)
        self.assertEqual(actual['rows'], [['1', '000001']])

    def test_percent_point_and_currency_and_share_units(self):
        source = dict(histories={('0', '000001'): [row(turnRatio=10000, volume=100)]}, names={})
        calls = [dict(kind='field', metric=m) for m in ('turn', 'cap', 'volume')]
        expr = ('and', ('cmp', 0, '=', 1), ('and', ('cmp', 1, '=', 1000000), ('cmp', 2, '=', 100)))
        self.assertEqual(reference(case(calls, expr), source)['rows'], [['0', '000001']])

    def test_or_true_preserves_security_with_missing_funds_and_discloses_missing(self):
        source = dict(histories={('1', '000001'): [row(extension=False)], ('1', '000002'): [row(net=-999999)]}, names={})
        calls = [dict(kind='field', metric='net'), dict(kind='field', metric='close')]
        expected = reference(case(calls, ('or', ('cmp', 0, '>', 0), ('cmp', 1, '=', 1))), source)
        self.assertEqual(expected['rows'], [['1', '000001'], ['1', '000002']])
        self.assertEqual(expected['missingExtension'], {('1', '000001')})
        self.assertEqual(expected['inputs'][0]['missing'], {('1', '000001'), ('1', '000002')})
        self.assertEqual(expected['coverageStatus'], 'PARTIAL_INPUTS')

    def test_and_unknown_cannot_be_a_match_but_legal_negative_funds_can(self):
        source = dict(histories={('1', '000001'): [row(net=-5)], ('1', '000002'): [row(extension=False)]}, names={})
        calls = [dict(kind='field', metric='net'), dict(kind='field', metric='close')]
        self.assertEqual(reference(case(calls, ('and', ('cmp', 0, '<', 0), ('cmp', 1, '=', 1))), source)['rows'], [['1', '000001']])

    def test_multiple_windows_use_observations_across_suspension_not_calendar_days(self):
        source = dict(histories={('1', '000001'): [row(day=day, closePx=p * 10000) for day, p in
            [('2006-01-04', 1), ('2018-08-20', 3), ('2026-04-14', 2)]]}, names={})
        calls = [dict(kind='ma', n=3), dict(kind='rsi', n=2)]
        actual = reference(case(calls, ('and', ('cmp', 0, '=', 2), ('cmp', 1, '>', 50))), source)
        self.assertEqual(actual['rows'], [['1', '000001']])
        self.assertEqual(actual['coverageStatus'], 'COMPLETE_QUERY_INPUTS')

    def test_new_security_short_window_is_unknown_and_all_dependencies_are_reported(self):
        source = dict(histories={('1', '000001'): [row()]}, names={})
        calls = [dict(kind='ma', n=3), dict(kind='ma', n=20), dict(kind='rsi', n=5)]
        actual = reference(case(calls, ('or', ('cmp', 0, '>', 0), ('or', ('cmp', 1, '>', 0), ('cmp', 2, '>', 0)))), source)
        self.assertEqual(actual['rows'], [])
        self.assertEqual([i['missing'] for i in actual['inputs']], [{('1', '000001')}] * 3)

    def test_zero_average_denominator_remains_unknown_in_arithmetic(self):
        source = dict(histories={('1', '000001'): [row(volume=0)]}, names={})
        calls = [dict(kind='field', metric='average'), dict(kind='field', metric='close')]
        self.assertEqual(reference(case(calls, ('sumcmp', 0, 1, 0)), source)['rows'], [])

    def test_fixture_contains_raw_sides_missing_operands_sentinel_sparse_and_future(self):
        data = fixture()
        self.assertEqual(len(data['histories']), 66)
        self.assertTrue({(str((0, 1, 103)[i % 3]), f'{i + 1:06}')
            for i in range(63)} <= set(data['histories']))
        self.assertEqual({data['histories'][('1', f'{i:06}')][-1]['operands']['turnRatio'] for i in (2, 5, 8)}, {9999, 10000, 10001})
        self.assertTrue(any(r['rawNet'] == -999999 for h in data['histories'].values() for r in h))
        self.assertTrue(any(not r['ext'] for h in data['histories'].values() for r in h))
        observed = source_on(data, '2026-04-14')['histories']
        self.assertNotIn(('103', '000063'), observed)
        self.assertTrue(all(h[-1]['date'] == '2026-04-14' for h in observed.values()))
        self.assertTrue(all(r['date'] <= '2026-04-14' for h in observed.values() for r in h))
        self.assertEqual(source_on(data, '2026-04-12')['histories'], {})

    def test_official_ma_boundary_fixture_preserves_verified_raw_values_only(self):
        data = fixture()
        key = ('1', '900924')
        history = data['histories'][key]
        self.assertEqual(len(history), 20)
        self.assertEqual((history[0]['date'], history[-1]['date']),
            ('2026-03-17', '2026-04-14'))
        self.assertEqual([sum(r['operands']['closePx'] for r in history[-n:])
            for n in (3, 5, 20)], [10610, 17680, 70500])
        self.assertTrue(all(not r['ext'] and r['rawNet'] is None for r in history))
        self.assertTrue(all(r['operands'][column] is None for r in history
            for column in RAW_COLUMNS if column != 'closePx'))
        self.assertFalse(any(str(m) == key[0] and code == key[1]
            for m, code, *_ in data['extensionRows']))
        source_rows = [r for r in data['sourceRows'] if (str(r[0]), r[1]) == key]
        self.assertEqual(len(source_rows), 21)
        self.assertEqual(len({r[:3] for r in data['sourceRows']}), len(data['sourceRows']))
        self.assertEqual(source_rows[:-1], [(1, '900924', r['date'],
            *(r['operands'][column] for column in RAW_COLUMNS)) for r in history])
        self.assertEqual(source_rows[-1][2], '2026-04-15')
        self.assertEqual(source_rows[-1][3 + RAW_COLUMNS.index('closePx')], 999999)
        self.assertEqual(source_on(data, '2026-04-14')['histories'][key], history)

    def test_exact_ma_boundary_is_not_quantized_before_strict_comparison(self):
        history = fixture()['histories'][('1', '900924')]
        ma3, ma5, ma20 = [value(dict(kind='ma', n=n), history) for n in (3, 5, 20)]
        self.assertIsInstance(ma3, Decimal)
        self.assertEqual(ma3, Decimal('1.061') / 3)
        self.assertEqual(ma5, Decimal('0.3536'))
        self.assertEqual(ma20, Decimal('0.3525'))
        self.assertGreater(ma3, ma5)
        self.assertGreaterEqual(ma5, ma20)
        # Reproduce the erroneous four-place intermediate without changing the
        # mathematical reference.  It would erase the genuine strict inequality.
        self.assertEqual(ma3.quantize(Decimal('0.0001'), rounding=ROUND_DOWN), ma5)
        frozen = next(c for c in cases() if c['name'] == 'three-windows-and')
        actual = reference(frozen, dict(histories={('1', '900924'): history}, names={}))
        self.assertEqual(actual['rows'], [['1', '900924']])
        self.assertEqual(actual['coverageStatus'], 'COMPLETE_QUERY_INPUTS')

    def test_exact_ma_equality_does_not_pass_a_strict_comparison(self):
        history = [row(day=r['date'], closePx=3536)
            for r in fixture()['histories'][('1', '900924')]]
        averages = [value(dict(kind='ma', n=n), history) for n in (3, 5, 20)]
        self.assertEqual(averages, [Decimal('0.3536')] * 3)
        calls = [dict(kind='ma', n=n) for n in (3, 5, 20)]
        source = dict(histories={('1', '000001'): history}, names={})
        self.assertEqual(reference(case(calls, ('and', ('callcmp', 0, '>', 1),
            ('callcmp', 1, '>=', 2))), source)['rows'], [])
        self.assertEqual(reference(case(calls, ('and', ('callcmp', 0, '=', 1),
            ('callcmp', 1, '>=', 2))), source)['rows'], [['1', '000001']])

    def test_exact_ma_boundary_null_and_short_windows_remain_unknown(self):
        history = fixture()['histories'][('1', '900924')]
        calls = [dict(kind='ma', n=n) for n in (3, 5, 20)]
        expr = ('and', ('callcmp', 0, '>', 1), ('callcmp', 1, '>=', 2))
        for label, changed, missing in (
                ('new-security-two-rows', history[-2:], [True, True, True]),
                ('nineteen-observations', history[-19:], [False, False, True]),
                ('current-null', history[:-1] + [row(closePx=None)], [True, True, True]),
                ('older-null-in-twenty-only', [row(day=history[0]['date'], closePx=None)]
                    + history[1:], [False, False, True])):
            with self.subTest(label=label):
                source = dict(histories={('1', '000001'): changed}, names={})
                actual = reference(case(calls, expr), source)
                self.assertEqual(actual['rows'], [])
                self.assertEqual([value(call, changed) is None for call in calls], missing)
                self.assertEqual([bool(i['missing']) for i in actual['inputs']], missing)
                self.assertEqual(actual['coverageStatus'], 'PARTIAL_INPUTS')

    def test_official_rsi_boundary_fixture_preserves_verified_raw_values_only(self):
        data = fixture()
        self.assertIn(('1', '900924'), data['histories'])
        for code, raw_sum, last_six in (
                ('000903', 513700, [25600, 26000, 25300, 25300, 25500, 25600]),
                ('300135', 795000, [38200, 38700, 37700, 38100, 38700, 38200])):
            with self.subTest(code=code):
                key = ('0', code)
                history = data['histories'][key]
                self.assertEqual(len(history), 20)
                self.assertEqual([r['date'] for r in history],
                    [r['date'] for r in data['histories'][('1', '900924')]])
                self.assertEqual(sum(r['operands']['closePx'] for r in history), raw_sum)
                self.assertEqual([r['operands']['closePx'] for r in history[-6:]], last_six)
                self.assertTrue(all(not r['ext'] and r['rawNet'] is None for r in history))
                self.assertTrue(all(r['operands'][column] is None for r in history
                    for column in RAW_COLUMNS if column != 'closePx'))
                self.assertFalse(any(str(m) == key[0] and c == key[1]
                    for m, c, *_ in data['extensionRows']))
                source_rows = [r for r in data['sourceRows'] if (str(r[0]), r[1]) == key]
                self.assertEqual(source_rows[:-1], [(0, code, r['date'],
                    *(r['operands'][column] for column in RAW_COLUMNS)) for r in history])
                self.assertEqual(len(source_rows), 21)
                self.assertEqual(source_rows[-1][2], '2026-04-15')
                self.assertEqual(source_rows[-1][3 + RAW_COLUMNS.index('closePx')], 999999)
                self.assertEqual(source_on(data, '2026-04-14')['histories'][key], history)
        self.assertEqual(len({r[:3] for r in data['sourceRows']}), len(data['sourceRows']))

    def test_exact_rsi_fifty_survives_double_cancellation_and_or(self):
        data = fixture()
        frozen = next(c for c in cases() if c['name'] == 'three-windows-or')
        histories = {key: data['histories'][key] for key in (('0', '000903'), ('0', '300135'))}
        for code, expected_total in (('000903', 700), ('300135', 1500)):
            with self.subTest(code=code):
                history = histories[('0', code)]
                closes = [r['operands']['closePx'] for r in history[-6:]]
                changes = [b - a for a, b in zip(closes, closes[1:])]
                gains = sum(max(d, 0) for d in changes)
                losses = sum(max(-d, 0) for d in changes)
                self.assertEqual((gains, losses), (expected_total, expected_total))
                rsi = value(dict(kind='rsi', n=5), history)
                self.assertIsInstance(rsi, Decimal)
                self.assertEqual(rsi, Decimal(50))
                self.assertLess(value(dict(kind='ma', n=3), history),
                    value(dict(kind='ma', n=20), history))
                float_gain = sum(float(Decimal(max(d, 0)) / 10000) for d in changes) / 5
                float_loss = sum(float(Decimal(max(-d, 0)) / 10000) for d in changes) / 5
                # Float summation may round below or exactly to 50 depending on
                # the Python runtime. The Decimal oracle and result assertions
                # remain exact on every supported runtime.
                self.assertAlmostEqual(100 - 100 / (1 + float_gain / float_loss),
                    50, delta=1e-12)
        actual = reference(frozen, dict(histories=histories, names={}))
        self.assertEqual(actual['rows'], [['0', '000903'], ['0', '300135']])
        self.assertEqual(actual['coverageStatus'], 'COMPLETE_QUERY_INPUTS')

    def test_exact_rsi_fifty_and_adjacent_raw_integer_sides(self):
        base = fixture()['histories'][('0', '000903')]
        histories = {}
        for i, side in enumerate((-1, 0, 1), 1):
            raw = dict(base[-1]['operands'])
            raw['closePx'] += side
            history = base[:-1] + [observation(base[-1]['date'], raw, extension=False)]
            histories[('0', f'{i:06}')] = history
            expected = Decimal(100 * (700 + side)) / (1400 + side)
            self.assertEqual(value(dict(kind='rsi', n=5), history), expected)
        source = dict(histories=histories, names={})
        for operator, selected in (('<', [1]), ('=', [2]), ('>', [3]), ('>=', [2, 3]), ('<=', [1, 2])):
            with self.subTest(operator=operator):
                actual = reference(case([dict(kind='rsi', n=5)], ('cmp', 0, operator, 50)), source)
                self.assertEqual(actual['rows'], [['0', f'{i:06}'] for i in selected])
                self.assertEqual(actual['coverageStatus'], 'COMPLETE_QUERY_INPUTS')

    def test_rsi_zero_loss_current_null_predecessor_null_and_short_window_are_unknown(self):
        base = fixture()['histories'][('0', '000903')]
        last_dates = [r['date'] for r in base[-6:]]
        for label, history in (
                ('only-gains', [row(day=day, closePx=10000 + 100 * i)
                    for i, day in enumerate(last_dates)]),
                ('flat-zero-gains-and-losses', [row(day=day, closePx=10000) for day in last_dates]),
                ('five-observations-not-six', base[-5:]),
                ('current-null', base[:-1] + [row(closePx=None)]),
                ('first-predecessor-null', base[:-6] + [row(day=base[-6]['date'], closePx=None)]
                    + base[-5:])):
            with self.subTest(label=label):
                self.assertIsNone(value(dict(kind='rsi', n=5), history))
                actual = reference(case([dict(kind='rsi', n=5)], ('cmp', 0, '>=', 50)),
                    dict(histories={('0', '000001'): history}, names={}))
                self.assertEqual(actual['rows'], [])
                self.assertEqual(actual['inputs'][0]['missing'], {('0', '000001')})
                self.assertEqual(actual['coverageStatus'], 'PARTIAL_INPUTS')

    def test_frozen_matrix_rejects_duplicate_names_and_unknown_scope(self):
        suite = cases()
        for changed in ([suite[0], suite[0]], [dict(suite[0], calls=[dict(kind='new_window', n=3)])],
                [dict(suite[0], expr=['cmp', 999, '=', 1])],
                [dict(suite[0], expr=['sql_fragment', 0, '=', 1])]):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'matrix.json'
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding='utf-8')
                with self.assertRaises(ValueError):
                    cases(path)


if __name__ == '__main__':
    unittest.main()
