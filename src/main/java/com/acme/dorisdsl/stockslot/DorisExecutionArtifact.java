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
        QueryProfileSummary queryProfile,
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        DataQuality dataQuality
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
    public record DataQuality(String validationLevel, boolean officialAcceptanceEligible, String certificateSha256,
                              String coverageStatus, String evaluationDate, List<String> requiredSources,
                              long observedSecurities, long currentMissingExtensionRows, List<InputAvailability> inputs,
                              List<List<String>> unavailableSamples, long snapshotExtensionWithoutBasic,
                              long snapshotCloseOutsideRange, List<String> limitations, double validationMillis,
                              List<StockSlotAvailabilityDiagnostics.SampleDetail> sampleDetails,
                              DiagnosticTimings diagnosticTimings) {
        public DataQuality {
            requiredSources = List.copyOf(requiredSources); inputs = List.copyOf(inputs);
            unavailableSamples = unavailableSamples.stream().map(List::copyOf).toList();
            limitations = List.copyOf(limitations); sampleDetails = List.copyOf(sampleDetails);
        }
    }
    /** Disjoint project diagnostic stages; validationMillis also includes the main EXPLAIN. */
    public record DiagnosticTimings(double sourceValidationMillis, double mainExplainMillis,
                                    double availabilityExplainMillis, double missingStatisticsMillis,
                                    double sampleDetailsMillis) {}
    public record InputAvailability(String function, String indicator, long unavailableSecurities,
                                    String inputId, String window, String role, int requiredObservations) {}
    public DorisExecutionArtifact(StockSlotSqlArtifact compilation, List<String> columns, List<List<String>> rows,
                                   boolean truncated, Timings timings, Limits limits, String sqlFingerprint,
                                   SnapshotVersion dataVersion, String compilerVersion, List<String> explain,
                                   QueryProfileSummary queryProfile) {
        this(compilation, columns, rows, truncated, timings, limits, sqlFingerprint, dataVersion,
                compilerVersion, explain, queryProfile, null);
    }
}
