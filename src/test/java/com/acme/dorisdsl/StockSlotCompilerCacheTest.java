package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.StockSlotRegistryLoader;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotCompilerCacheTest {
    @Test void cachesAreBoundedAndStableSqlTemplateIsReused() {
        var compiler = new StockSlotSqlCompiler(new StockSlotRegistryLoader().loadDefault(), 3);
        List<String> dsls = List.of(
                "indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1",
                "indicator('', '', '开盘价', '2026-04-14', '', '', '') > 1",
                "indicator('', '', '最高价', '2026-04-14', '', '', '') > 1",
                "indicator('', '', '最低价', '2026-04-14', '', '', '') > 1",
                "indicator('', '', '成交量', '2026-04-14', '', '', '') > 1");
        dsls.forEach(compiler::compile);
        var first = compiler.compileProfiled(dsls.getLast());
        var second = compiler.compileProfiled(dsls.getLast());

        assertEquals(first.artifact(), second.artifact());
        assertTrue(first.timings().sqlTemplateCacheHit());
        assertTrue(second.timings().sqlTemplateCacheHit());
        var stats = compiler.cacheStats();
        assertEquals(3, stats.capacity());
        assertAll(() -> assertTrue(stats.astSize() <= 3),
                () -> assertTrue(stats.semanticSize() <= 3),
                () -> assertTrue(stats.sqlTemplateSize() <= 3),
                () -> assertTrue(stats.indicatorDefinitions().size() <= stats.indicatorDefinitions().capacity()));
    }
}
