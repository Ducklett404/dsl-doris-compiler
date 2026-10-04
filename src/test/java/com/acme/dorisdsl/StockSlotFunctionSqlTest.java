package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotFunctionSqlTest {
    private final StockSlotSqlCompiler compiler = new StockSlotSqlCompiler();

    @Test void indicatorSupportsStrictMovingAverageRsiAndRangeAggregate() {
        var ma = compile("indicator('', '', '5日均线', '2026-04-14', '', '', '') > 10");
        assertSql(ma.sql(), "AVG(`v1`) OVER", "COUNT(`v1`) OVER", "ROWS BETWEEN 4 PRECEDING");
        assertContract(ma, "indicator:MA", 5);

        var rsi = compile("indicator('', '', 'RSI(14)', '2026-04-14', '', '', '') > 50");
        assertSql(rsi.sql(), "LAG(`v1`)", "GREATEST(price_delta,0)", "ROWS BETWEEN 13 PRECEDING");
        assertContract(rsi, "indicator:RSI", 14);

        var avg = compile("indicator('', '', '收盘价', '2026-04-14近5日', '', 'AVG', '') > 10");
        assertSql(avg.sql(), "AVG(`v1`) OVER", "COUNT(`v1`) OVER");
    }

    @Test void exactSnapshotMa60UsesFrozenFeatureWhileOtherWindowsFallBackSafely() {
        var accelerated = compile("indicator('沪', '', '60日均线', '2026-04-14', '', '', '') > 1 limit 0,100");
        assertSql(accelerated.sql(), "FROM newzl.stock_daily_features_v2 pf", "pf.ma60 AS `v1`");
        assertFalse(accelerated.sql().contains("v_hsj_stock_hq_basic"));
        assertTrue(accelerated.logicalPlan().stream().anyMatch(node -> node.kind().equals("FeatureScan")));

        var fallback = compile("indicator('沪', '', '5日均线', '2026-04-14', '', '', '') > 1");
        assertSql(fallback.sql(), "v_hsj_stock_hq_basic", "AVG(`v1`) OVER");
        assertFalse(fallback.sql().contains("stock_daily_features_v2"));

        var mixed=compile("indicator('沪', '', '60日均线', '2026-04-14', '', '', '') > "
                + "indicator('沪', '', '收盘价', '2026-04-14', '', '', '')");
        assertSql(mixed.sql(),"v_hsj_stock_hq_basic","AVG(`v1`) OVER","COUNT(`v1`) OVER");
        assertFalse(mixed.sql().contains("stock_daily_features_v2"));
    }

    @Test void rankSupportsAllThreeMethodsIndustryPartitionAndThenPrefilter() {
        for (String method : List.of("rank", "dense_rank", "row_number")) {
            var artifact = compile("indicator('', '行业', '成交量', '2026-04-14', '', '', '') > 0 then "
                    + "rank('', '行业', '收盘价', 'desc:" + method + "', '2026-04-14', '', '', '') <= 3");
            assertSql(artifact.sql(), method.toUpperCase() + "() OVER (PARTITION BY hyBlkRefName",
                    "prefiltered AS", "FROM prefiltered");
        }
    }

    @Test void queryDataUsesExactCodeOrNameAndCanParticipateInArithmetic() {
        var artifact = compile("indicator('', '', '收盘价', '2026-04-14', '', '', '') > "
                + "queryData('', '600000', '收盘价', '2026-04-14', '') * 1.1");
        assertSql(artifact.sql(), "LEFT JOIN newzl.hsj_stock_code_info", "tgtcode=? OR name=?",
                "MAX(CASE WHEN");
        assertTrue(artifact.bindings().contains("600000"));
    }

    @Test void recordHighLowAndPositionHaveStrictFullWindowSemantics() {
        var high = compile("record_high('', '', '最高价', '20日', '2026-04-14', '', '', '') = True");
        assertSql(high.sql(), "COUNT(`v1`) OVER", "MAX(`v1`) OVER", "ELSE NULL END");
        assertContract(high, "record_high", 20);

        var low = compile("record_low('', '', '最低价', '历史', '2026-04-14', '', '', '') = True");
        assertSql(low.sql(), "historical_extrema AS", "MIN(`v1`)", "GROUP BY mktcode,tgtcode");
        var reference = compiler.compile("record_low('', '', '最低价', '历史', '2026-04-14', '', '', '') = True",
                StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
        assertSql(reference.sql(), "UNBOUNDED PRECEDING", "MIN(`v1`) OVER");
        assertEquals(reference.bindings(), low.bindings());

        var position = compile("position('', '', '收盘价', '60日', '2026-04-14', '', '', '') = '高'");
        assertSql(position.sql(), "THEN '低'", "THEN '高'", "ELSE '中'");
    }

    @Test void historicalAggregateKeepsPointInTimeAndCompositeKeys() {
        var artifact = compile("record_high('', '', '收盘价', '历史', '2026-04-14', '', '', '') = True and "
                + "record_low('', '', '最低价', '历史', '2026-04-14', '', '', '') = False");
        assertSql(artifact.sql(), "b.bizdate <= ?", "b.bizdate = ?", "GROUP BY mktcode,tgtcode",
                "MAX(is_current) AS has_current", "MAX(CASE WHEN is_current=1 THEN `v1` END)",
                "WHERE has_current=1", "MAX(`v1`)", "MIN(`v2`)");
        assertFalse(artifact.sql().contains(" JOIN "));
        assertFalse(artifact.sql().contains(" OVER "));
        assertTrue(artifact.logicalPlan().stream().anyMatch(node -> node.kind().equals("HistoricalAggregate")));
        assertEquals(List.of(java.time.LocalDate.of(2026,4,14), java.time.LocalDate.of(2026,4,14), true, false), artifact.bindings());
    }

    @Test void historicalCountsMixedWindowsAndPositionRetainRowWiseEvaluation() {
        for (String dsl : List.of(
                "record_high('', '', '收盘价', '历史', '2026-04-14', '', '', 'CONS>=3日') = True",
                "record_low('', '', '收盘价', '历史', '2026-04-14', '', '', '') = True and indicator('', '', '5日均线', '2026-04-14', '', '', '') > 1",
                "position('', '', '收盘价', '历史', '2026-04-14', '', '', '') = '高'")) {
            var artifact = compile(dsl);
            assertFalse(artifact.sql().contains("historical_extrema AS"), dsl);
            assertSql(artifact.sql(), "UNBOUNDED PRECEDING");
        }
    }

    @Test void crossFunctionsUsePreviousObservedTradingRow() {
        for (String function : List.of("cross_above", "cross_down", "reset", "golden_cross")) {
            var artifact = compile(function + "('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True");
            assertSql(artifact.sql(), "LAG(`v1`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate)",
                    "LAG(`v2`) OVER", "ELSE NULL END");
            assertContract(artifact, function, 2);
        }
    }

    @Test void closeTogetherUsesDocumentedOnePercentRelativeDistance() {
        var artifact = compile("close_together('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True");
        assertSql(artifact.sql(), "ABS(`v1`-`v2`)/NULLIF(GREATEST", "<=0.01");
    }

    @Test void belongIndustryUsesRealIndustryColumnAndCrossSectionAggregate() {
        var artifact = compile("indicator('', '', '收盘价', '2026-04-14', '', '', '') > "
                + "belong_industry('', '', '收盘价', '2026-04-14', 'AVG')");
        assertSql(artifact.sql(), "c.hyBlkRefName", "AVG(`v1`) OVER (PARTITION BY hyBlkRefName,bizdate)");
        assertContract(artifact, "belong_industry:AVG", 1);
    }

    @Test void consAndExistBecomeExplicitOccurrenceWindows() {
        var cons = compile("indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') > 10");
        assertSql(cons.sql(), "predicates AS", "counted AS", "ROWS BETWEEN 2 PRECEDING", "`c1`");
        assertContract(cons, "CONS", 3);

        var exist = compile("indicator('', '', '成交量', '2026-04-14', '', '', 'EXIST>=3日') > 0");
        assertSql(exist.sql(), "ROWS BETWEEN 19 PRECEDING", ">=3");
        assertContract(exist, "EXIST", 20);
    }

    @Test void invalidAndUnmappedInputsFailBeforeSql() {
        assertCode("EXECUTION_WINDOW_RANGE", "record_high('', '', '最高价', '0日', '2026-04-14', '', '', '') = True");
        assertCode("EXECUTION_QUERY_TARGET", "queryData('', '浦发银行|平安银行', '收盘价', '2026-04-14', '') > 1");
        assertCode("EXECUTION_INDICATOR_UNSUPPORTED", "record_high('', '', '归母净利润', '20日', '2026-04-14', '', '', '') = True");
        assertCode("EXECUTION_SELECT_TYPE_UNSUPPORTED", "indicator('', '', '收盘价', '2026-04-14', 'ETF', '', '') > 1");
        assertCode("EXECUTION_COUNT_UNSUPPORTED", "indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS<3日') > 1");
    }

    @Test void everyWindowContractPinsNullSuspensionAndIpoPolicies() {
        List<String> dsls = List.of(
                "indicator('', '', '5日均线', '2026-04-14', '', '', '') > 1",
                "record_high('', '', '最高价', '5日', '2026-04-14', '', '', '') = True",
                "record_low('', '', '最低价', '5日', '2026-04-14', '', '', '') = True",
                "position('', '', '收盘价', '5日', '2026-04-14', '', '', '') = '中'",
                "cross_above('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                "cross_down('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                "close_together('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                "reset('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                "golden_cross('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                "indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') > 1");
        for (String dsl : dsls) for (var contract : compile(dsl).windowContracts()) {
            assertEquals(List.of("mktcode", "tgtcode"), contract.partitionKeys());
            assertEquals(List.of("bizdate"), contract.orderKeys());
            assertEquals("TRADING_DAY", contract.unit());
            assertEquals("OBSERVED_ROWS_SKIP_SUSPENSION", contract.suspensionPolicy());
            assertEquals("NULL", contract.insufficientHistoryPolicy());
            assertEquals("STRICT_NO_IMPUTATION", contract.nullPolicy());
        }
    }

    private com.acme.dorisdsl.stockslot.StockSlotSqlArtifact compile(String dsl) { return compiler.compile(dsl); }
    private void assertContract(com.acme.dorisdsl.stockslot.StockSlotSqlArtifact artifact, String function, int lookback) {
        assertTrue(artifact.windowContracts().stream().anyMatch(c -> c.function().equals(function) && c.lookback() == lookback));
    }
    private void assertSql(String sql, String... fragments) { for (String fragment : fragments) assertTrue(sql.contains(fragment), fragment + "\n" + sql); }
    private void assertCode(String code, String dsl) {
        assertEquals(code, assertThrows(CompileException.class, () -> compile(dsl)).code());
    }
}
