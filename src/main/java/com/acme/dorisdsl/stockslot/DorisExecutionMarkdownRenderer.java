package com.acme.dorisdsl.stockslot;

public final class DorisExecutionMarkdownRenderer {
    private DorisExecutionMarkdownRenderer() {}

    public static String render(DorisExecutionArtifact result) {
        var out = new StringBuilder("# DSL → Doris 执行结果\n\n");
        out.append("- 数据快照：`").append(escape(result.dataVersion().snapshotId())).append("`\n")
                .append("- 编译器版本：`").append(escape(result.compilerVersion())).append("`\n")
                .append("- SQL 指纹：`").append(result.sqlFingerprint()).append("`\n")
                .append("- 返回行数：").append(result.rows().size())
                .append(result.truncated() ? "（已按安全上限截断）" : "").append("\n")
                .append("- 估算扫描行数：").append(result.limits().estimatedScanRows()).append(" / ")
                .append(result.limits().maxEstimatedScanRows()).append("\n\n");
        var t = result.timings();
        out.append("## 分阶段耗时\n\n")
                .append("| 阶段 | 毫秒 |\n|---|---:|\n")
                .append("| 编译 | ").append(f(t.compileMillis())).append(" |\n")
                .append("| 应用排队 | ").append(f(t.queueMillis())).append(" |\n")
                .append("| EXPLAIN/门禁 | ").append(f(t.explainMillis())).append(" |\n")
                .append("| Doris 执行至结果可读 | ").append(f(t.dorisExecutionMillis())).append(" |\n")
                .append("| 结果读取/返回 | ").append(f(t.returnMillis())).append(" |\n")
                .append("| 总耗时 | ").append(f(t.totalMillis())).append(" |\n\n");
        out.append("## 股票列表\n\n");
        if (result.columns().isEmpty()) out.append("无结果。\n");
        else {
            out.append("|"); result.columns().forEach(c -> out.append(" ").append(cell(c)).append(" |"));
            out.append("\n|"); result.columns().forEach(c -> out.append("---|")); out.append("\n");
            for (var row : result.rows()) {
                out.append("|"); row.forEach(v -> out.append(" ").append(cell(v)).append(" |")); out.append("\n");
            }
        }
        var p = result.queryProfile();
        out.append("\n## Query Profile 摘要\n\n")
                .append("- 可用：").append(p.available()).append("\n")
                .append("- Query ID：`").append(escape(p.queryId())).append("`\n")
                .append("- 状态：").append(escape(p.taskState())).append("\n")
                .append("- Doris 总耗时：").append(escape(p.total())).append("\n")
                .append("- 用户：").append(escape(p.user())).append("\n")
                .append("- 说明：").append(escape(p.note())).append("\n\n")
                .append("## EXPLAIN\n\n```text\n");
        result.explain().forEach(line -> out.append(line.replace("```", "` ` `")).append("\n"));
        return out.append("```\n").toString();
    }

    private static String f(double value) { return String.format(java.util.Locale.ROOT, "%.3f", value); }
    private static String cell(String value) { return escape(value).replace("|", "\\|").replace("\n", " "); }
    private static String escape(String value) { return value == null ? "不可用" : value; }
}
