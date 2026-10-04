"""Execute generated SQL with real bindings on portable boundary fixtures.

Uses SQLite only for the shared window/NULL SQL subset. Run Maven tests first;
this complements, and does not replace, integration tests against Doris.
"""
import datetime
import json
from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "target/review-regression-queries.json"
END = datetime.date(2026, 4, 14)


class GeneratedSqlRegressionTest(unittest.TestCase):
    def setUp(self):
        self.queries = json.loads(QUERIES.read_text(encoding="utf-8"))
        self.db = sqlite3.connect(":memory:")
        self.db.create_function("GREATEST", 2, lambda a, b: max(x for x in (a, b) if x is not None))
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS newzl")
        self.db.execute("ATTACH DATABASE ':memory:' AS market")
        self.db.executescript("""
            CREATE TABLE newzl.v_hsj_stock_hq_basic(
                mktcode INTEGER,tgtcode TEXT,bizdate TEXT,closePrice REAL);
            CREATE TABLE newzl.stock_daily_features_v2(
                mktcode INTEGER,tgtcode TEXT,bizdate TEXT,ma60 REAL);
            CREATE TABLE newzl.hsj_stock_code_info(
                mktcode INTEGER,tgtcode TEXT,name TEXT,hyBlkRefName TEXT);
            CREATE TABLE market.dwd_quote_daily(symbol TEXT,trade_date TEXT,close REAL);
        """)

    def rows(self, code, prices, market=1, skip=()):
        for i, price in enumerate(prices):
            if i not in skip:
                date = (END - datetime.timedelta(days=len(prices) - 1 - i)).isoformat()
                self.db.execute("INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?)",
                                (market, code, date, price))

    def query(self, name):
        artifact = self.queries[name]
        return self.db.execute(artifact["sql"], artifact["bindings"]).fetchall()

    def materialize(self):
        # Run the production INSERT without rewriting its window semantics.
        ddl = (ROOT / "data/doris/ddl/005_performance_features.sql").read_text(encoding="utf-8")
        insert = ddl[ddl.index("INSERT INTO stock_daily_features_v2"):ddl.index("ANALYZE TABLE")]
        self.db.executescript(insert.replace("INSERT INTO stock_daily_features_v2",
                                            "INSERT INTO newzl.stock_daily_features_v2", 1))

    def test_ma60_feature_and_reference_match_null_new_listing_and_suspension(self):
        self.rows("A", [2] * 61)
        null_prices = [2] * 61
        null_prices[20] = None
        self.rows("B", null_prices)
        self.rows("C", [2] * 10)
        self.rows("D", [2] * 62, skip=(20,))
        self.rows("E", [2] * 61, market=2)
        self.materialize()
        expected = [(1, "A"), (1, "D"), (2, "E")]
        for date in ("2026-04-13", "2026-04-14"):
            actual = self.query(f"ma_{date}_optimized")
            self.assertEqual(expected, actual)
            self.assertEqual(self.query(f"ma_{date}_reference"), actual)
        self.assertIsNone(self.db.execute(
            "SELECT ma60 FROM newzl.stock_daily_features_v2 WHERE tgtcode='B'").fetchone()[0])

    def test_between_uses_repeated_operand_bindings_in_both_paths(self):
        for code, price in (("A", 1), ("B", 2), ("C", 3), ("D", 4), ("E", 0)):
            self.rows(code, [price] * 5)
        for name in ("between_simple", "between_advanced"):
            self.assertEqual([(1, "A"), (1, "B"), (1, "C")], self.query(name))

    def test_missing_industry_never_forms_a_synthetic_industry(self):
        for code, price, industry in (("A", 2, None), ("B", 8, None), ("C", 2, "Tech"), ("D", 4, "Tech")):
            self.rows(code, [price])
            self.db.execute("INSERT INTO newzl.hsj_stock_code_info VALUES(1,?,?,?)", (code, code, industry))
        for name in ("industry", "industry_max"):
            self.assertEqual([(1, "C"), (1, "D")], self.query(name))
        self.db.execute("UPDATE newzl.hsj_stock_code_info SET hyBlkRefName=NULL")
        self.assertEqual([], self.query("industry"))

    def test_boolean_count_checks_all_days_instead_of_only_last_day(self):
        self.rows("A", [1, 2, 3, 4, 5])
        self.rows("B", [1, 4, 3, 2, 5])
        self.rows("C", [1, 2, None, 4, 5])
        self.rows("D", [1, 2, 3])
        self.assertEqual([(1, "A")], self.query("count_boolean"))

    def test_screen_null_retains_the_underlying_column(self):
        self.db.executemany("INSERT INTO market.dwd_quote_daily VALUES(?,?,?)",
                            [("A", "2026-08-07", None), ("B", "2026-08-07", 2), ("C", "2026-08-06", None)])
        self.assertEqual([("A", "2026-08-07")], self.query("screen_null"))

    def test_rsi_executes_and_handles_losses_nulls_and_insufficient_history(self):
        self.rows("A", [1, 2, 1, 2, 1])  # Last three changes: -1,+1,-1 => 33.33
        self.rows("B", [1, 2, 1, 2, 3])  # Last three changes: -1,+1,+1 => 66.67
        self.rows("C", [2, 2, 2, 2, 2])  # Zero loss follows the frozen NULL policy.
        self.rows("D", [1, 2, None, 2, 3])
        self.rows("E", [2, 3])
        self.assertEqual([(1, "B")], self.query("rsi"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
