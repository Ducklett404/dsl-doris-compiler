package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.plan.LogicalPlan;
import com.acme.dorisdsl.plan.WindowSpec;

import java.util.List;

public record CompilationArtifact(
        String compilerVersion,
        String ruleConfigVersion,
        Ast.Query ast,
        LogicalPlan logicalPlan,
        String sql,
        List<Object> bindings,
        int requiredLookbackTradingDays,
        List<WindowSpec> windowSpecs,
        List<RuleTrace> ruleTrace,
        List<Diagnostic> diagnostics
) {
    public CompilationArtifact {
        bindings = List.copyOf(bindings);
        windowSpecs = List.copyOf(windowSpecs);
        ruleTrace = List.copyOf(ruleTrace);
        diagnostics = List.copyOf(diagnostics);
    }
    public record RuleTrace(String ruleId, String configVersion, String phase, int iteration,
                            String inputNodeType, String outputNodeType, int priority,
                            String conflictResolution, String equivalence, String description) {
        public RuleTrace(String ruleId, String description) {
            this(ruleId, "compiler-builtin", "PLAN", 1, "LOGICAL_PLAN", "LOGICAL_PLAN", 0,
                    "NONE", "Plan construction preserves query semantics.", description);
        }
    }
    public record Diagnostic(String severity, String code, String message) {}
}
