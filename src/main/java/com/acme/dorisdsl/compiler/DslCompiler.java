package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.parser.DslParserFacade;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.rewrite.RuleEngine;
import com.acme.dorisdsl.semantic.SemanticAnalyzer;
import com.acme.dorisdsl.sql.DorisSqlGenerator;

import java.util.ArrayList;

public final class DslCompiler {
    public static final String VERSION = "0.1.0";
    private final DslParserFacade parser = new DslParserFacade();
    private final SemanticAnalyzer semanticAnalyzer;
    private final RuleEngine ruleEngine = new RuleEngine();
    private final DorisSqlGenerator sqlGenerator;

    public DslCompiler(Registry registry) {
        this.semanticAnalyzer = new SemanticAnalyzer(registry);
        this.sqlGenerator = new DorisSqlGenerator(registry);
    }

    public CompilationArtifact compile(String dsl) {
        if (dsl == null || dsl.isBlank()) throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
        if (dsl.length() > 100_000) throw new CompileException("DSL_TOO_LARGE", "DSL exceeds 100000 characters", 1, 1);
        var parsed = parser.parse(dsl);
        var typed = semanticAnalyzer.analyze(parsed);
        var rewritten = ruleEngine.rewrite(typed);
        var generated = sqlGenerator.generate(rewritten.query());
        var trace = new ArrayList<>(rewritten.trace());
        trace.add(new CompilationArtifact.RuleTrace("R-104", "Deduplicated common window expressions and emitted layered CTEs"));
        return new CompilationArtifact(VERSION, rewritten.query(), generated.logicalPlan(), generated.sql(),
                generated.bindings(), generated.lookback(), generated.indicatorVersions(), trace, generated.diagnostics());
    }
}
