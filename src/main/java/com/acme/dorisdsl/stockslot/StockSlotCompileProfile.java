package com.acme.dorisdsl.stockslot;

public record StockSlotCompileProfile(StockSlotSqlArtifact artifact, Timings timings) {
    public record Timings(long parseNanos, long semanticNanos, long rewriteNanos,
                          long planningNanos, long sqlGenerationNanos, long totalNanos,
                          boolean astCacheHit, boolean semanticCacheHit, boolean sqlTemplateCacheHit) {}
}
