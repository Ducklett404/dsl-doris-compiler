package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.*;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

final class DorisExecutionMarkdownRendererTest {
    @Test void rendersStocksTimingFingerprintVersionExplainAndProfile() {
        var compilation = new StockSlotSqlCompiler().compile(
                "indicator('沪', '', '60日均线', '2026-04-14', '', '', '') > 1 limit 0,1");
        var result = new DorisExecutionArtifact(compilation, List.of("mktcode", "tgtcode"),
                List.of(List.of("1", "600000")), false,
                new DorisExecutionArtifact.Timings(1, 2, 3, 4, 5, 15),
                new DorisExecutionArtifact.Limits(10, 1_000_000, 5_573, 100, 536_870_912),
                "sha256:abc", new DorisExecutionArtifact.SnapshotVersion("snapshot-v1", "1.0.0", "hash"),
                "0.1.0", List.of("PLAN FRAGMENT 0", "cardinality=5573"),
                new DorisExecutionArtifact.QueryProfileSummary(true, "abc-def", "EOF", "4 ms", "reader", "summary"));

        String markdown = DorisExecutionMarkdownRenderer.render(result);
        assertTrue(markdown.contains("# DSL → Doris 执行结果"));
        assertTrue(markdown.contains("| 1 | 600000 |"));
        assertTrue(markdown.contains("sha256:abc"));
        assertTrue(markdown.contains("snapshot-v1"));
        assertTrue(markdown.contains("PLAN FRAGMENT 0"));
        assertTrue(markdown.contains("Query Profile"));
    }
}
