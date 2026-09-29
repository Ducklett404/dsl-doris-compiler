package com.acme.dorisdsl.stockslot;

import java.util.Locale;

public final class DorisBenchmarkMatrixMarkdown {
    private DorisBenchmarkMatrixMarkdown() {}

    public static String render(DorisBenchmarkMatrixReport report) {
        var out = new StringBuilder("# Doris 基准矩阵\n\n")
                .append("- 矩阵版本：`").append(report.matrixVersion()).append("`\n")
                .append("- 数据快照：`").append(report.snapshotId()).append("`\n")
                .append("- 编译器版本：`").append(report.compilerVersion()).append("`\n")
                .append("- 每类/缓存模式重复：").append(report.iterations()).append(" 次\n")
                .append("- 冷缓存口径：").append(report.coldCacheProtocol()).append("\n\n")
                .append("| 查询 | 类别 | 缓存 | 结果一致 | 行数 | 基线 P50 | 优化 P50 | 加速 P50 | 基线 P95 | 优化 P95 | 加速 P95 | 建议路径 |\n")
                .append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|\n");
        for (var r : report.results()) out.append('|').append(r.id()).append('|').append(r.category())
                .append('|').append(r.cacheMode()).append('|').append(r.resultsEqual()).append('|').append(r.resultRows())
                .append('|').append(f(r.baseline().p50Millis())).append('|').append(f(r.optimized().p50Millis()))
                .append('|').append(f(r.speedupP50())).append("x|")
                .append(f(r.baseline().p95Millis())).append('|').append(f(r.optimized().p95Millis()))
                .append('|').append(f(r.speedupP95())).append("x|").append(r.recommendedPath()).append("|\n");
        out.append("\n每个证据目录均包含参考/优化 SQL、bindings、EXPLAIN 和 30 次 Query Profile 摘要。\n")
                .append("加速比严格按 `全表扫描参考耗时 / 优化查询耗时` 计算。\n");
        return out.toString();
    }

    private static String f(double value) { return String.format(Locale.ROOT, "%.3f", value); }
}
