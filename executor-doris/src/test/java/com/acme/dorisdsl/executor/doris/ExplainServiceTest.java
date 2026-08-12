package com.acme.dorisdsl.executor.doris;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class ExplainServiceTest {
    @Test void provesPruningMvIndexAndFeatureTableHits() throws Exception {
        DorisQueryExecutor executor = new StubExecutor(List.of("""
                0:VOlapScanNode
                   TABLE: market.dws_quote_feature_daily
                   partitions=1/32
                   tablets=2/64
                   rollup: mv_latest_features
                   index: idx_feature_version
                """));

        var evidence = new ExplainService(executor).explain("SELECT 1", List.of());

        assertTrue(evidence.partitionPruned());
        assertEquals(1, evidence.scannedPartitions());
        assertEquals(32, evidence.totalPartitions());
        assertTrue(evidence.bucketOrTabletPruned());
        assertTrue(evidence.materializedViewHit());
        assertTrue(evidence.indexHit());
        assertTrue(evidence.featureTableHit());
    }

    static final class StubExecutor implements DorisQueryExecutor {
        private final List<String> plan;
        StubExecutor(List<String> plan) { this.plan = plan; }
        @Override public List<String> explain(String sql, List<?> bindings) { return plan; }
        @Override public QueryExecution executeProfiled(String sql, List<?> bindings) {
            return new QueryExecution("query-1", 99_000_000L);
        }
    }
}
