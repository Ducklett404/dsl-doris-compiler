package com.acme.dorisdsl.stockslot;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

public record CompilerPerformanceReport(String compilerVersion, String registryVersion, String corpusVersion,
                                        int corpusSize, int warmupIterations, double p95ThresholdMillis,
                                        Lane uncachedPipeline, Lane boundedCache, boolean passed,
                                        StockSlotSqlCompiler.CacheStats cacheStats) {
    public record Lane(String name, int iterations, Map<String, Stats> stages, Stats allocatedBytes) {
        public Lane { stages = Collections.unmodifiableMap(new LinkedHashMap<>(stages)); }
    }
    public record Stats(double p50, double p95, double p99, double max) {}
}
