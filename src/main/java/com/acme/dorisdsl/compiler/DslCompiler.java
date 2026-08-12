package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.parser.DslParserFacade;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.registry.RegistryConfig;
import com.acme.dorisdsl.rewrite.RuleEngine;
import com.acme.dorisdsl.semantic.SemanticAnalyzer;
import com.acme.dorisdsl.sql.DorisSqlGenerator;
import com.acme.dorisdsl.security.CompilationSecurity;
import com.acme.dorisdsl.security.SecurityPolicy;
import com.acme.dorisdsl.security.SecurityAudit;
import com.acme.dorisdsl.security.SecurityAuditLog;

import java.util.ArrayList;
import java.util.List;

public final class DslCompiler {
    public static final String VERSION = "0.1.0";
    public static final String DEFAULT_DORIS_CAPABILITY_VERSION = "doris-2.1";
    private final DslParserFacade parser = new DslParserFacade();
    private final SemanticAnalyzer semanticAnalyzer;
    private final RuleEngine ruleEngine = new RuleEngine();
    private final DorisSqlGenerator sqlGenerator;
    private final Registry registry;
    private final CompilerVersions versions;
    private final CompilationCache cache;
    private final NormalizedAstHasher hasher;
    private final CompilationSecurity security;
    private final SecurityAuditLog auditLog;

    public DslCompiler(Registry registry) {
        this(registry, new CompilerVersions(RuleEngine.VERSION, registry.catalogVersion(),
                DEFAULT_DORIS_CAPABILITY_VERSION), new CompilationCache(1_024), SecurityPolicy.defaults(),
                new SecurityAuditLog(10_000));
    }

    public DslCompiler(Registry registry, CompilerVersions versions, CompilationCache cache) {
        this(registry, versions, cache, SecurityPolicy.defaults(), new SecurityAuditLog(10_000));
    }

    public DslCompiler(Registry registry, CompilerVersions versions, CompilationCache cache, SecurityPolicy securityPolicy) {
        this(registry, versions, cache, securityPolicy, new SecurityAuditLog(10_000));
    }

    public DslCompiler(Registry registry, CompilerVersions versions, CompilationCache cache,
                       SecurityPolicy securityPolicy, SecurityAuditLog auditLog) {
        this.registry = registry;
        this.versions = versions;
        this.cache = cache;
        this.semanticAnalyzer = new SemanticAnalyzer(registry);
        this.sqlGenerator = new DorisSqlGenerator(registry);
        this.hasher = new NormalizedAstHasher(registry);
        this.security = new CompilationSecurity(securityPolicy);
        this.auditLog = auditLog;
    }

    public CompilationArtifact compile(String dsl) {
        if (dsl == null || dsl.isBlank()) throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
        if (dsl.length() > 100_000) throw new CompileException("DSL_TOO_LARGE", "DSL exceeds 100000 characters", 1, 1);
        security.validateDsl(dsl);
        Ast.Query parsed = parser.parse(dsl);
        Ast.Query typed = semanticAnalyzer.analyze(parsed);
        RuleEngine.Result rewritten = ruleEngine.rewrite(typed);
        Ast.Query ast = rewritten.query();
        CompilationCache.CacheKey key = new CompilationCache.CacheKey(hasher.hash(ast),
                versions.ruleSetVersion(), versions.catalogVersion(), versions.dorisCapabilityVersion());
        CompilationCache.CachedCompilation cached = cache.get(key);
        if (cached != null) {
            List<Object> bindings = new ParameterBindings(registry).extract(ast, cached.lookback());
            return artifact(ast, cached.logicalPlan(), cached.sql(), bindings, cached.diagnostics(),
                    cached.ruleTrace(), cached.lookback());
        }

        DorisSqlGenerator.Result generated = sqlGenerator.generate(ast);
        List<CompilationArtifact.RuleTrace> trace = new ArrayList<>(rewritten.trace());
        trace.add(new CompilationArtifact.RuleTrace("R-104",
                "Deduplicated common window expressions and emitted layered CTEs"));
        CompilationCache.CachedCompilation value = new CompilationCache.CachedCompilation(
                generated.logicalPlan(), generated.sql(), generated.diagnostics(), trace, generated.lookback());
        cache.put(key, value);
        return artifact(ast, value.logicalPlan(), value.sql(), generated.bindings(), value.diagnostics(),
                value.ruleTrace(), value.lookback());
    }

    public CompilationCache.Stats cacheStats() { return cache.stats(); }
    public CompilerVersions versions() { return versions; }
    public List<SecurityAudit> securityAudits() { return auditLog.snapshot(); }

    private CompilationArtifact artifact(Ast.Query ast, com.acme.dorisdsl.plan.LogicalPlan logicalPlan,
                                         String sql, List<Object> bindings,
                                         List<CompilationArtifact.Diagnostic> diagnostics,
                                         List<CompilationArtifact.RuleTrace> trace, int lookback) {
        var securityAudit = security.auditAndEnforce(sql, bindings, logicalPlan, lookback);
        auditLog.append(securityAudit);
        return new CompilationArtifact(ast, logicalPlan, sql, bindings, diagnostics, trace,
                logicalPlan.accessPath(), lookback, VERSION, versions.ruleSetVersion());
    }

    private static final class ParameterBindings {
        private final Registry registry;
        private final List<Object> values = new ArrayList<>();

        private ParameterBindings(Registry registry) { this.registry = registry; }

        private List<Object> extract(Ast.Query query, int lookback) {
            values.add(query.asOf());
            if (lookback > 0) values.add(query.asOf());
            values.add(query.asOf());
            expression(query.where());
            if (query.orderBy() != null) expression(query.orderBy().expression());
            return List.copyOf(values);
        }

        private void expression(Ast.Expr expression) {
            if (expression == null) return;
            switch (expression) {
                case Ast.Literal literal -> values.add(literal.value());
                case Ast.Identifier ignored -> { }
                case Ast.FunctionCall call -> {
                    RegistryConfig.LoweringKind kind = registry.function(call.name(), call.span().line(),
                            call.span().column()).loweringKind();
                    if (kind == RegistryConfig.LoweringKind.TEMPLATE) call.arguments().forEach(this::expression);
                }
                case Ast.Binary binary -> { expression(binary.left()); expression(binary.right()); }
                case Ast.Unary unary -> expression(unary.operand());
                case Ast.Between between -> {
                    expression(between.value()); expression(between.lower()); expression(between.upper());
                }
                case Ast.InList in -> { expression(in.value()); in.options().forEach(this::expression); }
            }
        }
    }
}
