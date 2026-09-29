package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.parser.DslParserFacade;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.rewrite.RuleEngine;
import com.acme.dorisdsl.rewrite.RuleCatalogLoader;
import com.acme.dorisdsl.rewrite.RuleCatalogManager;
import com.acme.dorisdsl.semantic.SemanticAnalyzer;
import com.acme.dorisdsl.sql.DorisSqlGenerator;
import com.acme.dorisdsl.stockslot.StockSlotCompiler;

import java.util.ArrayList;

public final class DslCompiler {
    public static final String VERSION = "0.1.0";
    public static final String SCREEN_DSL_VERSION = "screen-v1";
    public static final String STOCK_SLOT_DSL_VERSION = StockSlotCompiler.DSL_VERSION;
    private final DslParserFacade parser = new DslParserFacade();
    private final SemanticAnalyzer semanticAnalyzer;
    private final RuleCatalogManager ruleCatalog;
    private final DorisSqlGenerator sqlGenerator;
    private final StockSlotCompiler stockSlotCompiler = new StockSlotCompiler();

    public DslCompiler(Registry registry) {
        this(registry, new RuleCatalogLoader().loadDefault(VERSION));
    }

    public DslCompiler(Registry registry, RuleCatalogManager ruleCatalog) {
        this.semanticAnalyzer = new SemanticAnalyzer(registry);
        this.sqlGenerator = new DorisSqlGenerator(registry);
        this.ruleCatalog = ruleCatalog;
    }

    public String activeRuleVersion() { return ruleCatalog.activeVersion(); }
    public void activateRuleVersion(String version) { ruleCatalog.activate(version); }
    public String rollbackRuleVersion() { return ruleCatalog.rollback(); }
    public void rollbackRuleVersion(String version) { ruleCatalog.rollbackTo(version); }

    public CompilationArtifact compile(String dsl) {
        if (dsl == null) throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
        if (dsl.length() > 100_000) throw new CompileException("DSL_TOO_LARGE", "DSL exceeds 100000 characters", 1, 1);
        if (dsl.isBlank()) throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
        var parsed = parser.parse(dsl);
        var typed = semanticAnalyzer.analyze(parsed);
        var rewritten = ruleCatalog.engine().rewrite(typed);
        var generated = sqlGenerator.generate(rewritten.query());
        var trace = new ArrayList<>(rewritten.trace());
        trace.add(new CompilationArtifact.RuleTrace("R-104", "Deduplicated common window expressions and emitted layered CTEs"));
        return new CompilationArtifact(VERSION, rewritten.ruleConfigVersion(), rewritten.query(), generated.logicalPlan(), generated.sql(),
                generated.bindings(), generated.lookback(), generated.windowSpecs(), trace, generated.diagnostics());
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
}
