package com.acme.dorisdsl.stockslot;

import java.util.Locale;

public final class CompilerPerformanceMarkdown {
    private CompilerPerformanceMarkdown() {}

    public static String render(CompilerPerformanceReport report) {
        StringBuilder out = new StringBuilder("# 正式 DSL 编译性能报告\n\n")
                .append("| 项目 | 值 |\n|---|---|\n")
                .append("| Compiler | ").append(report.compilerVersion()).append(" |\n")
                .append("| Registry | ").append(report.registryVersion()).append(" |\n")
                .append("| Corpus | ").append(report.corpusVersion()).append(" / ").append(report.corpusSize()).append(" cases |\n")
                .append("| Warmup | ").append(report.warmupIterations()).append(" |\n")
                .append("| Required uncached P95 | < ").append(report.p95ThresholdMillis()).append(" ms |\n")
                .append("| Result | ").append(report.passed() ? "PASS" : "FAIL").append(" |\n\n");
        lane(out, report.uncachedPipeline());
        lane(out, report.boundedCache());
        var cache = report.cacheStats();
        out.append("\n## 有界缓存\n\n| AST | Semantic | SQL template | Capacity | SQL hits/misses |\n|---:|---:|---:|---:|---:|\n|")
                .append(cache.astSize()).append('|').append(cache.semanticSize()).append('|')
                .append(cache.sqlTemplateSize()).append('|').append(cache.capacity()).append('|')
                .append(cache.sqlTemplateHits()).append('/').append(cache.sqlTemplateMisses()).append("|\n");
        var indicator = cache.indicatorDefinitions();
        out.append("\n指标定义解析缓存：size=").append(indicator.size()).append(" / capacity=")
                .append(indicator.capacity()).append(", hits/misses=").append(indicator.hits())
                .append('/').append(indicator.misses()).append("。注册表文件仅在基准启动时加载一次。\n");
        return out.toString();
    }

    private static void lane(StringBuilder out, CompilerPerformanceReport.Lane lane) {
        out.append("## ").append(lane.name()).append("\n\n")
                .append("Iterations: ").append(lane.iterations()).append("\n\n")
                .append("| Stage | P50 ms | P95 ms | P99 ms | Max ms |\n|---|---:|---:|---:|---:|\n");
        lane.stages().forEach((stage, value) -> out.append('|').append(stage).append('|')
                .append(f(value.p50())).append('|').append(f(value.p95())).append('|')
                .append(f(value.p99())).append('|').append(f(value.max())).append("|\n"));
        var allocation = lane.allocatedBytes();
        out.append("\nAllocated bytes/compile: P50=").append(f(allocation.p50()))
                .append(", P95=").append(f(allocation.p95())).append(", P99=").append(f(allocation.p99()))
                .append(", Max=").append(f(allocation.max())).append(".\n\n");
    }

    private static String f(double value) { return String.format(Locale.ROOT, "%.3f", value); }
}
