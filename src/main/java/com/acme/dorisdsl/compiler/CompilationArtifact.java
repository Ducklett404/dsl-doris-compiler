package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.plan.LogicalPlan;

import java.util.List;

public record CompilationArtifact(
        Ast.Query ast,
        LogicalPlan logicalPlan,
        String sql,
        List<Object> bindings,
        List<Diagnostic> diagnostics,
        List<RuleTrace> ruleTrace,
        LogicalPlan.AccessPathDecision accessPath,
        int lookback,
        String compilerVersion,
        String ruleSetVersion
) {
    public CompilationArtifact {
        bindings = List.copyOf(bindings);
        diagnostics = List.copyOf(diagnostics);
        ruleTrace = List.copyOf(ruleTrace);
    }

    public int requiredLookbackTradingDays() { return lookback; }

    public record RuleTrace(String ruleId, String description) {}
    public record Diagnostic(String severity, String code, String message) {}
}
