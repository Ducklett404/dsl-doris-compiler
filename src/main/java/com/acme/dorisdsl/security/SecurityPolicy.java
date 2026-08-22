package com.acme.dorisdsl.security;

public record SecurityPolicy(
        long maximumEstimatedScanBytes,
        double maximumPlanCost,
        long estimatedRowsPerTradingDay,
        int estimatedBytesPerRow
) {
    public static SecurityPolicy defaults() {
        return new SecurityPolicy(64L * 1024 * 1024 * 1024, 128d * 1024 * 1024 * 1024,
                6_000_000, 128);
    }

    public SecurityPolicy {
        if (maximumEstimatedScanBytes < 1 || maximumPlanCost <= 0
                || estimatedRowsPerTradingDay < 1 || estimatedBytesPerRow < 1) {
            throw new IllegalArgumentException("Security policy limits must be positive");
        }
    }
}
