package com.acme.dorisdsl.plan;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.registry.RegistryConfig;

import java.util.ArrayList;
import java.util.List;

public final class AccessPathPlanner {
    private final Registry registry;

    public AccessPathPlanner(Registry registry) { this.registry = registry; }

    public LogicalPlan.AccessPathDecision choose(Ast.Query query, int lookback) {
        boolean hasWindow = containsKind(query.where(), RegistryConfig.LoweringKind.WINDOW_AVG);
        boolean allFeatureBacked = allFunctionsFeatureBacked(query.where());
        List<LogicalPlan.Candidate> candidates = new ArrayList<>();
        candidates.add(new LogicalPlan.Candidate("DETAIL_TABLE", 100 + lookback * 2.0, true,
                "Always semantically complete; cost grows with window lookback"));
        candidates.add(new LogicalPlan.Candidate("FEATURE_TABLE", allFeatureBacked ? 12 : 9999, allFeatureBacked,
                allFeatureBacked ? "Every referenced indicator has a registered feature column" : "At least one indicator lacks a feature column"));
        candidates.add(new LogicalPlan.Candidate("PREFIX_SUM", hasWindow ? 35 : 9999, hasWindow,
                hasWindow ? "Window aggregate may be lowered to prefix sums in the next data-model iteration" : "No additive window aggregate"));
        String selected = allFeatureBacked ? "FEATURE_TABLE" : "DETAIL_TABLE";
        String reason = allFeatureBacked ? "Selected lowest-cost fully covered feature path" : "Selected correctness-first detail path";
        return new LogicalPlan.AccessPathDecision(selected, candidates, reason);
    }

    private boolean containsKind(Ast.Expr expr, RegistryConfig.LoweringKind kind) {
        if (expr == null) return false;
        if (expr instanceof Ast.FunctionCall call) {
            if (registry.function(call.name(), call.span().line(), call.span().column()).loweringKind() == kind) return true;
            return call.arguments().stream().anyMatch(e -> containsKind(e, kind));
        }
        if (expr instanceof Ast.Binary e) return containsKind(e.left(), kind) || containsKind(e.right(), kind);
        if (expr instanceof Ast.Unary e) return containsKind(e.operand(), kind);
        if (expr instanceof Ast.Between e) return containsKind(e.value(), kind) || containsKind(e.lower(), kind) || containsKind(e.upper(), kind);
        if (expr instanceof Ast.InList e) return containsKind(e.value(), kind) || e.options().stream().anyMatch(v -> containsKind(v, kind));
        return false;
    }

    private boolean allFunctionsFeatureBacked(Ast.Expr expr) {
        if (expr == null) return false;
        List<Ast.FunctionCall> calls = new ArrayList<>();
        collect(expr, calls);
        return !calls.isEmpty() && calls.stream().allMatch(call -> {
            var fn = registry.function(call.name(), call.span().line(), call.span().column());
            return fn.featureColumn() != null && !fn.featureColumn().isBlank();
        });
    }

    private void collect(Ast.Expr expr, List<Ast.FunctionCall> out) {
        if (expr instanceof Ast.FunctionCall call) { out.add(call); call.arguments().forEach(e -> collect(e, out)); }
        else if (expr instanceof Ast.Binary e) { collect(e.left(), out); collect(e.right(), out); }
        else if (expr instanceof Ast.Unary e) collect(e.operand(), out);
        else if (expr instanceof Ast.Between e) { collect(e.value(), out); collect(e.lower(), out); collect(e.upper(), out); }
        else if (expr instanceof Ast.InList e) { collect(e.value(), out); e.options().forEach(v -> collect(v, out)); }
    }
}
