package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.CompilerPerformanceBenchmark;
import com.acme.dorisdsl.stockslot.CompilerPerformanceDefinition;
import com.acme.dorisdsl.stockslot.CompilerPerformanceMarkdown;
import com.acme.dorisdsl.stockslot.StockSlotRegistryLoader;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotCompilerPerformanceTest {
    @Test void complexFormalCorpusStaysBelowCiP95Budget() throws Exception {
        var definition = JsonSupport.MAPPER.readValue(
                Path.of("benchmarks/compiler/stock-slot-complex-v1.json").toFile(),
                CompilerPerformanceDefinition.class);
        var report = new CompilerPerformanceBenchmark().run(definition, 500, 5_000, 50.0,
                new StockSlotRegistryLoader().loadDefault());

        assertEquals(10, report.corpusSize());
        assertEquals(5_000, report.uncachedPipeline().iterations());
        assertTrue(report.passed(), () -> "uncached P95="
                + report.uncachedPipeline().stages().get("total").p95() + "ms");
        assertTrue(report.uncachedPipeline().stages().keySet().containsAll(
                java.util.List.of("parse", "semantic", "rewrite", "planning", "sqlGeneration", "total")));
        assertTrue(report.cacheStats().astSize() <= report.cacheStats().capacity());
        assertTrue(report.cacheStats().semanticSize() <= report.cacheStats().capacity());
        assertTrue(report.cacheStats().sqlTemplateSize() <= report.cacheStats().capacity());
        assertTrue(report.cacheStats().sqlTemplateHits() >= 5_000);
        assertTrue(report.cacheStats().indicatorDefinitions().size()
                <= report.cacheStats().indicatorDefinitions().capacity());
        String markdown = CompilerPerformanceMarkdown.render(report);
        assertAll(() -> assertTrue(markdown.contains("P50 ms")),
                () -> assertTrue(markdown.contains("P95 ms")),
                () -> assertTrue(markdown.contains("P99 ms")),
                () -> assertTrue(markdown.contains("Allocated bytes/compile")));
    }
}
