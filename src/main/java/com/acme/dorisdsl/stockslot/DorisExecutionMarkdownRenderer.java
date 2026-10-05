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
        var quality = result.dataQuality();
        if (quality != null) {
            out.append("## 数据可用性\n\n")
                    .append("本次按项目内部规则验证，包含已披露的数据限制，不代表官方验收通过。\n\n")
                    .append("- 评价日期：").append(quality.evaluationDate()).append("\n")
                    .append("- 筛选前实际有行情的证券：").append(quality.observedSecurities()).append("\n")
                    .append("- 当日缺少衍生行情：").append(quality.currentMissingExtensionRows()).append("\n")
                    .append("- 全快照未关联衍生行：").append(quality.snapshotExtensionWithoutBasic()).append("\n\n")
                    .append("| 查询输入 | 观察窗口 | 输入标识 | 无法计算的证券数 |\n|---|---|---|---:|\n");
            for (var input : quality.inputs()) out.append("| ").append(cell(input.function() + " " + input.indicator()))
                    .append(" | ").append(cell(input.window())).append(" | ").append(input.inputId(), 0, 12)
                    .append(" | ").append(input.unavailableSecurities()).append(" |\n");
            if (!quality.sampleDetails().isEmpty()) {
                out.append("\n### 样本原因与实际相关日期\n\n");
                for (var sample : quality.sampleDetails()) {
                    out.append("- ").append(cell(sample.marketCode())).append('/').append(cell(sample.securityCode()))
                            .append(sample.currentExtensionMissing() ? "：评价日缺少衍生行情" : "")
                            .append(sample.historyTruncated() ? "（历史样本已截断）" : "").append("\n");
                    for (var issue : sample.inputs()) {
                        out.append("  - ").append(cell(issue.function() + " " + issue.indicator())).append("，")
                                .append(cell(issue.window())).append("，标识 ").append(issue.inputId(), 0, 12)
                                .append(issue.status().equals("PARTIAL_DETAIL") ? "（解释不完整）" : "").append("\n");
                        for (var reason : issue.reasons()) {
                            out.append("    - ").append(StockSlotAvailabilityDiagnostics.reasonLabel(reason.code())).append("：")
                                    .append(cell(reason.indicator()));
                            if (reason.requiredObservations() > 0) out.append("；需要 ").append(reason.requiredObservations())
                                    .append(" 条，已观察 ").append(reason.minimumObserved()).append(reason.minimumObserved() == reason.maximumObserved()
                                            ? "" : "–" + reason.maximumObserved());
                            if (!reason.relatedDates().isEmpty()) out.append("；相关日期 ").append(String.join(", ", reason.relatedDates()))
                                    .append(reason.datesTruncated() ? "（共 " + reason.totalRelatedDates() + " 个，仅展示前 20 个）" : "");
                            out.append("\n");
                        }
                    }
                }
            }
            if (quality.observedSecurities() == 0) out.append("\n评价日及市场范围内没有实际行情记录，空结果不能解释为所有证券均不符合条件。\n");
            out.append("\n数量按用户条件、排名及返回上限之前的查询范围统计；各输入可能影响同一证券，不能相加。无法计算不等于不符合条件。\n\n");
            quality.limitations().forEach(note -> out.append("- ").append(escape(note)).append("\n"));
            out.append("\n- 数据验证及可用性检查：").append(f(quality.validationMillis())).append(" ms\n\n");
        }
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
