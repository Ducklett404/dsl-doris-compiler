package com.acme.dorisdsl.stockslot;

public record DorisExecutionPolicy(
        int queryTimeoutSeconds,
        long maxEstimatedScanRows,
        int maxReturnRows,
        long maxExecutionMemoryBytes,
        int maxQueueWaitMillis,
        boolean requireReadOnlyAccount
) {
    public DorisExecutionPolicy {
        if (queryTimeoutSeconds < 1 || queryTimeoutSeconds > DorisQueryExecutor.MAX_TIMEOUT_SECONDS)
            throw new IllegalArgumentException("queryTimeoutSeconds must be 1.." + DorisQueryExecutor.MAX_TIMEOUT_SECONDS);
        if (maxEstimatedScanRows < 1) throw new IllegalArgumentException("maxEstimatedScanRows must be positive");
        if (maxReturnRows < 1 || maxReturnRows > 100_000)
            throw new IllegalArgumentException("maxReturnRows must be 1..100000");
        if (maxExecutionMemoryBytes < 64L * 1024 * 1024)
            throw new IllegalArgumentException("maxExecutionMemoryBytes must be at least 64 MiB");
        if (maxQueueWaitMillis < 1 || maxQueueWaitMillis > 60_000)
            throw new IllegalArgumentException("maxQueueWaitMillis must be 1..60000");
    }

    public static DorisExecutionPolicy controlledDefaults() {
        return new DorisExecutionPolicy(10, 1_000_000, 1_000, 512L * 1024 * 1024, 2_000, true);
    }

    public static DorisExecutionPolicy localBenchmarkDefaults() {
        return new DorisExecutionPolicy(10, 100_000_000, 10_000, 2L * 1024 * 1024 * 1024, 10_000, false);
    }
}
