package com.acme.dorisdsl.stockslot;

import java.util.List;

public record DorisBenchmarkMatrixReport(
        String matrixVersion,
        String snapshotId,
        String compilerVersion,
        int iterations,
        String coldCacheProtocol,
        List<CaseResult> results
) {
    public DorisBenchmarkMatrixReport { results = List.copyOf(results); }

    public record CaseResult(String id, String category, String cacheMode, boolean resultsEqual,
                             int resultRows, Stats baseline, Stats optimized,
                             double speedupP50, double speedupP95, String recommendedPath,
                             String baselineFingerprint, String optimizedFingerprint,
                             String evidenceDirectory) {}
    public record Stats(double p50Millis, double p95Millis, double minMillis, double maxMillis) {}
}
