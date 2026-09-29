package com.acme.dorisdsl.util;

import com.acme.dorisdsl.compiler.CompilationArtifact;

public final class MarkdownRenderer {
    private MarkdownRenderer() {}

    public static String render(CompilationArtifact artifact) {
        StringBuilder out = new StringBuilder("# DSL 编译结果\n\n")
                .append("| 项目 | 值 |\n|---|---|\n")
                .append("| Compiler | ").append(artifact.compilerVersion()).append(" |\n")
                .append("| Rule config | ").append(artifact.ruleConfigVersion()).append(" |\n")
                .append("| Access path | ").append(artifact.logicalPlan().accessPath().selected()).append(" |\n")
                .append("| Lookback | ").append(artifact.requiredLookbackTradingDays()).append(" trading days |\n")
                .append("| Window specs | ").append(artifact.windowSpecs().size()).append(" |\n")
                .append("| Bindings | ").append(artifact.bindings().size()).append(" |\n\n")
                .append("## Doris SQL\n\n```sql\n").append(artifact.sql()).append("\n```\n\n")
                .append("## 参数\n\n| # | 值 |\n|---:|---|\n");
        for (int i = 0; i < artifact.bindings().size(); i++) {
            out.append('|').append(i + 1).append('|').append(escape(String.valueOf(artifact.bindings().get(i)))).append("|\n");
        }
        out.append("\n## 规则轨迹\n\n| Rule | 配置 | 阶段 | 迭代 | 输入→输出 | 优先级 | 冲突处理 | 等价性 | 说明 |\n")
                .append("|---|---|---|---:|---|---:|---|---|---|\n");
        artifact.ruleTrace().forEach(t -> out.append('|').append(t.ruleId()).append('|')
                .append(t.configVersion()).append('|').append(t.phase()).append('|').append(t.iteration()).append('|')
                .append(t.inputNodeType()).append("→").append(t.outputNodeType()).append('|').append(t.priority()).append('|')
                .append(escape(t.conflictResolution())).append('|').append(escape(t.equivalence())).append('|')
                .append(escape(t.description())).append("|\n"));
        return out.toString();
    }

    private static String escape(String value) { return value.replace("|", "\\|").replace("\n", " "); }
}
