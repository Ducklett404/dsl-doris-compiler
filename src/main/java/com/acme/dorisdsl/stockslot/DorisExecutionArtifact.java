package com.acme.dorisdsl.stockslot;

import java.util.List;

public record DorisExecutionArtifact(
        StockSlotSqlArtifact compilation,
        List<String> columns,
        List<List<String>> rows,
        boolean truncated,
        Timings timings,
        Limits limits,
        String sqlFingerprint,
        SnapshotVersion dataVersion,
        String compilerVersion,
        List<String> explain,
        QueryProfileSummary queryProfile
) {
    public DorisExecutionArtifact {
        columns = List.copyOf(columns);
        rows = rows.stream().map(List::copyOf).toList();
        explain = List.copyOf(explain);
    }

    /** Compatibility accessors retained for the benchmark command. */
    public double compileMillis() { return timings.compileMillis(); }
    public double queryMillis() { return timings.dorisExecutionMillis() + timings.returnMillis(); }

    public record Timings(double compileMillis, double queueMillis, double explainMillis,
                          double dorisExecutionMillis, double returnMillis, double totalMillis) {}
    public record Limits(int queryTimeoutSeconds, long maxEstimatedScanRows, long estimatedScanRows,
                         int maxReturnRows, long maxExecutionMemoryBytes) {}
    public record SnapshotVersion(String snapshotId, String contractVersion, String manifestSha256) {}
    public record QueryProfileSummary(boolean available, String queryId, String taskState,
                                      String total, String user, String note) {}
}
