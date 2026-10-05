"""Hand-computed field expectations; no SQL, view or registry used for the expected values."""
import unittest
from decimal import Decimal as D
from project_field_reference import observation,null_causes,KEYS,cases
from check_official_field_acceptance import RAW_COLUMNS

def row(**changes):
    raw=dict.fromkeys(RAW_COLUMNS,10000)
    raw.update(lastPx=20000,preClosePx=10000,closePx=30000,volume=4,turnover=1000,
        totalShare=100,listedShare=50,qfqMulti=2,qfqAdd=3,hfqMulti=3,hfqAdd=-2,net=-5)
    raw.update(changes)
    return observation('2026-04-14',raw)

class FieldReferenceTest(unittest.TestCase):
    def test_prices_amount_ratios_and_amplitude(self):
        actual=row()['normalized']
        self.assertEqual([actual[k] for k in ['last','previous','close','amount','quantity','turn','trueTurn','amplitude']],
            [D(2),D(1),D(3),D(10),D(1),D(1),D(1),D(1)])
    def test_market_caps_use_last_price_not_close(self):
        self.assertEqual([row()['normalized'][k] for k in ['cap','listedCap']],[D(200),D(100)])
    def test_rise_average_and_adjustments(self):
        self.assertEqual([row()['normalized'][k] for k in ['rise','average','qfq','hfq']],[D(100),D('2.5'),D(9),D(7)])
    def test_zero_divisors_and_missing_numerators_are_independent(self):
        r=row(volume=0,turnover=None,preClosePx=0,lastPx=None)
        self.assertEqual(null_causes(r,'average'),[('SOURCE_OPERAND_NULL','均价 / turnover'),('ZERO_DENOMINATOR','均价 / volume')])
        self.assertEqual(null_causes(r,'rise'),[('SOURCE_OPERAND_NULL','涨跌幅 / lastPx'),('ZERO_DENOMINATOR','涨跌幅 / preClosePx')])
    def test_all_missing_adjustment_operands(self):
        r=row(closePx=None,qfqMulti=None,qfqAdd=None)
        self.assertEqual([i[1] for i in null_causes(r,'qfq')],['前复权收盘价 / closePx','前复权收盘价 / qfqMulti','前复权收盘价 / qfqAdd'])
    def test_sentinel_does_not_swallow_legal_negatives(self):
        self.assertEqual(row(net=-5)['normalized']['net'],-5)
        self.assertIsNone(row(net=-999999)['normalized']['net'])
    def test_position_decimal_scale(self):
        r=row(turnover=1,volume=10000000000)
        self.assertEqual(r['positions']['average'],D('0.000000000001'))
        self.assertEqual(r['positions']['amplitude'],D('1.0000'))
    def test_inventory_matrix_windows_and_dates(self):
        suite=cases();self.assertEqual(len(KEYS),19);self.assertEqual(len(suite),94)
        self.assertEqual(len({c['name'] for c in suite}),94)
        self.assertEqual({c['calls'][0]['metric'] for c in suite if c['calls'][0]['kind']=='position'},set(KEYS))

if __name__=='__main__':unittest.main()
