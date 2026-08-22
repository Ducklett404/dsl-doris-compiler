package com.acme.dorisdsl;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class TypeSystemTest {
    private DslCompiler compiler;

    @BeforeEach void setUp() {
        compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    }

    @Test void roeTtmCanCompareWithPercent() {
        var artifact = compiler.compile("SCREEN ON 2026-08-07 WHERE ROE_TTM() >= 15% LIMIT 5");
        assertEquals(Ast.DataType.BooleanSeries, artifact.ast().where().type());
        assertTrue(artifact.sql().contains("`roe_ttm` >= ?"));
        assertEquals("0.15", artifact.bindings().getLast().toString());
    }

    @Test void rejectsArithmeticBetweenRatioSeriesAndTradeDateWithDiagnosticContext() {
        CompileException error = assertThrows(CompileException.class,
                () -> compiler.compile("""
                        SCREEN ON 2026-08-07
                        WHERE ROE_TTM() + TRADE_DATE > 1
                        LIMIT 5
                        """));
        assertEquals("NUMERIC_TYPE", error.code());
        assertEquals(2, error.line());
        assertTrue(error.column() > 1);
        assertEquals("TRADE_DATE", error.fragment());
        assertTrue(error.suggestion().contains("PriceSeries"));
    }

    @Test void crossUpRequiresSymbolTradeDateOrderableSeriesOperands() {
        var valid = compiler.compile("SCREEN ON 2026-08-07 WHERE CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20)) LIMIT 5");
        assertEquals(Ast.DataType.BooleanSeries, valid.ast().where().type());

        CompileException error = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE CROSS_UP(MA(CLOSE, 5), 10) LIMIT 5"));
        assertEquals("SERIES_TYPE", error.code());
        assertEquals("10", error.fragment());
        assertTrue(error.suggestion().contains("symbol"));
        assertTrue(error.suggestion().contains("trade_date"));
    }

    @Test void orderByMustResolveToTargetDateScalarValue() {
        var valid = compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 10 ORDER BY RANK_BY(TURNOVER_RATE) ASC LIMIT 5");
        assertEquals(Ast.DataType.ScalarNumber, valid.ast().orderBy().expression().type());

        CompileException error = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 10 ORDER BY CLOSE > 10 ASC LIMIT 5"));
        assertEquals("ORDER_BY_TYPE", error.code());
        assertTrue(error.fragment().contains("CLOSE"));
        assertTrue(error.suggestion().contains("target date"));
    }
}
