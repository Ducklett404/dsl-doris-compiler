package com.acme.dorisdsl.compiler;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.plan.LogicalPlan;
import com.acme.dorisdsl.plan.WindowSpec;

import java.util.List;

public record CompilationArtifact(
        String compilerVersion,
        String ruleSetVersion,
        String metadataVersion,
        CacheKey cacheKey,
        Ast.Query ast,
        LogicalPlan logicalPlan,
        LogicalPlan.AccessPathDecision accessPath,
        String sql,
        List<Object> bindings,
        int lookback,
        List<WindowSpec> windowSpecs,
        List<IndicatorVersion> indicatorVersions,
        List<RuleTrace> ruleTrace,
        List<Diagnostic> diagnostics
) {
    public CompilationArtifact {
        bindings = List.copyOf(bindings);
        windowSpecs = List.copyOf(windowSpecs);
        indicatorVersions = List.copyOf(indicatorVersions);
        ruleTrace = List.copyOf(ruleTrace);
        diagnostics = List.copyOf(diagnostics);
    }
    public int requiredLookbackTradingDays() { return lookback; }
    @JsonIgnore
    public String ruleConfigVersion() { return ruleSetVersion; }

    public record CacheKey(String sourceHash, String compilerVersion, String metadataVersion) {}

    public record RuleTrace(String ruleId, String configVersion, String phase, int iteration,
                            String inputNodeType, String outputNodeType, int priority,
                            String conflictResolution, String equivalence, String description,
                            String semanticProofTag, String version) {
        public RuleTrace(String ruleId, String configVersion, String phase, int iteration,
                         String inputNodeType, String outputNodeType, int priority,
                         String conflictResolution, String equivalence, String description) {
            this(ruleId, configVersion, phase, iteration, inputNodeType, outputNodeType, priority,
                    conflictResolution, equivalence, description, equivalence, configVersion);
        }

        public RuleTrace(String ruleId, String description, String semanticProofTag, int priority, String version) {
            this(ruleId, version, "REWRITE", 1, "AST", "AST", priority,
                    "NONE", semanticProofTag, description, semanticProofTag, version);
        }

        public RuleTrace(String ruleId, String description) {
            this(ruleId, "compiler-builtin", "PLAN", 1, "LOGICAL_PLAN", "LOGICAL_PLAN", 0,
                    "NONE", "PLAN_EQUIVALENCE", description, "PLAN_EQUIVALENCE", "compiler-builtin");
        }
    }
    public record Diagnostic(String severity, String code, String message) {}
    public record IndicatorVersion(String name, String version) {}
}
