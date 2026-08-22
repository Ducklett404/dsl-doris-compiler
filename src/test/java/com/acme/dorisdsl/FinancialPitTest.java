package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class FinancialPitTest {
    @Test void financialIndicatorsUsePointInTimeVisibilityJoin() {
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE PE_TTM() BETWEEN 0 AND 20
                  AND ROE_TTM() >= 15%
                LIMIT 10
                """);

        assertTrue(artifact.sql().contains("LEFT JOIN market.dwd_financial_pit f"));
        assertTrue(artifact.sql().contains("AND f.visible_from <= q.trade_date"));
        assertTrue(artifact.sql().contains("AND q.trade_date < f.visible_to"));
        assertFalse(artifact.sql().contains("f.report_period = q.trade_date"));
        assertFalse(artifact.sql().contains("f.report_period <= q.trade_date"));
        assertTrue(artifact.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.code().equals("FINANCIAL_PIT")
                        && diagnostic.message().contains("point-in-time financial visibility")
                        && diagnostic.message().contains("report period column f.report_period is not used for direct joins")));
    }

    @Test void registryRejectsFinancialFunctionWithoutPitMetadata() {
        Path registry = Path.of("src/test/resources/unsafe-financial-registry.json");
        CompileException error = assertThrows(CompileException.class,
                () -> new RegistryLoader().load(registry, List.of()));
        assertEquals("REGISTRY_INVALID", error.code());
        assertTrue(error.getMessage().contains("Financial function requires PIT metadata"));
    }
}
