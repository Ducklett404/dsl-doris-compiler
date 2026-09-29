package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.catalog.CatalogSnapshotLoader;
import com.acme.dorisdsl.parser.DslParserFacade;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.rewrite.RuleCatalogLoader;
import com.acme.dorisdsl.rewrite.RuleCatalogManager;
import com.acme.dorisdsl.rewrite.RuleEngine;
import com.acme.dorisdsl.security.CompilationSecurity;
import com.acme.dorisdsl.security.SecurityAudit;
import com.acme.dorisdsl.security.SecurityAuditLog;
import com.acme.dorisdsl.security.SecurityPolicy;
import com.acme.dorisdsl.semantic.SemanticAnalyzer;
import com.acme.dorisdsl.sql.DorisSqlGenerator;
import com.acme.dorisdsl.stockslot.StockSlotCompiler;

import java.util.ArrayList;
import java.util.List;

public final class DslCompiler {
    public static final String VERSION = "0.1.0";
    public static final String SCREEN_DSL_VERSION = "screen-v1";
    public static final String STOCK_SLOT_DSL_VERSION = StockSlotCompiler.DSL_VERSION;
    public static final String DEFAULT_DORIS_CAPABILITY_VERSION = "doris-2.1";

    private final DslParserFacade parser = new DslParserFacade();
    private final SemanticAnalyzer semanticAnalyzer;
    private final RuleEngine ruleEngine = new RuleEngine();
    private final RuleCatalogManager ruleCatalog;
    private final DorisSqlGenerator sqlGenerator;
    private final StockSlotCompiler stockSlotCompiler = new StockSlotCompiler();
    private final CompilerVersions versions;
    private final String metadataVersion;
    private final CompilationCache cache;
    private final NormalizedAstHasher hasher;
    private final CompilationSecurity security;
    private final SecurityAuditLog auditLog;

    public DslCompiler(Registry registry) {
        this(registry, new CatalogSnapshotLoader().loadDefault(),
                new RuleCatalogLoader().loadDefault(VERSION));
    }

    private DslCompiler(Registry registry, CatalogSnapshot catalogSnapshot, RuleCatalogManager ruleCatalog) {
        this(registry, catalogSnapshot,
                new CompilerVersions(ruleCatalog.activeVersion(),
                        catalogSnapshot.version() + ":" + registry.catalogVersion(),
                        "doris-" + catalogSnapshot.doris().version()),
                new CompilationCache(1_024), SecurityPolicy.defaults(), new SecurityAuditLog(10_000),
                catalogSnapshot.version(), ruleCatalog);
    }

    public DslCompiler(Registry registry, CatalogSnapshot catalogSnapshot) {
        this(registry, catalogSnapshot,
                new CompilerVersions(RuleEngine.VERSION,
                        catalogSnapshot.version() + ":" + registry.catalogVersion(),
                        "doris-" + catalogSnapshot.doris().version()),
                new CompilationCache(1_024), SecurityPolicy.defaults(), new SecurityAuditLog(10_000),
                catalogSnapshot.version(), null);
    }

    public DslCompiler(Registry registry, RuleCatalogManager ruleCatalog) {
        this(registry, new CatalogSnapshotLoader().loadDefault(),
                new CompilerVersions(ruleCatalog.activeVersion(), registry.catalogVersion(), DEFAULT_DORIS_CAPABILITY_VERSION),
                new CompilationCache(1_024), SecurityPolicy.defaults(), new SecurityAuditLog(10_000),
                registry.catalogVersion(), ruleCatalog);
    }

    public DslCompiler(Registry registry, CompilerVersions versions, CompilationCache cache) {
        this(registry, new CatalogSnapshotLoader().loadDefault(), versions, cache,
                SecurityPolicy.defaults(), new SecurityAuditLog(10_000), versions.catalogVersion(), null);
    }

    public DslCompiler(Registry registry, CompilerVersions versions, CompilationCache cache,
                       SecurityPolicy securityPolicy) {
        this(registry, new CatalogSnapshotLoader().loadDefault(), versions, cache,
                securityPolicy, new SecurityAuditLog(10_000), versions.catalogVersion(), null);
    }

    public DslCompiler(Registry registry, CompilerVersions versions, CompilationCache cache,
                       SecurityPolicy securityPolicy, SecurityAuditLog auditLog) {
        this(registry, new CatalogSnapshotLoader().loadDefault(), versions, cache,
                securityPolicy, auditLog, versions.catalogVersion(), null);
    }

    public DslCompiler(Registry registry, CatalogSnapshot catalogSnapshot, CompilerVersions versions,
                       CompilationCache cache, SecurityPolicy securityPolicy, SecurityAuditLog auditLog) {
        this(registry, catalogSnapshot, versions, cache, securityPolicy, auditLog, versions.catalogVersion(), null);
    }

    private DslCompiler(Registry registry, CatalogSnapshot catalogSnapshot, CompilerVersions versions,
                        CompilationCache cache, SecurityPolicy securityPolicy, SecurityAuditLog auditLog,
                        String metadataVersion, RuleCatalogManager ruleCatalog) {
        this.versions = versions;
        this.metadataVersion = metadataVersion;
        this.cache = cache;
        this.semanticAnalyzer = new SemanticAnalyzer(registry);
        this.sqlGenerator = new DorisSqlGenerator(registry, catalogSnapshot);
        this.hasher = new NormalizedAstHasher(registry);
        this.security = new CompilationSecurity(securityPolicy);
        this.auditLog = auditLog;
        this.ruleCatalog = ruleCatalog;
    }

    public String activeRuleVersion() { return requireRuleCatalog().activeVersion(); }
    public void activateRuleVersion(String version) { requireRuleCatalog().activate(version); }
    public String rollbackRuleVersion() { return requireRuleCatalog().rollback(); }
    public void rollbackRuleVersion(String version) { requireRuleCatalog().rollbackTo(version); }

    private RuleCatalogManager requireRuleCatalog() {
        if (ruleCatalog == null) throw new IllegalStateException("No declarative rule catalog configured");
        return ruleCatalog;
    }

    public CompilationArtifact compile(String dsl) {
        if (dsl == null || dsl.isBlank())
            throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
        if (dsl.length() > 100_000)
            throw new CompileException("DSL_TOO_LARGE", "DSL exceeds 100000 characters", 1, 1);
        security.validateDsl(dsl);

        Ast.Query parsed = parser.parse(dsl);
        Ast.Query typed = semanticAnalyzer.analyze(parsed);
        Ast.Query ast;
        List<CompilationArtifact.RuleTrace> rewrittenTrace;
        String ruleSetVersion;
        if (ruleCatalog == null) {
            RuleEngine.Result rewritten = ruleEngine.rewrite(typed);
            ast = rewritten.query();
            rewrittenTrace = rewritten.trace();
            ruleSetVersion = versions.ruleSetVersion();
        } else {
            var declarative = ruleCatalog.engine().rewrite(typed);
            var combined = new ArrayList<CompilationArtifact.RuleTrace>(declarative.trace());
            if ("rules-v1".equals(declarative.ruleConfigVersion())) {
                var canonical = ruleEngine.rewrite(declarative.query());
                ast = canonical.query();
                combined.addAll(canonical.trace());
            } else {
                ast = declarative.query();
            }
            rewrittenTrace = List.copyOf(combined);
            ruleSetVersion = declarative.ruleConfigVersion();
        }

        String normalizedHash = hasher.hash(ast);
        CompilationCache.CacheKey key = new CompilationCache.CacheKey(normalizedHash,
                ruleSetVersion, versions.catalogVersion(), versions.dorisCapabilityVersion());
        CompilationCache.CachedCompilation cached = cache.get(key);
        if (cached != null) {
            DorisSqlGenerator.Result rebound = sqlGenerator.generate(ast);
            if (cached.sql().equals(rebound.sql()))
                return artifact(normalizedHash, ruleSetVersion, ast, cached, rebound.bindings());
        }

        DorisSqlGenerator.Result generated = sqlGenerator.generate(ast);
        List<CompilationArtifact.RuleTrace> trace = completeTrace(rewrittenTrace);
        CompilationCache.CachedCompilation compiled = new CompilationCache.CachedCompilation(
                generated.logicalPlan(), generated.sql(), generated.diagnostics(), trace,
                generated.lookback(), generated.windowSpecs(), generated.indicatorVersions());
        cache.put(key, compiled);
        return artifact(normalizedHash, ruleSetVersion, ast, compiled, generated.bindings());
    }

    public Object compile(String dsl, String dslVersion) {
        String version = dslVersion == null || dslVersion.isBlank() ? SCREEN_DSL_VERSION : dslVersion;
        return switch (version) {
            case SCREEN_DSL_VERSION -> compile(dsl);
            case STOCK_SLOT_DSL_VERSION -> stockSlotCompiler.classify(dsl);
            default -> throw new CompileException("UNSUPPORTED_DSL_VERSION",
                    "Unsupported dslVersion: " + version, 1, 1);
        };
    }

    public CompilationCache.Stats cacheStats() { return cache.stats(); }
    public CompilerVersions versions() { return versions; }
    public List<SecurityAudit> securityAudits() { return auditLog.snapshot(); }

    private List<CompilationArtifact.RuleTrace> completeTrace(List<CompilationArtifact.RuleTrace> rewrittenTrace) {
        var trace = new ArrayList<>(rewrittenTrace);
        trace.add(new CompilationArtifact.RuleTrace("R-101", "Pruned projection to referenced fields and generated metrics",
                "PROJECTION_EQUIVALENCE", 200, "1.0.0"));
        trace.add(new CompilationArtifact.RuleTrace("R-102", "Shared common metric expressions by stable function signature",
                "COMMON_SUBEXPRESSION", 210, "1.0.0"));
        trace.add(new CompilationArtifact.RuleTrace("R-103", "Merged windows with identical partition and order keys",
                "WINDOW_EQUIVALENCE", 220, "1.0.0"));
        trace.add(new CompilationArtifact.RuleTrace("R-104", "Deduplicated common window expressions and emitted layered CTEs",
                "WINDOW_LAYERING", 230, "1.0.0"));
        return List.copyOf(trace);
    }

    private CompilationArtifact artifact(String normalizedHash, String ruleSetVersion, Ast.Query ast,
                                         CompilationCache.CachedCompilation compiled, List<Object> bindings) {
        var audit = security.auditAndEnforce(compiled.sql(), bindings,
                compiled.logicalPlan(), compiled.lookback());
        auditLog.append(audit);
        return new CompilationArtifact(VERSION, ruleSetVersion, metadataVersion,
                new CompilationArtifact.CacheKey(normalizedHash, VERSION, metadataVersion),
                ast, compiled.logicalPlan(), compiled.logicalPlan().accessPath(), compiled.sql(), bindings,
                compiled.lookback(), compiled.windowSpecs(), compiled.indicatorVersions(),
                compiled.ruleTrace(), compiled.diagnostics());
    }
}
