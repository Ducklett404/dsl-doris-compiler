import unittest
import json
from pathlib import Path

from prepare_competition_corpus import (
    FUNCTION_ARITY,
    classify_rows,
    dsl_identity,
    extract_indicators,
    parse_call_arguments,
    quoted_literal,
    split_for,
)


class CompetitionCorpusTest(unittest.TestCase):
    def test_function_arity_matches_contract(self):
        contract_path = Path(__file__).resolve().parents[1] / "docs" / "competition" / "dsl-contract-draft.v0.1.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(FUNCTION_ARITY, {name: len(slots) for name, slots in contract["functions"].items()})

    def test_dsl_identity_preserves_quoted_whitespace(self):
        self.assertEqual(
            dsl_identity(" indicator( '沪 深', '', '最新价', '', '', '', '' )  >  10 "),
            "indicator( '沪 深', '', '最新价', '', '', '', '' ) > 10",
        )

    def test_parser_keeps_nested_commas_inside_function_and_string(self):
        source = "indicator('', '', 'A,B', '', '', '', '')"
        arguments, end = parse_call_arguments(source, source.index("("))
        self.assertEqual(7, len(arguments))
        self.assertEqual("A,B", quoted_literal(arguments[2]))
        self.assertEqual(len(source), end)

    def test_quarantine_badcase_and_conflicting_labels(self):
        rows = [
            (2, "batch", "问题甲", "indicator('', '', '最新价', '', '', '', '') > 10", ""),
            (3, "batch", "问题甲", "indicator('', '', '最新价', '', '', '', '') > 20", ""),
            (4, "batch", "问题乙", "indicator('', '', '成交量', '', '', '', '') > 10", "评测badcase"),
            (5, "batch", "问题丙", "", ""),
            (6, "batch", "问题丁", "indicator('', '', '最新价', '', '', '', '') > 10", ""),
            (7, "batch", "问题丁", "indicator('', '', '最新价', '', '', '', '') > 10", ""),
        ]
        records = classify_rows(rows)
        self.assertEqual(["review", "review", "review", "excluded", "included", "excluded"],
                         [record["status"] for record in records])
        self.assertEqual("conflicting_dsl_for_query", records[0]["reason"])
        self.assertEqual("exact_duplicate", records[-1]["reason"])

    def test_split_is_stable_and_inventory_uses_included_only(self):
        rows = [
            (2, "batch", "问题甲", "cross_above('', '', '最新价', '5日均线', '', '', '') = True", ""),
            (3, "batch", "问题乙", "indicator('', '', '不应计入', '', '', '', '') = True", "badcase"),
        ]
        records = classify_rows(rows)
        self.assertEqual(split_for("问题甲"), records[0]["split"])
        indicators = {item["indicator"]: item for item in extract_indicators(records)}
        self.assertEqual({"最新价", "5日均线"}, set(indicators))
        self.assertEqual([2], indicators["最新价"]["source_rows"])


if __name__ == "__main__":
    unittest.main()
