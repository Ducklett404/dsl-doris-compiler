package com.acme.dorisdsl.stockslot;

public record DorisBenchmarkReport(
        String snapshotId,
        int warmup,
        int iterations,
        int resultRows,
        Percentiles compile,
        Percentiles query,
        Percentiles fullScanBaseline,
        double fullScanSpeedup,
        boolean compileP95Below50Millis,
        boolean queryP95AtMost10Seconds,
        boolean fullScanSpeedupAtLeastTen,
        boolean passed
) {
    public record Percentiles(double p50Millis, double p95Millis, double p99Millis, double maxMillis) {}
}
