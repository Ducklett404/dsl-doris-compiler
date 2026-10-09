"""Offline hand-oracle and lowering contracts; no Java or Doris is started.

Expected keys below are hand-labelled from raw integer units. The finite-scale
counterexample documents a limitation, rather than weakening the native oracle.
"""
import ast
from decimal import Decimal, localcontext, ROUND_HALF_UP
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import check_project_numeric_comparisons as numeric


ROOT = Path(__file__).resolve().parents[2]
OPERATORS = ('=', '!=', '>', '>=', '<', '<=')


def keys(indices):
    return [['1', f'{index:06}'] for index in indices]


class NumericComparisonOracleTest(unittest.TestCase):
    def test_seventeen_raw_vectors_have_unique_names_and_signed_bigint_inputs(self):
        vectors = numeric.vectors()
        self.assertEqual(len(vectors), 17)
        self.assertEqual([row[0] for row in vectors], [
            'equal-below-one', 'equal-one', 'equal-above-one', 'below', 'above',
            'negative-equal', 'large-equal', 'large-below', 'large-above',
            'huge-volume-equal', 'huge-volume-below', 'huge-volume-above',
            'tiny-positive', 'null-turnover', 'null-volume', 'zero-volume',
            'null-close',
        ])
        self.assertEqual(len({row[0] for row in vectors}), 17)
        for name, *values in vectors:
            for value in values:
                with self.subTest(name=name, value=value):
                    if value is not None:
                        self.assertIs(type(value), int)
                        self.assertGreaterEqual(value, -(2 ** 63))
                        self.assertLess(value, 2 ** 63)

    def test_all_six_operators_match_hand_labelled_native_vector_keys(self):
        # Equality: 1/2/3, signed 6, large 7, and huge-volume 10.
        # Strictly below: 4/8/11. Strictly above: 5/9/12/13.
        selected = {
            '=': [1, 2, 3, 6, 7, 10],
            '!=': [4, 5, 8, 9, 11, 12, 13],
            '>': [5, 9, 12, 13],
            '>=': [1, 2, 3, 5, 6, 7, 9, 10, 12, 13],
            '<': [4, 8, 11],
            '<=': [1, 2, 3, 4, 6, 7, 8, 10, 11],
        }
        for operator, indices in selected.items():
            with self.subTest(operator=operator):
                self.assertEqual(numeric.expected(operator), keys(indices))

    def test_negative_adjacent_values_and_negative_volume_preserve_order(self):
        vectors = [
            ('negative-below', -10000, 100, -9999),
            ('negative-equal', -9999, 100, -9999),
            ('negative-above', -9998, 100, -9999),
            ('negative-volume-below', 10000, -100, -9999),
            ('negative-volume-equal', 9999, -100, -9999),
            ('negative-volume-above', 9998, -100, -9999),
        ]
        selected = {'=': [2, 5], '!=': [1, 3, 4, 6], '>': [3, 6],
                    '>=': [2, 3, 5, 6], '<': [1, 4], '<=': [1, 2, 4, 5]}
        with patch.object(numeric, 'vectors', return_value=vectors):
            for operator, indices in selected.items():
                with self.subTest(operator=operator):
                    self.assertEqual(numeric.expected(operator), keys(indices))

    def test_bigint_adjacent_values_are_not_collapsed_at_double_integer_limit(self):
        vectors = numeric.vectors()[6:9]
        self.assertEqual([row[1] for row in vectors],
                         [9007199254740993, 9007199254740992, 9007199254740994])
        self.assertEqual([100 * amount - close * volume
                          for _, amount, volume, close in vectors], [0, -100, 100])
        # Both source integers become the same DOUBLE; the oracle must not.
        self.assertEqual(float(vectors[0][1]), float(vectors[1][1]))
        with patch.object(numeric, 'vectors', return_value=vectors):
            self.assertEqual(numeric.expected('='), keys([1]))
            self.assertEqual(numeric.expected('<'), keys([2]))
            self.assertEqual(numeric.expected('>'), keys([3]))

    def test_huge_volume_one_cent_neighbors_have_independent_integer_deltas(self):
        vectors = numeric.vectors()[9:12]
        self.assertEqual([row[1] for row in vectors],
                         [92233720368547700, 92233720368547699, 92233720368547701])
        self.assertEqual([row[2] for row in vectors], [9223372036854770000] * 3)
        self.assertEqual([row[3] for row in vectors], [1] * 3)
        # avg = amount/(100*volume), close = closePx/10000. Multiplying
        # positive denominators gives 100*amount versus closePx*volume.
        self.assertEqual([100 * amount - close * volume
                          for _, amount, volume, close in vectors], [0, -100, 100])
        with patch.object(numeric, 'vectors', return_value=vectors):
            self.assertEqual(numeric.expected('='), keys([1]))
            self.assertEqual(numeric.expected('<'), keys([2]))
            self.assertEqual(numeric.expected('>'), keys([3]))

    def test_one_cent_at_maximum_volume_is_positive_and_survives_21_places(self):
        vector = numeric.vectors()[12]
        self.assertEqual(vector, ('tiny-positive', 1, 9223372036854775807, 0))
        with localcontext() as context:
            context.prec = 80
            average = Decimal(1) / 100 / Decimal(9223372036854775807)
            self.assertGreater(average, Decimal('1e-21'))
            self.assertLess(average, Decimal('2e-21'))
            self.assertEqual(average.quantize(Decimal('1e-21'), rounding=ROUND_HALF_UP),
                             Decimal('1e-21'))
        with patch.object(numeric, 'vectors', return_value=[vector]):
            self.assertEqual(numeric.expected('>'), keys([1]))
            self.assertEqual(numeric.expected('='), [])

    def test_null_operands_and_zero_denominator_never_match_even_not_equal(self):
        for vector in numeric.vectors()[13:]:
            with patch.object(numeric, 'vectors', return_value=[vector]):
                for operator in OPERATORS:
                    with self.subTest(vector=vector[0], operator=operator):
                        self.assertEqual(numeric.expected(operator), [])

    def test_oracle_uses_no_sql_view_registry_or_database_for_expected_keys(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('File oracle')), \
                patch.object(numeric, 'compiled_paths', side_effect=AssertionError('SQL oracle')), \
                patch.object(numeric, 'WslDoris', side_effect=AssertionError('Database oracle')):
            self.assertEqual(numeric.expected('='), keys([1, 2, 3, 6, 7, 10]))

    def test_finite_21_place_domain_does_not_claim_infinite_rational_precision(self):
        vector = ('finite-scale-counterexample', 92233720368547758,
                  9223372036854775801, 1)
        _, amount, volume, close = vector
        # An exact integer cross-product proves strict order without rounding.
        self.assertEqual(100 * amount - close * volume, -1)
        with localcontext() as context:
            context.prec = 80
            average = Decimal(amount) / 100 / volume
            close_price = Decimal('0.0001')
            self.assertLess(average, close_price)
            self.assertLess(close_price - average, Decimal('1e-21') / 2)
            self.assertEqual(average.quantize(Decimal('1e-21'), rounding=ROUND_HALF_UP),
                             close_price)
        # Preserve the independent oracle's strict result. This vector is not
        # inserted into the native PASS suite or assigned a rounded expectation.
        with patch.object(numeric, 'vectors', return_value=[vector]):
            self.assertEqual(numeric.expected('<'), keys([1]))
            self.assertEqual(numeric.expected('>='), [])
            self.assertEqual(numeric.expected('='), [])


class NumericComparisonLoweringContractTest(unittest.TestCase):
    def test_plain_prices_enter_decimal_directly_from_all_six_raw_bigints(self):
        ddl = (ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8')
        sources = {'lastPrice': 'lastPx', 'preClosePrice': 'preClosePx',
                   'openPrice': 'openPx', 'highPrice': 'highPx',
                   'lowPrice': 'lowPx', 'closePrice': 'closePx'}
        for field, raw in sources.items():
            with self.subTest(field=field):
                projection = re.search(r'(?m)^\s*(.+?)\s+AS\s+' + field + r'\s*,?$', ddl)
                self.assertIsNotNone(projection)
                expression = projection.group(1)
                self.assertRegex(expression, r'CAST\(\s*b\.' + raw + r'\s+AS\s+DECIMAL\(')
                self.assertRegex(expression, r'/\s*10000\b')
                self.assertRegex(expression, r'AS\s+DECIMAL\(19,\s*4\)')
                self.assertNotIn('DOUBLE', expression.upper())

    def test_average_enters_decimal_before_normalization_and_preserves_null_guard(self):
        ddl = (ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8')
        projection = re.search(r'CASE\s+WHEN\s+b\.volume\b.*?END\s+AS\s+avgPx\b',
                               ddl, flags=re.DOTALL)
        self.assertIsNotNone(projection)
        expression = re.sub(r'--[^\n]*', '', projection.group(0))
        self.assertRegex(expression, r'b\.volume IS NULL OR b\.volume = 0 THEN NULL')
        self.assertRegex(expression, r'CAST\(\s*b\.turnover\s+AS\s+DECIMAL\(')
        self.assertRegex(expression, r'CAST\(\s*b\.volume\s+AS\s+DECIMAL\(')
        self.assertRegex(expression, r'/\s*100\s+AS\s+DECIMAL\(')
        self.assertRegex(expression, r'AS\s+DECIMAL\(38,\s*21\)')
        self.assertNotIn('DOUBLE', expression.upper())

    def test_native_suite_keeps_all_six_original_operators(self):
        source = Path(numeric.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'operators'
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(tuple(ast.literal_eval(assignments[0].value)), OPERATORS)
        suite = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == 'suite'
                             for target in node.targets))
        self.assertIsInstance(suite, ast.ListComp)
        self.assertEqual(suite.generators[0].target.id, 'op')
        dsl = next(keyword.value for keyword in suite.elt.keywords if keyword.arg == 'dsl')
        self.assertIsInstance(dsl, ast.BinOp)
        self.assertEqual(dsl.left.right.id, 'op')

    def test_java_normal_comparisons_render_original_operator_without_epsilon(self):
        # Both renderers' ordinary path concatenates the parsed operator. Only
        # the DSL's separately specified ~= branch has approximate semantics.
        for filename, variable, ending in [
            ('StockSlotSqlCompiler.java', 'operator', 'private String renderRange'),
            ('StockSlotAdvancedSqlCompiler.java', 'op', 'private String renderRange'),
        ]:
            with self.subTest(renderer=filename):
                source = (ROOT / 'src/main/java/com/acme/dorisdsl/stockslot' /
                          filename).read_text(encoding='utf-8')
                starting = ('private String renderBinary' if variable == 'operator'
                            else 'private String renderPlain')
                body = source.split(starting, 1)[1].split(ending, 1)[0]
                self.assertEqual(set(re.findall(variable + r'\.equals\("([^"]+)"\)', body)),
                                 {'THEN', 'BETWEEN', '~='})
                ordinary = ('"(" + render(binary.left()) + " " + ' + variable +
                            ' + " " + render(binary.right()) + ")";')
                self.assertIn(ordinary, re.sub(r'\s+', ' ', body))


if __name__ == '__main__':
    unittest.main()
