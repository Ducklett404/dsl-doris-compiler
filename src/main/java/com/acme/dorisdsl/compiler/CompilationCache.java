package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.plan.LogicalPlan;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class CompilationCache {
    private final int maximumEntries;
    private final Map<CacheKey, CachedCompilation> entries;
    private long hits;
    private long misses;

    public CompilationCache(int maximumEntries) {
        if (maximumEntries < 1) throw new IllegalArgumentException("maximumEntries must be positive");
        this.maximumEntries = maximumEntries;
        this.entries = new LinkedHashMap<>(16, 0.75f, true);
    }

    public synchronized CachedCompilation get(CacheKey key) {
        CachedCompilation value = entries.get(key);
        if (value == null) misses++; else hits++;
        return value;
    }

    public synchronized void put(CacheKey key, CachedCompilation value) {
        entries.put(key, value);
        while (entries.size() > maximumEntries) {
            entries.remove(entries.keySet().iterator().next());
        }
    }

    public synchronized Stats stats() {
        return new Stats(entries.size(), hits, misses);
    }

    public record CacheKey(
            String normalizedAstHash,
            String ruleVersion,
            String catalogVersion,
            String dorisCapabilityVersion
    ) {}

    /** Deliberately excludes AST, bindings, request context, and authorization decisions. */
    public record CachedCompilation(
            LogicalPlan logicalPlan,
            String sql,
            List<CompilationArtifact.Diagnostic> diagnostics,
            List<CompilationArtifact.RuleTrace> ruleTrace,
            int lookback
    ) {
        public CachedCompilation {
            diagnostics = List.copyOf(diagnostics);
            ruleTrace = List.copyOf(ruleTrace);
        }
    }

    public record Stats(int size, long hits, long misses) {}
}
