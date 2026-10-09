"""Manually labelled rank, lookup, count and matrix integrity regression tests."""
import json
import unittest
from validate_project_sources import ROOT
from project_rank_reference import KEYS, cases, matrix_document, rank_mode, reference, security_key
from check_project_rank_combinations import fixture, at_date


def history(prices, net=None):
    return [dict(date=f'2026-04-{j + 1:02}', close=None if p is None else p * 10000,
                 open=10000, volume=100, net=None if net is None else net[j], ext=True)
            for j, p in enumerate(prices)]


def rank_case(direction='desc:rank', threshold=3, **extra):
    return dict(market='', calls=[dict(kind='rank', metric='close', direction=direction)], expr=('cmp', 0, '<=', threshold), **extra)


class RankLookupCountReferenceTest(unittest.TestCase):
    def setUp(self):
        self.source = dict(histories={('103', '000001'): history([3]), ('1', '000001'): history([3]),
            ('0', '000001'): history([5]), ('0', '000002'): history([None]), ('1', '000003'): history([1])}, names={})

    def test_rank_gap_is_not_dense_rank(self):
        self.assertEqual(reference(rank_case('desc:rank', 3), self.source)['rows'], [['0', '000001'], ['1', '000001'], ['103', '000001']])
        self.assertEqual(reference(rank_case('desc:rank', 4), self.source)['rows'][-1], ['1', '000003'])
        self.assertEqual(len(reference(rank_case('desc:dense_rank', 3), self.source)['rows']), 4)

    def test_row_number_tie_break_is_numeric_market_and_text_code(self):
        self.assertEqual(reference(rank_case('desc:row_number', 2), self.source)['rows'], [['0', '000001'], ['1', '000001']])
        self.assertEqual(sorted([('103', '000001'), ('1', '000001'), ('0', '000001')], key=security_key), [('0', '000001'), ('1', '000001'), ('103', '000001')])

    def test_default_direction_is_dense_and_NULL_excluded(self):
        self.assertEqual(rank_mode('desc'), ('desc', 'dense_rank'))
        self.assertEqual(reference(rank_case('desc', 3), self.source)['rows'], reference(rank_case('desc:dense_rank', 3), self.source)['rows'])
        self.assertEqual(reference(rank_case('asc', 3), self.source)['rows'][0], ['1', '000003'])
        self.assertEqual(len(reference(rank_case(), self.source)['inputs'][0]['missing']), 1)

    def test_invalid_rank_method_not_silently_defaulted(self):
        for direction in ('desc:other', 'down', 'asc:'):
            with self.assertRaises(ValueError):
                rank_mode(direction)

    def test_limit_minimum_does_not_skip_offset_rows(self):
        case = rank_case('desc:row_number', 10, limitMinimum=2, limit=3)
        self.assertEqual(reference(case, self.source)['rows'], [['0', '000001'], ['1', '000001'], ['103', '000001']])
        self.assertEqual(reference(rank_case(limit=0), self.source)['rows'], [])
        self.assertEqual(reference(rank_case(limit=-1), self.source)['rows'], reference(rank_case(), self.source)['rows'])

    def test_then_prefilter_ranks_candidates_but_discloses_all_inputs(self):
        case = dict(market='', calls=[dict(kind='field', metric='close'), dict(kind='rank', metric='close', direction='asc:row_number')],
                    pre=('cmp', 0, '>', 1), expr=('cmp', 1, '<=', 1))
        result = reference(case, self.source)
        self.assertEqual(result['rows'], [['1', '000001']])
        self.assertEqual(result['observed'], 5)
        self.assertEqual([len(i['missing']) for i in result['inputs']], [1, 1])

    def test_multi_rank_NULL_intersection_before_rank(self):
        self.source['histories'][('0', '000001')][0]['net'] = None
        for key, h in self.source['histories'].items():
            if key != ('0', '000001'):
                h[0]['net'] = 1
        case = dict(market='', calls=[dict(kind='rank', metric='close', direction='desc:row_number'), dict(kind='rank', metric='net', direction='asc:rank')],
                    expr=('and', ('cmp', 0, '<=', 1), ('cmp', 1, '<=', 5)))
        self.assertEqual(reference(case, self.source)['rows'], [['1', '000001']])

    def lookup(self, keyword, market=''):
        return reference(dict(market=market, calls=[dict(kind='field', metric='close'), dict(kind='query', keyword=keyword)], expr=('callcmp', 0, '>=', 1)), self.source)

    def test_leading_zero_lookup_does_not_coerce_text(self):
        self.assertEqual(self.lookup('1')['rows'], [])
        self.assertEqual(self.lookup('000001')['rows'], [['0', '000001']])

    def test_market_scopes_lookup_scalar_and_current_security(self):
        self.assertEqual(self.lookup('000001', '京')['rows'], [['103', '000001']])
        self.assertEqual(self.lookup('000001', '沪')['rows'], [['1', '000001']])
        self.assertEqual(self.lookup('000001', '深')['rows'], [['0', '000001']])

    def test_name_lookup_is_exact_current_name_and_wrong_market_missing(self):
        self.source['names'][('0', '000001')] = '目标深零一'
        self.assertEqual(self.lookup('目标深零一')['rows'], [['0', '000001']])
        self.assertEqual(self.lookup('目标深零一', '沪')['rows'], [])
        self.assertEqual(self.lookup('目标深')['rows'], [])

    def test_target_NULL_or_absent_causes_partial_inputs_not_false_data(self):
        for keyword in ('000002', 'missing'):
            result = self.lookup(keyword)
            self.assertEqual(result['rows'], [])
            self.assertEqual(result['coverageStatus'], 'PARTIAL_INPUTS')
            self.assertEqual(len(result['inputs'][1]['missing']), 5)

    def test_legal_negative_fund_hits_without_sentinel_coercion(self):
        call = dict(kind='count', metric='net', mode='CONS', countOp='>=', n=3, op='<', threshold=0)
        source = dict(histories={('1', '000001'): history([1, 1, 1], [-10, -20, -30])}, names={})
        result = reference(dict(market='', calls=[call], expr=('cmp', 0, '=', True)), source)
        self.assertEqual(result['rows'], [['1', '000001']])
        self.assertEqual([len(i['missing']) for i in result['inputs']], [0, 0, 0])

    def test_unknown_count_input_and_count_result_are_different(self):
        call = dict(kind='count', metric='net', mode='EXIST', countOp='=', n=3, op='<', threshold=0)
        source = dict(histories={('103', '000001'): history([1] * 20, [None] * 17 + [-1, -2, -3])}, names={})
        result = reference(dict(market='', calls=[call], expr=('cmp', 0, '=', True)), source)
        self.assertEqual(result['rows'], [['103', '000001']])
        self.assertEqual([len(i['missing']) for i in result['inputs']], [0, 0, 1])

    def test_exact_CONS_unknown_boundary_is_non_hit(self):
        call = dict(kind='count', metric='net', mode='CONS', countOp='=', n=3, op='<', threshold=0)
        source = dict(histories={('1', '000001'): history([1] * 4, [None, -1, -2, -3])}, names={})
        self.assertEqual(reference(dict(market='', calls=[call], expr=('cmp', 0, '=', True)), source)['rows'], [['1', '000001']])
        source['histories'][('1', '000001')][0]['net'] = -1
        self.assertEqual(reference(dict(market='', calls=[call], expr=('cmp', 0, '=', True)), source)['rows'], [])

    def test_insufficient_observations_produce_missing_result(self):
        for mode, op in [('CONS', '='), ('EXIST', '>=')]:
            call = dict(kind='count', metric='net', mode=mode, countOp=op, n=3, op='<', threshold=0)
            result = reference(dict(market='', calls=[call], expr=('cmp', 0, '=', True)), dict(histories={('1', '000001'): history([1] * 3, [-1] * 3)}, names={}))
            self.assertEqual(result['rows'], [])
            self.assertEqual([len(i['missing']) for i in result['inputs']], [0, 1, 1])

    def test_no_observations_and_market_exclusion_are_distinct(self):
        self.assertEqual(reference(rank_case(), dict(histories={}, names={}))['coverageStatus'], 'NO_OBSERVATIONS')
        case = rank_case('desc:row_number', 10); case['market'] = '^京'
        self.assertNotIn(['103', '000001'], reference(case, self.source)['rows'])

    def test_frozen_manifest_and_every_field_has_all_rank_modes(self):
        doc = json.loads((ROOT / 'config/acceptance/project-rank-matrix-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(doc, json.loads(json.dumps(matrix_document(), ensure_ascii=False)))
        suite = cases(); self.assertEqual(len(suite), 172)
        self.assertEqual(len({c['name'] for c in suite}), len(suite))
        for key in KEYS:
            methods = {rank_mode(c['calls'][0]['direction'])[1] for c in suite if c['name'].startswith('rank-' + key + '-')}
            self.assertEqual(methods, {'rank', 'dense_rank', 'row_number'})

    def test_fixture_has_raw_NULL_sentinel_negative_missing_extension_and_future(self):
        data = fixture(); source = at_date(data, '2026-04-14')
        self.assertEqual(len(data['histories']), 55)
        self.assertTrue(any(not h[-1]['ext'] for h in source['histories'].values()))
        self.assertTrue(any(r['rawNet'] == -999999 for h in data['histories'].values() for r in h))
        self.assertTrue(any(r['net'] is not None and r['net'] < 0 for h in data['histories'].values() for r in h))
        self.assertTrue(any(r[2] == '2026-04-15' for r in data['basic']))
        self.assertNotIn(('0', '000003'), source['histories'])

    def test_matrix_covers_multiple_dates_and_all_frozen_market_sets(self):
        suite = cases()
        self.assertTrue({'沪', '深', '京', '沪|深', '^京', '沪|深|京'}.issubset({c['market'] for c in suite}))
        self.assertTrue({'2006-01-04', '2018-08-20', '2026-04-13', '2026-04-14'}.issubset({c['date'] for c in suite}))

    def test_repeated_rank_AND_lookup_share_one_semantic_input(self):
        for kind in ('rank', 'query'):
            call = dict(kind='rank', metric='close', direction='desc:row_number') if kind == 'rank' else dict(kind='query', metric='close', keyword='missing')
            result = reference(dict(market='', calls=[call, dict(call)], expr=('or', ('cmp', 0, '<=', 3), ('cmp', 1, '>', 0))), self.source)
            self.assertEqual(len(result['inputs']), 1)

    def test_count_and_direct_metric_share_VALUE_but_count_roles_remain_separate(self):
        count = dict(kind='count', metric='net', mode='CONS', countOp='>=', n=3, op='<', threshold=0)
        result = reference(dict(market='', calls=[count, dict(kind='field', metric='net')], expr=('cmp', 0, '=', True)), self.source)
        self.assertEqual([i['function'] for i in result['inputs']], ['indicator', 'CONS', 'CONS（窗口输入）'])


if __name__ == '__main__':
    unittest.main()
