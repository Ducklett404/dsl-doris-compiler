package com.acme.dorisdsl;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.semantic.SemanticAnalyzer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class MinimumSyntaxTest {
    private DslCompiler compiler;

    @BeforeEach void setUp() {
        compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    }

    @Test void supportsIsNullAndIsNotNullPredicates() {
        var isNull = compiler.compile("SCREEN ON 2026-08-07 WHERE PE_TTM() IS NULL LIMIT 5");
        assertTrue(isNull.sql().contains("`pe_ttm` IS NULL"));
        assertInstanceOf(Ast.IsNull.class, isNull.ast().where());

        var isNotNull = compiler.compile("SCREEN ON 2026-08-07 WHERE ROE_TTM() IS NOT NULL LIMIT 5");
        assertTrue(isNotNull.sql().contains("`roe_ttm` IS NOT NULL"));
    }

    @Test void rejectsMalformedIsNullWithSourceLocation() {
        CompileException error = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07\nWHERE CLOSE IS MISSING\nLIMIT 5"));
        assertEquals("DSL_SYNTAX", error.code());
        assertEquals(2, error.line());
        assertTrue(error.column() > 1);
    }

    @Test void supportsExplicitTradingDayWindowUnit() {
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE CROSS_UP(MA(CLOSE, 5, unit=TRADING_DAY), MA(CLOSE, 20, unit=TRADING_DAY))
                LIMIT 5
                """);
        assertEquals(21, artifact.requiredLookbackTradingDays());
        assertTrue(artifact.sql().contains("ROWS BETWEEN 4 PRECEDING AND CURRENT ROW"));
        assertTrue(artifact.sql().contains("ROWS BETWEEN 19 PRECEDING AND CURRENT ROW"));
    }

    @Test void rejectsUnsupportedWindowUnitAndOversizedWindow() {
        CompileException unit = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE MA(CLOSE, 5, unit=NATURAL_DAY) > 1 LIMIT 5"));
        assertEquals("WINDOW_UNIT", unit.code());
        assertEquals(1, unit.line());

        CompileException window = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE MA(CLOSE, 501, unit=TRADING_DAY) > 1 LIMIT 5"));
        assertEquals("WINDOW_RANGE", window.code());
        assertTrue(window.column() > 1);
    }

    @Test void supportsCrossSectionalRankBy() {
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE RANK_BY(TURNOVER_RATE) <= 100
                ORDER BY RANK_BY(TURNOVER_RATE, direction='ASC') ASC
                LIMIT 100
                """);
        assertTrue(artifact.sql().contains("DENSE_RANK() OVER (PARTITION BY trade_date ORDER BY `turnover_rate` DESC)"));
        assertTrue(artifact.sql().contains("DENSE_RANK() OVER (PARTITION BY trade_date ORDER BY `turnover_rate` ASC)"));
    }

    @Test void rejectsInvalidRankByDirection() {
        CompileException error = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE RANK_BY(CLOSE, direction='SIDEWAYS') <= 10 LIMIT 5"));
        assertEquals("RANK_DIRECTION", error.code());
        assertEquals(1, error.line());
        assertTrue(error.column() > 1);
    }

    @Test void supportsParameterizedQueryContext() {
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07 USING MARKET IN ['SH', 'SZ'], INDUSTRY='BANK', UNIVERSE='CSI300', USER='alice'
                WHERE CLOSE > 10
                LIMIT 5
                """);
        assertEquals(List.of("SH", "SZ"), artifact.ast().context().values().get("MARKET"));
        assertEquals(List.of("alice"), artifact.ast().context().values().get("USER"));
        assertTrue(artifact.sql().contains("q.market IN (?,?)"));
        assertTrue(artifact.sql().contains("q.industry = ?"));
        assertTrue(artifact.sql().contains("q.universe = ?"));
        assertFalse(artifact.sql().contains("alice"));
    }

    @Test void rejectsUnsupportedContextKeyAndNonStringContextValue() {
        CompileException key = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 USING REGION='CN' WHERE CLOSE > 1 LIMIT 5"));
        assertEquals("CONTEXT_KEY", key.code());

        CompileException value = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 USING MARKET=1 WHERE CLOSE > 1 LIMIT 5"));
        assertEquals("CONTEXT_VALUE", value.code());
    }

    @Test void rejectsOverlongInListBeforeSqlGeneration() {
        StringBuilder dsl = new StringBuilder("SCREEN ON 2026-08-07 WHERE MARKET IN [");
        for (int i = 0; i <= SemanticAnalyzer.MAX_IN_LIST_SIZE; i++) {
            if (i > 0) dsl.append(", ");
            dsl.append("'M").append(i).append("'");
        }
        dsl.append("] LIMIT 5");

        CompileException error = assertThrows(CompileException.class, () -> compiler.compile(dsl.toString()));
        assertEquals("IN_LIST_TOO_LARGE", error.code());
    }

    @Test void rejectsMaliciousDeepExpression() {
        StringBuilder dsl = new StringBuilder("SCREEN ON 2026-08-07 WHERE ");
        for (int i = 0; i < SemanticAnalyzer.MAX_EXPRESSION_DEPTH + 10; i++) dsl.append("(");
        dsl.append("CLOSE > 1");
        for (int i = 0; i < SemanticAnalyzer.MAX_EXPRESSION_DEPTH + 10; i++) dsl.append(")");
        dsl.append(" LIMIT 5");

        CompileException error = assertThrows(CompileException.class, () -> compiler.compile(dsl.toString()));
        assertEquals("EXPRESSION_DEPTH", error.code());
    }
}
