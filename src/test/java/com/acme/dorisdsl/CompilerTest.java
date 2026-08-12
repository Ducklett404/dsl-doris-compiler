package com.acme.dorisdsl;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.util.JsonSupport;
import com.acme.dorisdsl.util.MarkdownRenderer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class CompilerTest {
    private DslCompiler compiler;

    @BeforeEach void setUp() {
        compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    }

    @Test void compilesComplexDslIntoLayeredParameterizedDorisSql() {
        var artifact = compiler.compile(sampleDsl());
        assertEquals(21, artifact.requiredLookbackTradingDays());
        assertEquals(Ast.DataType.BOOLEAN, artifact.ast().where().type());
        assertTrue(artifact.sql().contains("WITH base AS"));
        assertTrue(artifact.sql().contains("metrics AS"));
        assertTrue(artifact.sql().contains("signals AS"));
        assertEquals(2, occurrences(artifact.sql(), "AVG("));
        assertEquals(2, occurrences(artifact.sql(), "LAG("));
        assertFalse(artifact.sql().contains("LAG(AVG("), "window functions must be layered");
        assertFalse(artifact.sql().contains("'SH'"), "user values must be bound");
        assertFalse(artifact.sql().contains("15%"));
        assertEquals(8, artifact.bindings().size());
        assertEquals(6, artifact.logicalPlan().accessPath().candidates().size());
    }

    @Test void serializesAstAndRendersMarkdown() throws Exception {
        var artifact = compiler.compile(sampleDsl());
        String json = JsonSupport.MAPPER.writeValueAsString(artifact);
        String markdown = MarkdownRenderer.render(artifact);
        assertTrue(json.contains("\"kind\" : \"FunctionCall\""));
        assertTrue(markdown.contains("## Doris SQL"));
        assertTrue(markdown.contains("| Access path | " + artifact.logicalPlan().accessPath().selected() + " |"));
    }

    @Test void rejectsUnknownFunctionsAndSqlInjectionTokens() {
        CompileException unknown = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE EVIL(CLOSE) > 1 LIMIT 5"));
        assertEquals("UNKNOWN_FUNCTION", unknown.code());
        assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 1; DROP TABLE x"));
    }

    @Test void rejectsWrongTypesAndExtremeLimit() {
        assertEquals("TYPE_MISMATCH", assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE MARKET > 1 LIMIT 5")).code());
        assertEquals("LIMIT_RANGE", assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 1 LIMIT 10001")).code());
    }

    static String sampleDsl() {
        return """
                SCREEN ON 2026-08-07
                WHERE PE_TTM() BETWEEN 0 AND 20
                  AND ROE_TTM() >= 15%
                  AND CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
                  AND MARKET IN ['SH', 'SZ']
                ADJUST FORWARD
                ORDER BY TURNOVER_RATE DESC
                LIMIT 100
                """;
    }

    private static int occurrences(String value, String token) {
        int count = 0, from = 0;
        while ((from = value.indexOf(token, from)) >= 0) { count++; from += token.length(); }
        return count;
    }
}
