package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.catalog.CatalogSnapshotLoader;
import com.acme.dorisdsl.parser.DslParserFacade;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.rewrite.RuleEngine;
import com.acme.dorisdsl.semantic.SemanticAnalyzer;
import com.acme.dorisdsl.sql.DorisSqlGenerator;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.concurrent.ConcurrentHashMap;

public final class DslCompiler {
    public static final String VERSION = "0.1.0";
    private final DslParserFacade parser = new DslParserFacade();
    private final SemanticAnalyzer semanticAnalyzer;
    private final RuleEngine ruleEngine = new RuleEngine();
    private final DorisSqlGenerator sqlGenerator;
    private final CatalogSnapshot catalogSnapshot;
    private final ConcurrentHashMap<CompilationArtifact.CacheKey, CompilationArtifact> cache = new ConcurrentHashMap<>();

    public DslCompiler(Registry registry) {
        this(registry, new CatalogSnapshotLoader().loadDefault());
    }

    public DslCompiler(Registry registry, CatalogSnapshot catalogSnapshot) {
        this.catalogSnapshot = catalogSnapshot;
        this.semanticAnalyzer = new SemanticAnalyzer(registry);
        this.sqlGenerator = new DorisSqlGenerator(registry, catalogSnapshot);
    }

    public CompilationArtifact compile(String dsl) {
        if (dsl == null || dsl.isBlank()) throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
        if (dsl.length() > 100_000) throw new CompileException("DSL_TOO_LARGE", "DSL exceeds 100000 characters", 1, 1);
        var cacheKey = new CompilationArtifact.CacheKey(hash(dsl), VERSION, catalogSnapshot.version());
        return cache.computeIfAbsent(cacheKey, ignored -> compileUncached(dsl, cacheKey));
    }

    private CompilationArtifact compileUncached(String dsl, CompilationArtifact.CacheKey cacheKey) {
        var parsed = parser.parse(dsl);
        var typed = semanticAnalyzer.analyze(parsed);
        var rewritten = ruleEngine.rewrite(typed);
        var generated = sqlGenerator.generate(rewritten.query());
        var trace = new ArrayList<>(rewritten.trace());
        trace.add(new CompilationArtifact.RuleTrace("R-101", "Pruned projection to referenced fields and generated metrics",
                "PROJECTION_EQUIVALENCE", 200, "1.0.0"));
        trace.add(new CompilationArtifact.RuleTrace("R-102", "Shared common metric expressions by stable function signature",
                "COMMON_SUBEXPRESSION", 210, "1.0.0"));
        trace.add(new CompilationArtifact.RuleTrace("R-103", "Merged windows with identical partition and order keys",
                "WINDOW_EQUIVALENCE", 220, "1.0.0"));
        trace.add(new CompilationArtifact.RuleTrace("R-104", "Deduplicated common window expressions and emitted layered CTEs",
                "WINDOW_LAYERING", 230, "1.0.0"));
        return new CompilationArtifact(VERSION, catalogSnapshot.version(), cacheKey,
                rewritten.query(), generated.logicalPlan(), generated.sql(),
                generated.bindings(), generated.lookback(), generated.windowSpecs(),
                generated.indicatorVersions(), trace, generated.diagnostics());
    }

    private String hash(String source) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(source.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }
}
