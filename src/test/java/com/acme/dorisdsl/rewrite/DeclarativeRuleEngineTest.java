package com.acme.dorisdsl.rewrite;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class DeclarativeRuleEngineTest {
    private static final String DSL = "SCREEN ON 2026-08-07 WHERE CLOSE > 1 + 2 * 3 LIMIT 5";

    @Test void loadsDefaultRulesAndEmitsCompleteTrace() {
        var artifact = compiler().compile(DSL);
        assertEquals("rules-v1", artifact.ruleConfigVersion());
        assertEquals(2, artifact.ruleTrace().stream().filter(t -> t.ruleId().equals("R-001")).count());
        var trace = artifact.ruleTrace().stream().filter(t -> t.ruleId().equals("R-001")).findFirst().orElseThrow();
        assertEquals("SIMPLIFY", trace.phase());
        assertEquals("BINARY", trace.inputNodeType());
        assertEquals("LITERAL", trace.outputNodeType());
        assertFalse(trace.equivalence().isBlank());
        assertEquals("NONE", trace.conflictResolution());
        var where = (Ast.Binary) artifact.ast().where();
        assertEquals("7", ((Ast.Literal) where.right()).value().toString());
    }

    @Test void producesDeterministicSqlBindingsAstAndTrace() throws Exception {
        var compiler = compiler();
        String expected = JsonSupport.MAPPER.writeValueAsString(compiler.compile(DSL));
        for (int i = 0; i < 25; i++) assertEquals(expected,
                JsonSupport.MAPPER.writeValueAsString(compiler.compile(DSL)));
    }

    @Test void activatesAndRollsBackImmutableVersions() {
        var compiler = compiler();
        assertInstanceOf(Ast.Literal.class, ((Ast.Binary) compiler.compile(DSL).ast().where()).right());
        compiler.activateRuleVersion("rules-v0");
        assertEquals("rules-v0", compiler.activeRuleVersion());
        assertInstanceOf(Ast.Binary.class, ((Ast.Binary) compiler.compile(DSL).ast().where()).right());
        assertEquals("rules-v1", compiler.rollbackRuleVersion());
        assertInstanceOf(Ast.Literal.class, ((Ast.Binary) compiler.compile(DSL).ast().where()).right());
    }

    @Test void resolvesConflictsByPriorityWithDeterministicTieBreaker() {
        var manager = manager(4, RuleCatalog.ConflictPolicy.HIGHEST_PRIORITY,
                fold("R-HIGH", 100), fold("R-LOW", 10));
        var compiler = compiler(manager);
        var artifact = compiler.compile(DSL);
        var trace = artifact.ruleTrace().stream().filter(t -> t.ruleId().equals("R-HIGH")).findFirst().orElseThrow();
        assertTrue(trace.conflictResolution().contains("R-HIGH>R-LOW"));
        assertTrue(artifact.ruleTrace().stream().noneMatch(t -> t.ruleId().equals("R-LOW")));
    }

    @Test void rejectsConfiguredConflictWhenPolicyIsError() {
        var compiler = compiler(manager(4, RuleCatalog.ConflictPolicy.ERROR,
                fold("R-A", 100), fold("R-B", 10)));
        assertEquals("RULE_CONFLICT", assertThrows(CompileException.class, () -> compiler.compile(DSL)).code());
    }

    @Test void stopsAtIterationLimitAndDetectsCycles() {
        var limited = compiler(manager(1, RuleCatalog.ConflictPolicy.HIGHEST_PRIORITY, fold("R-FOLD", 100)));
        assertEquals("RULE_ITERATION_LIMIT", assertThrows(CompileException.class, () -> limited.compile(DSL)).code());

        var swap = new RuleCatalog.RuleDefinition("R-SWAP", true, RuleCatalog.Phase.SIMPLIFY, 10,
                RuleCatalog.NodeType.BINARY, RuleCatalog.NodeType.BINARY, "canonical-order",
                new RuleCatalog.RuleCondition(List.of("+"), false, false, true),
                RuleCatalog.Action.SWAP_COMMUTATIVE_OPERANDS, "a+b is equivalent to b+a", "Cycle test rule");
        var cyclic = compiler(manager(16, RuleCatalog.ConflictPolicy.HIGHEST_PRIORITY, swap));
        assertEquals("RULE_CYCLE", assertThrows(CompileException.class, () -> cyclic.compile(DSL)).code());
    }

    @Test void validatesUnknownPropertiesAndCompilerCompatibility() throws Exception {
        Path file = Path.of("target", "invalid-rules-" + UUID.randomUUID() + ".json");
        Files.createDirectories(file.getParent());
        Files.writeString(file, "{\"schemaVersion\":1,\"activeVersion\":\"x\",\"versions\":[],\"unknown\":true}",
                StandardCharsets.UTF_8);
        try {
            assertEquals("RULE_CONFIG_INVALID", assertThrows(CompileException.class,
                    () -> new RuleCatalogLoader().load(file, DslCompiler.VERSION)).code());
        } finally { Files.deleteIfExists(file); }

        var incompatible = new RuleCatalog(1, "future", List.of(new RuleCatalog.RuleSet("future", "1.0.0",
                "2.0.0", 2, RuleCatalog.ConflictPolicy.HIGHEST_PRIORITY, List.of())));
        assertEquals("RULE_VERSION_INCOMPATIBLE", assertThrows(CompileException.class,
                () -> new RuleCatalogManager(incompatible, DslCompiler.VERSION)).code());
    }

    private static DslCompiler compiler() {
        return new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    }

    private static DslCompiler compiler(RuleCatalogManager manager) {
        return new DslCompiler(new RegistryLoader().loadDefault(List.of()), manager);
    }

    private static RuleCatalogManager manager(int iterations, RuleCatalog.ConflictPolicy policy,
                                              RuleCatalog.RuleDefinition... rules) {
        var set = new RuleCatalog.RuleSet("test-v1", "0.1.0", "1.0.0", iterations, policy, List.of(rules));
        return new RuleCatalogManager(new RuleCatalog(1, "test-v1", List.of(set)), DslCompiler.VERSION);
    }

    private static RuleCatalog.RuleDefinition fold(String id, int priority) {
        return new RuleCatalog.RuleDefinition(id, true, RuleCatalog.Phase.SIMPLIFY, priority,
                RuleCatalog.NodeType.BINARY, RuleCatalog.NodeType.LITERAL, "constant-evaluation",
                new RuleCatalog.RuleCondition(List.of("+", "-", "*", "/"), true, true, false),
                RuleCatalog.Action.FOLD_NUMERIC_BINARY, "constant arithmetic equivalence", "Fold constants");
    }
}
