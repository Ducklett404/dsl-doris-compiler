package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.stockslot.DorisExecutionPolicy;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotSecurityResourceTest {
    private final StockSlotSqlCompiler compiler = new StockSlotSqlCompiler();

    @Test void rejectsSqlInjectionAndNeverCopiesUserValuesIntoSql() {
        assertThrows(CompileException.class, () -> compiler.compile(
                "indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1; DROP TABLE newzl.hsj_stock_hq_basic"));
        var artifact = compiler.compile("queryData('', '600000', '收盘价', '2026-04-14', '') > 1");
        assertFalse(artifact.sql().contains("600000"));
        assertTrue(artifact.sql().contains("tgtcode=? OR name=?"));
        assertTrue(artifact.bindings().contains("600000"));
    }

    @Test void rejectsUnauthorizedFieldsOversizedWindowsAndDslPayloads() {
        assertCode("EXECUTION_INDICATOR_UNSUPPORTED",
                "indicator('', '', '管理员密码', '2026-04-14', '', '', '') = 1");
        assertCode("EXECUTION_WINDOW_RANGE",
                "record_high('', '', '最高价', '5001日', '2026-04-14', '', '', '') = True");
        assertCode("EXECUTION_WINDOW_RANGE",
                "indicator('', '', '5001日均线', '2026-04-14', '', '', '') > 1");
        CompileException tooLarge = assertThrows(CompileException.class,
                () -> compiler.compile(" ".repeat(100_001)));
        assertEquals("DSL_TOO_LARGE", tooLarge.code());
    }

    @Test void executionResourcePolicyRejectsUnsafeLimits() {
        var safe = DorisExecutionPolicy.controlledDefaults();
        assertAll(() -> assertEquals(10, safe.queryTimeoutSeconds()),
                () -> assertEquals(1_000_000, safe.maxEstimatedScanRows()),
                () -> assertEquals(1_000, safe.maxReturnRows()),
                () -> assertTrue(safe.requireReadOnlyAccount()));
        assertThrows(IllegalArgumentException.class,
                () -> new DorisExecutionPolicy(11, 1_000_000, 1_000, 512L << 20, 2_000, true));
        assertThrows(IllegalArgumentException.class,
                () -> new DorisExecutionPolicy(10, 1_000_000, 100_001, 512L << 20, 2_000, true));
        assertThrows(IllegalArgumentException.class,
                () -> new DorisExecutionPolicy(10, 1_000_000, 1_000, 32L << 20, 2_000, true));
    }

    private void assertCode(String expected, String dsl) {
        assertEquals(expected, assertThrows(CompileException.class, () -> compiler.compile(dsl)).code());
    }
}
