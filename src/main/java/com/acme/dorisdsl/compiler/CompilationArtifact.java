package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.plan.LogicalPlan;
import com.acme.dorisdsl.plan.WindowSpec;

import java.util.List;

public record CompilationArtifact(
        String compilerVersion,
        String metadataVersion,
        CacheKey cacheKey,
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
    public record CacheKey(String sourceHash, String compilerVersion, String metadataVersion) {}
    public record RuleTrace(String ruleId, String description) {}
    public record Diagnostic(String severity, String code, String message) {}
}
