package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

final class MarketDataSemanticsContractTest {
    @Test void semanticViewDerivesScalesAdjustedPricesNullsAndSentinels() throws Exception {
        String ddl = Files.readString(Path.of("data/doris/ddl/002_semantic_view.sql"));
        assertAll(
                () -> assertTrue(ddl.contains("b.quantRatio AS quanRatio")),
                () -> assertTrue(ddl.contains("CAST(b.closePx AS DOUBLE) / 10000.0 AS closePrice")),
                () -> assertTrue(ddl.contains("CAST(b.closePx AS DOUBLE) / 10000.0 * b.qfqMulti + b.qfqAdd AS closeQfq")),
                () -> assertTrue(ddl.contains("CAST(b.closePx AS DOUBLE) / 10000.0 * b.hfqMulti + b.hfqAdd AS closeHfq")),
                () -> assertTrue(ddl.contains("CASE WHEN b.volume IS NULL OR b.volume = 0 THEN NULL")),
                () -> assertTrue(ddl.contains("NULLIF(e.ZJLXMainNetTurInDays, -999999)")));

        var compiler = new StockSlotSqlCompiler();
        String adjusted = compiler.compile("indicator('', '', '前复权收盘价', '2026-04-14', '', '', '') > 1 "
                + "and indicator('', '', '后复权收盘价', '2026-04-14', '', '', '') > 1").sql();
        assertTrue(adjusted.contains("b.closeQfq"));
        assertTrue(adjusted.contains("b.closeHfq"));
        String sentinel = compiler.compile(
                "indicator('', '', '主力净流入', '2026-04-14', '', '', '') > 0").sql();
        assertTrue(sentinel.contains("NULLIF(e.ZJLXMainNetTur,-999999)"));
    }

    @Test void suspensionAndIpoFixtureProducesObservedRowAndFullWindowSemantics() throws Exception {
        List<String> rows = Files.readAllLines(Path.of("src/test/resources/window-fixtures/quotes.csv"));
        List<Double> aaa = rows.stream().skip(1).filter(line -> line.startsWith("AAA,"))
                .map(line -> Double.parseDouble(line.split(",")[2])).toList();
        List<Double> ipo = rows.stream().skip(1).filter(line -> line.startsWith("IPO,"))
                .map(line -> Double.parseDouble(line.split(",")[2])).toList();
        assertEquals(List.of(10.0, 11.0, 12.0, 13.0), aaa,
                "停牌日无记录，窗口只能按已观测交易行推进");
        assertEquals(12.0, aaa.subList(aaa.size() - 3, aaa.size()).stream().mapToDouble(Double::doubleValue).average().orElseThrow());
        assertEquals(1, ipo.size());
        assertTrue(ipo.size() < 3, "新股不足完整窗口时必须返回 NULL，而不是缩短窗口");

        var window = new StockSlotSqlCompiler().compile(
                "indicator('', '', '3日均线', '2026-04-14', '', '', '') > 1");
        assertTrue(window.sql().contains("COUNT(`v1`) OVER"));
        assertTrue(window.sql().contains("ROWS BETWEEN 2 PRECEDING AND CURRENT ROW"));
        assertTrue(window.windowContracts().stream().allMatch(c -> c.suspensionPolicy().equals("OBSERVED_ROWS_SKIP_SUSPENSION")));
        assertTrue(window.windowContracts().stream().allMatch(c -> c.insufficientHistoryPolicy().equals("NULL")));
    }
}
