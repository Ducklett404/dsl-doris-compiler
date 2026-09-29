package com.acme.dorisdsl.executor.doris;

import java.io.IOException;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;

public final class BenchmarkRunner {
    private final DorisQueryExecutor executor;
    private final ExplainService explainService;
    private final QueryProfileCollector profiles;

    public BenchmarkRunner(DorisQueryExecutor executor, ExplainService explainService,
                           QueryProfileCollector profiles) {
        this.executor = executor;
        this.explainService = explainService;
        this.profiles = profiles;
    }

    public PerformanceReport run(String sql, List<?> bindings) throws SQLException, IOException, InterruptedException {
        var explain = explainService.explain(sql, bindings);
        var execution = executor.executeProfiled(sql, bindings);
        var profile = profiles.collect(execution.queryId());
        long elapsed = profile.elapsedNanos() >= 0 ? profile.elapsedNanos() : execution.clientElapsedNanos();
        return new PerformanceReport(Instant.now(), execution.queryId(), profile.scannedBytes(), profile.scannedRows(),
                elapsed, profile.peakMemoryBytes(), explain.partitionPruned(), explain.scannedPartitions(),
                explain.totalPartitions(), explain.bucketOrTabletPruned(), explain.indexHit(),
                explain.materializedViewHit(), explain.featureTableHit(), explain.rawPlan(), profile.rawProfile());
    }

    public record PerformanceReport(Instant collectedAt, String queryId, long scannedBytes, long scannedRows,
                                    long elapsedNanos, long peakMemoryBytes, boolean partitionPruned,
                                    int scannedPartitions, int totalPartitions, boolean bucketOrTabletPruned,
                                    boolean indexHit, boolean materializedViewHit, boolean featureTableHit,
                                    String rawExplain, String rawProfile) {}
}
