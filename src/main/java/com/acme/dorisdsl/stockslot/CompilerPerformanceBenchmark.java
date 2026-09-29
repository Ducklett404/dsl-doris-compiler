package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.sun.management.ThreadMXBean;

import java.lang.management.ManagementFactory;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Repeatable in-process benchmark for the formal stock-slot-v1 SQL compiler. */
public final class CompilerPerformanceBenchmark {
    public CompilerPerformanceReport run(CompilerPerformanceDefinition definition, int warmup, int iterations,
                                         double p95ThresholdMillis, StockSlotRegistry registry) {
        if (definition.cases().size() < 5) throw new IllegalArgumentException("Complex corpus requires at least five cases");
        if (warmup < 500) throw new IllegalArgumentException("Warmup must be at least 500 iterations");
        if (iterations < 5_000) throw new IllegalArgumentException("Benchmark requires at least 5000 iterations");
        if (!(p95ThresholdMillis > 0)) throw new IllegalArgumentException("P95 threshold must be positive");

        StockSlotSqlCompiler compiler = new StockSlotSqlCompiler(registry, 256);
        for (var item : definition.cases()) compiler.compileProfiledUncached(item.dsl());
        for (int i = 0; i < warmup; i++)
            compiler.compileProfiledUncached(definition.cases().get(i % definition.cases().size()).dsl());

        LaneSamples uncached = measure(definition, iterations, compiler, false);
        compiler.clearCaches();
        for (var item : definition.cases()) compiler.compile(item.dsl());
        for (int i = 0; i < warmup; i++) compiler.compile(definition.cases().get(i % definition.cases().size()).dsl());
        LaneSamples cached = measure(definition, iterations, compiler, true);

        var uncachedReport = uncached.report("UNCACHED_PHASES_AFTER_JVM_WARMUP");
        var cachedReport = cached.report("BOUNDED_CACHE_HOT_PATH");
        boolean passed = uncachedReport.stages().get("total").p95() < p95ThresholdMillis;
        return new CompilerPerformanceReport(DslCompiler.VERSION, registry.version(), definition.corpusVersion(),
                definition.cases().size(), warmup, p95ThresholdMillis, uncachedReport, cachedReport,
                passed, compiler.cacheStats());
    }

    private LaneSamples measure(CompilerPerformanceDefinition definition, int iterations,
                                StockSlotSqlCompiler compiler, boolean cached) {
        LaneSamples samples = new LaneSamples(iterations);
        ThreadMXBean bean = allocationBean();
        long threadId = Thread.currentThread().threadId();
        for (int i = 0; i < iterations; i++) {
            String dsl = definition.cases().get(i % definition.cases().size()).dsl();
            long before = allocated(bean, threadId);
            StockSlotCompileProfile profile = cached ? compiler.compileProfiled(dsl) : compiler.compileProfiledUncached(dsl);
            long after = allocated(bean, threadId);
            samples.add(profile.timings(), before < 0 || after < before ? -1 : after - before);
        }
        return samples;
    }

    private static ThreadMXBean allocationBean() {
        var bean = ManagementFactory.getThreadMXBean();
        if (!(bean instanceof ThreadMXBean allocation) || !allocation.isThreadAllocatedMemorySupported()) return null;
        if (!allocation.isThreadAllocatedMemoryEnabled()) allocation.setThreadAllocatedMemoryEnabled(true);
        return allocation;
    }

    private static long allocated(ThreadMXBean bean, long threadId) {
        return bean == null ? -1 : bean.getThreadAllocatedBytes(threadId);
    }

    private static final class LaneSamples {
        private final Map<String, List<Long>> values = new LinkedHashMap<>();
        private final List<Long> allocations = new ArrayList<>();

        LaneSamples(int capacity) {
            for (String stage : List.of("parse", "semantic", "rewrite", "planning", "sqlGeneration", "total"))
                values.put(stage, new ArrayList<>(capacity));
        }

        void add(StockSlotCompileProfile.Timings value, long allocation) {
            values.get("parse").add(value.parseNanos());
            values.get("semantic").add(value.semanticNanos());
            values.get("rewrite").add(value.rewriteNanos());
            values.get("planning").add(value.planningNanos());
            values.get("sqlGeneration").add(value.sqlGenerationNanos());
            values.get("total").add(value.totalNanos());
            if (allocation >= 0) allocations.add(allocation);
        }

        CompilerPerformanceReport.Lane report(String name) {
            Map<String, CompilerPerformanceReport.Stats> stages = new LinkedHashMap<>();
            values.forEach((stage, samples) -> stages.put(stage, stats(samples, 1_000_000.0)));
            return new CompilerPerformanceReport.Lane(name, values.get("total").size(), stages,
                    allocations.isEmpty() ? new CompilerPerformanceReport.Stats(-1, -1, -1, -1) : stats(allocations, 1.0));
        }
    }

    static CompilerPerformanceReport.Stats stats(List<Long> input, double divisor) {
        List<Long> sorted = input.stream().sorted().toList();
        return new CompilerPerformanceReport.Stats(at(sorted, .50) / divisor, at(sorted, .95) / divisor,
                at(sorted, .99) / divisor, sorted.getLast() / divisor);
    }

    private static long at(List<Long> sorted, double percentile) {
        return sorted.get(Math.min(sorted.size() - 1, (int) Math.ceil(sorted.size() * percentile) - 1));
    }
}
