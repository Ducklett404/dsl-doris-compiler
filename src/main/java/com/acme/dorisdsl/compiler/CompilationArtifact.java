package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.plan.LogicalPlan;

import java.util.List;

public record CompilationArtifact(
        String compilerVersion,
        Ast.Query ast,
        LogicalPlan logicalPlan,
        String sql,
        List<Object> bindings,
        int requiredLookbackTradingDays,
        List<RuleTrace> ruleTrace,
        List<Diagnostic> diagnostics
) {
    public CompilationArtifact {
        bindings = List.copyOf(bindings);
        ruleTrace = List.copyOf(ruleTrace);
        diagnostics = List.copyOf(diagnostics);
    }
    public record RuleTrace(String ruleId, String description, String semanticProofTag, int priority, String version) {
        public RuleTrace(String ruleId, String description) {
            this(ruleId, description, "", 0, "");
        }
    }
    public record Diagnostic(String severity, String code, String message) {}
}
