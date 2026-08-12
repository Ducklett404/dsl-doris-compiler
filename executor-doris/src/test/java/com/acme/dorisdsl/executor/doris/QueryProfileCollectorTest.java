package com.acme.dorisdsl.executor.doris;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class QueryProfileCollectorTest {
    private static final String PROFILE = """
            Summary:
              - Total: 1s250ms
            VOlapScanNode:
              - RowsRead: 1,250,000
              - BytesRead: 48.50 MB
              - PeakMemoryUsage: 72.00 MB
            """;

    @Test void extractsRequiredPerformanceMetrics() throws Exception {
        var profile = new QueryProfileCollector(queryId -> PROFILE).collect("query-1");

        assertEquals(1_250_000L, profile.scannedRows());
        assertEquals(50_855_936L, profile.scannedBytes());
        assertEquals(75_497_472L, profile.peakMemoryBytes());
        assertEquals(1_250_000_000L, profile.elapsedNanos());
    }
}
