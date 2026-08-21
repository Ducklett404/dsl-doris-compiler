package com.acme.dorisdsl.executor.doris;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class BenchmarkRunnerTest {
    @Test void producesCompletePerformanceReport() throws Exception {
        var executor = new ExplainServiceTest.StubExecutor(List.of("""
                0:VOlapScanNode
                  table: market.dws_quote_feature_daily
                  partitions=1/20
                  tablets=1/32
                  rollup: mv_latest_features
                  index: idx_feature_version
                """));
        var profiles = new QueryProfileCollector(queryId -> """
                - Total: 80ms
                - RowsRead: 5000
                - BytesRead: 2.00 MB
                - PeakMemoryUsage: 6.00 MB
                """);
        var runner = new BenchmarkRunner(executor, new ExplainService(executor), profiles);

        var report = runner.run("SELECT * FROM market.dws_quote_feature_daily", List.of());

        assertEquals("query-1", report.queryId());
        assertEquals(2L << 20, report.scannedBytes());
        assertEquals(5000, report.scannedRows());
        assertEquals(80_000_000L, report.elapsedNanos());
        assertEquals(6L << 20, report.peakMemoryBytes());
        assertTrue(report.partitionPruned());
        assertTrue(report.bucketOrTabletPruned());
        assertTrue(report.materializedViewHit());
        assertTrue(report.indexHit());
        assertTrue(report.featureTableHit());
        assertFalse(report.rawExplain().isBlank());
        assertFalse(report.rawProfile().isBlank());
    }
}
