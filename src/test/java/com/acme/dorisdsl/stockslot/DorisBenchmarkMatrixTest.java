package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

final class DorisBenchmarkMatrixTest {
    @Test void everyMatrixDslCompilesForReferenceAndOptimizedPaths() throws Exception {
        var definition = JsonSupport.MAPPER.readValue(Path.of("benchmarks/doris-matrix-v1.json").toFile(),
                DorisBenchmarkMatrixDefinition.class);
        assertEquals(12, definition.cases().size());
        var history = definition.cases().stream().filter(x -> x.category().equals("LONG_RANGE"))
                .findFirst().orElseThrow();
        assertTrue(history.dsl().contains("'历史'"));
        var manifest = JsonSupport.MAPPER.readTree(
                Path.of("data/doris/snapshots/stock-20060104-20260414-v1/manifest.json").toFile());
        assertEquals("2006-01-04", manifest.at("/files/hsj_stock_hq_basic/dateMin").asText());
        assertEquals("2026-04-14", manifest.at("/files/hsj_stock_hq_basic/dateMax").asText());
        var compiler = new StockSlotSqlCompiler();
        for (var item : definition.cases()) {
            var reference = compiler.compile(item.dsl(), StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
            var optimized = compiler.compile(item.dsl(), StockSlotSqlCompiler.AccessPathMode.OPTIMIZED);
            assertEquals(reference.bindings(), optimized.bindings(), item.id());
            assertTrue(reference.sql().startsWith("WITH"), item.id());
            assertTrue(optimized.sql().startsWith("WITH"), item.id());
        }
        var ma60 = definition.cases().stream().filter(x -> x.id().equals("ma60")).findFirst().orElseThrow();
        assertTrue(compiler.compile(ma60.dsl(), StockSlotSqlCompiler.AccessPathMode.OPTIMIZED).sql()
                .contains("stock_daily_features_v1"));
        assertTrue(compiler.compile(ma60.dsl(), StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).sql()
                .contains("v_hsj_stock_hq_basic"));
        var single = definition.cases().stream().filter(x -> x.id().equals("single-day-simple-filter")).findFirst().orElseThrow();
        assertTrue(compiler.compile(single.dsl(), StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).sql()
                .contains("DATE_FORMAT(b.bizdate,'%Y-%m-%d') = ?"));
        assertFalse(compiler.compile(single.dsl(), StockSlotSqlCompiler.AccessPathMode.OPTIMIZED).sql()
                .contains("DATE_FORMAT(b.bizdate"));
    }

    @Test void percentileUsesNearestRankAndRequiresSamples() {
        var values = new ArrayList<Double>();
        for (int i = 1; i <= 30; i++) values.add((double) i);
        var stats = DorisBenchmarkMatrixRunner.stats(values);
        assertEquals(15, stats.p50Millis());
        assertEquals(29, stats.p95Millis());
        assertEquals(1, stats.minMillis());
        assertEquals(30, stats.maxMillis());
        assertThrows(IllegalArgumentException.class, () -> DorisBenchmarkMatrixRunner.stats(List.of()));
    }

    @Test void markdownContainsComparisonColumnsAndFormula() {
        var stats = new DorisBenchmarkMatrixReport.Stats(10, 20, 8, 22);
        var result = new DorisBenchmarkMatrixReport.CaseResult("q1", "WINDOW", "HOT", true, 10,
                stats, new DorisBenchmarkMatrixReport.Stats(2, 4, 1, 5), 5, 5,
                "candidate", "sha256:a", "sha256:b", "q1/hot");
        var report = new DorisBenchmarkMatrixReport("v1", "snapshot", "compiler", 30,
                "process restart", List.of(result));
        String markdown = DorisBenchmarkMatrixMarkdown.render(report);
        assertTrue(markdown.contains("基线 P50"));
        assertTrue(markdown.contains("优化 P95"));
        assertTrue(markdown.contains("5.000x"));
        assertTrue(markdown.contains("全表扫描参考耗时 / 优化查询耗时"));
    }
}
