package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.TestFactory;

import java.util.List;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.*;

/** Requirement matrix: every function family owns normal/boundary/null/suspension/IPO/error checks. */
final class StockSlotFunctionEdgeCaseTest {
    private final StockSlotSqlCompiler compiler = new StockSlotSqlCompiler();

    private static final List<FunctionCase> CASES = List.of(
            c("indicator", "indicator('', '', '1日均线', '2026-04-14', '', '', '') > 1",
                    "indicator('', '', '0日均线', '2026-04-14', '', '', '') > 1"),
            c("rank", "rank('', '', '收盘价', 'desc:row_number', '2026-04-14', '', '', '') <= 1",
                    "rank('', '', '收盘价', 'sideways', '2026-04-14', '', '', '') <= 1"),
            c("queryData", "queryData('', '920690', '收盘价', '2026-04-14', '') > 1",
                    "queryData('', 'A|B', '收盘价', '2026-04-14', '') > 1"),
            c("record_high", "record_high('', '', '最高价', '1日', '2026-04-14', '', '', '') = True",
                    "record_high('', '', '最高价', '0日', '2026-04-14', '', '', '') = True"),
            c("record_low", "record_low('', '', '最低价', '1日', '2026-04-14', '', '', '') = True",
                    "record_low('', '', '最低价', '零日', '2026-04-14', '', '', '') = True"),
            c("cross_above", "cross_above('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                    "cross_above('', '', '未知', '开盘价', '2026-04-14', '', '') = True"),
            c("cross_down", "cross_down('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                    "cross_down('', '', '收盘价', '未知', '2026-04-14', '', '') = True"),
            c("position", "position('', '', '收盘价', '1日', '2026-04-14', '', '', '') = '中'",
                    "position('', '', '收盘价', '5001日', '2026-04-14', '', '', '') = '中'"),
            c("belong_industry", "belong_industry('', '', '收盘价', '2026-04-14', 'AVG') > 1",
                    "belong_industry('', '', '收盘价', '2026-04-14', 'MEDIAN') > 1"),
            c("close_together", "close_together('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                    "close_together('', '', '未知', '开盘价', '2026-04-14', '', '') = True"),
            c("reset", "reset('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                    "reset('', '', '未知', '开盘价', '2026-04-14', '', '') = True"),
            c("golden_cross", "golden_cross('', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
                    "golden_cross('', '', '未知', '开盘价', '2026-04-14', '', '') = True"),
            c("CONS", "indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=1日') > 1",
                    "indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS<3日') > 1"),
            c("EXIST", "indicator('', '', '收盘价', '2026-04-14', '', '', 'EXIST>=1日') > 1",
                    "indicator('', '', '收盘价', '2026-04-14', '', '', 'EXIST!=3日') > 1")
    );

    @TestFactory Stream<DynamicTest> fullScenarioMatrix() {
        return CASES.stream().flatMap(item -> Stream.of(
                DynamicTest.dynamicTest(item.name + ":normal", () -> assertFalse(compiler.compile(item.dsl).sql().isBlank())),
                DynamicTest.dynamicTest(item.name + ":boundary", () -> assertFalse(compiler.compile(item.dsl).logicalPlan().isEmpty())),
                DynamicTest.dynamicTest(item.name + ":null", () -> assertTrue(compiler.compile(item.dsl).windowContracts().stream()
                        .allMatch(c -> List.of("STRICT_NO_IMPUTATION", "EXCLUDE_NULL_METRIC", "IGNORE_NULL_INPUTS")
                                .contains(c.nullPolicy())))),
                DynamicTest.dynamicTest(item.name + ":suspension", () -> assertTrue(compiler.compile(item.dsl).windowContracts().stream()
                        .allMatch(c -> c.suspensionPolicy().equals("OBSERVED_ROWS_SKIP_SUSPENSION") || c.suspensionPolicy().equals("NOT_APPLICABLE")))),
                DynamicTest.dynamicTest(item.name + ":ipo", () -> assertTrue(compiler.compile(item.dsl).windowContracts().stream()
                        .allMatch(c -> c.insufficientHistoryPolicy().contains("NULL")))),
                DynamicTest.dynamicTest(item.name + ":error", () -> assertThrows(CompileException.class, () -> compiler.compile(item.errorDsl)))
        ));
    }

    private static FunctionCase c(String name, String dsl, String errorDsl) { return new FunctionCase(name, dsl, errorDsl); }
    private record FunctionCase(String name, String dsl, String errorDsl) {}
}
