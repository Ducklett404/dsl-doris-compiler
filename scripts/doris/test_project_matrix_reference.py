"""Hand-computed reference boundaries, independent of the Doris compiler implementation."""
import unittest
from project_matrix_reference import value, sql_bool, reference, assess


def history(prices, dates=None):
    return [dict(date=(dates or ['2026-04-14']*len(prices))[i], close=None if p is None else p*10000,
                 open=10000, volume=100, ext=True, net=10) for i, p in enumerate(prices)]


class ReferenceTest(unittest.TestCase):
    def test_null_logic(self):
        self.assertEqual([sql_bool('and', False, None), sql_bool('or', True, None), sql_bool('not', None)], [False, True, None])
        self.assertIsNone(sql_bool('and', True, None)); self.assertIsNone(sql_bool('or', False, None))

    def test_inclusive_thirds(self):
        call = dict(kind='position', n=3)
        self.assertEqual(value(call, history([1, 4, 2])), '低')
        self.assertEqual(value(call, history([1, 4, 3])), '高')

    def test_flat_missing_short(self):
        for prices in [[2, 2, 2], [1, None, 3], [1, 3]]:
            self.assertIsNone(value(dict(kind='position', n=3), history(prices)))

    def test_observed_rows_across_suspension(self):
        self.assertEqual(value(dict(kind='ma', n=3), history([1, 2, 3], ['2026-01-04', '2026-02-01', '2026-04-14'])), 2)

    def test_count_null_predicate_unhit(self):
        call = dict(kind='count', metric='close', mode='CONS', countOp='=', n=3, op='>', threshold=1)
        self.assertTrue(value(call, history([None, 2, 3, 4])))
        self.assertFalse(value(call, history([2, 2, 3, 4])))
        self.assertIsNone(value(call, history([2, 3, 4])))

    def test_exist_horizon(self):
        call = dict(kind='count', metric='close', mode='EXIST', countOp='=', n=3, op='>', threshold=1)
        self.assertTrue(value(call, history([None]*17+[2, 3, 4])))
        self.assertIsNone(value(call, history([None]*16+[2, 3, 4])))

    def test_rsi_zero_loss(self):
        self.assertIsNone(value(dict(kind='rsi', n=2), history([1, 2, 3])))
        self.assertEqual(value(dict(kind='rsi', n=2), history([2, 1, 2])), 50)

    def test_counted_ma_needs_prices_before_count_horizon(self):
        call = dict(kind='count',base=dict(kind='ma',n=3),n=2,mode='CONS',countOp='=',op='>',threshold=1)
        self.assertTrue(value(call,history([0,0,3,3,3])))
        self.assertFalse(value(call,history([3,3,3,3,3])))
        self.assertIsNone(value(call,history([3,3])))

    def test_counted_rsi_and_unknown_diagnostic_are_separate(self):
        call = dict(kind='count',base=dict(kind='rsi',n=2),n=2,mode='CONS',countOp='=',op='>=',threshold=0)
        source=dict(histories={('1','000001'):history([None,3,1,2,1])},names={})
        result=reference(dict(market='',calls=[call],expr=('cmp',0,'=',True)),source)
        self.assertEqual(result['rows'],[['1','000001']])
        self.assertEqual([len(i['missing']) for i in result['inputs']],[0,0,1])

    def test_cross_and_zero_denominator(self):
        self.assertTrue(value(dict(kind='cross_above'), history([1, 2])))
        self.assertIsNone(value(dict(kind='cross_above'), history([None, 2])))
        zero = history([0]); zero[0]['open'] = 0
        self.assertIsNone(value(dict(kind='close_together'), zero))

    def test_rank_then_limit_and_precondition_coverage(self):
        source = dict(histories={('1', '000001'): history([3]), ('1', '000002'): history([3]), ('0', '000003'): history([None])}, names={})
        case = dict(market='', calls=[dict(kind='field', metric='close'), dict(kind='rank', direction='desc:row_number')],
            pre=('cmp', 0, '>', 1), expr=('cmp', 1, '<=', 2), limit=1)
        result = reference(case, source)
        self.assertEqual(result['rows'], [['1', '000001']]); self.assertEqual(result['observed'], 3)
        self.assertEqual([len(i['missing']) for i in result['inputs']], [1, 1])

    def test_missing_query_target(self):
        source = dict(histories={('1', '000001'): history([3])}, names={})
        result = reference(dict(market='', calls=[dict(kind='query', keyword='missing')], expr=('cmp', 0, '>', 0)), source)
        self.assertEqual(result['rows'], []); self.assertEqual(result['coverageStatus'], 'PARTIAL_INPUTS')

    def test_duplicate_labels_and_sample_flags(self):
        key = ('1', '000001')
        expected = dict(rows=[], observed=1, missingExtension=set(), sampleKeys=[key], coverageStatus='PARTIAL_INPUTS',
            inputs=[dict(function='position', indicator='收盘价', missing=set()), dict(function='position', indicator='收盘价', missing={key})])
        data = dict(rows=[], truncated=False, dataQuality=dict(observedSecurities=1, currentMissingExtensionRows=0,
            coverageStatus='PARTIAL_INPUTS', validationLevel='PROJECT_SCOPED', officialAcceptanceEligible=False,
            inputs=[dict(function='position', indicator='收盘价', unavailableSecurities=1), dict(function='position', indicator='收盘价', unavailableSecurities=0)],
            unavailableSamples=[['1', '000001', '0', '1', '0']]))
        self.assertTrue(all(assess(data, expected).values()))
        data['dataQuality']['unavailableSamples'][0][3] = '0'
        self.assertFalse(assess(data, expected)['inputsEqual'])


if __name__ == '__main__': unittest.main()
