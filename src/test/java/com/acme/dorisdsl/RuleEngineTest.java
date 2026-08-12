package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompilationArtifact;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

class RuleEngineTest {
    private DslCompiler compiler;

    @BeforeEach void setUp() {
        compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    }

    @Test void rewritesEquivalentPredicatesToGoldenSqlAndTracesRules() throws Exception {
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE 10 < CLOSE
                  AND TRUE
                  AND CLOSE > (5 + 5)
                  AND MARKET IN ['SH', 'SZ']
                LIMIT 5
                """);

        assertEquals(golden("rule-engine-equivalent.sql"), artifact.sql());
        assertEquals(List.of(java.time.LocalDate.parse("2026-08-07"), java.time.LocalDate.parse("2026-08-07"),
                new java.math.BigDecimal("10"), "SH", "SZ"), artifact.bindings());
        assertRuleTraceComplete(artifact);
        assertHasRule(artifact, "R-001");
        assertHasRule(artifact, "R-002");
        assertHasRule(artifact, "R-003");
        assertHasRule(artifact, "R-004");
    }

    @Test void commonWindowExpressionIsSharedAndMatchesGoldenSql() throws Exception {
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE MA(CLOSE, 5) > 10
                  AND MA(CLOSE, 5) > 10
                LIMIT 5
                """);

        assertEquals(golden("rule-engine-window.sql"), artifact.sql());
        assertEquals(1, occurrences(artifact.sql(), "AVG("));
        assertRuleTraceComplete(artifact);
        assertHasRule(artifact, "R-102");
        assertHasRule(artifact, "R-103");
        assertHasRule(artifact, "R-104");
    }

    private void assertRuleTraceComplete(CompilationArtifact artifact) {
        for (CompilationArtifact.RuleTrace trace : artifact.ruleTrace()) {
            assertFalse(trace.ruleId().isBlank());
            assertFalse(trace.description().isBlank());
            assertFalse(trace.semanticProofTag().isBlank(), trace.ruleId() + " missing semanticProofTag");
            assertTrue(trace.priority() > 0, trace.ruleId() + " missing priority");
            assertFalse(trace.version().isBlank(), trace.ruleId() + " missing version");
        }
    }

    private void assertHasRule(CompilationArtifact artifact, String ruleId) {
        Map<String, List<CompilationArtifact.RuleTrace>> byRule = artifact.ruleTrace().stream()
                .collect(Collectors.groupingBy(CompilationArtifact.RuleTrace::ruleId));
        assertTrue(byRule.containsKey(ruleId), "missing trace for " + ruleId);
    }

    private String golden(String name) throws Exception {
        return Files.readString(Path.of(getClass().getResource("/golden/" + name).toURI())).trim();
    }

    private static int occurrences(String value, String token) {
        int count = 0, from = 0;
        while ((from = value.indexOf(token, from)) >= 0) { count++; from += token.length(); }
        return count;
    }
}
