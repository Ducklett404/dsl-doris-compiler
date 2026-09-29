package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotSqlCompilerTest {
    private final StockSlotSqlCompiler compiler = new StockSlotSqlCompiler();

    @Test
    void lowersAcceptedIndicatorSubsetWithBindingsAndMarketFilter() {
        var artifact = compiler.compile(
                "indicator('沪|深', '', '收盘价', '2026年4月14日', '', '', '') between '[5,20)' "
                        + "and indicator('沪|深', '', '成交量', '2026年4月14日', '', '', '') > 0");
        assertTrue(artifact.sql().contains("newzl.v_hsj_stock_hq_basic"));
        assertTrue(artifact.sql().contains("b.mktcode = 1 OR b.mktcode = 0"));
        assertTrue(artifact.sql().contains("`m1` >= ? AND `m1` < ?"));
        assertEquals(4, artifact.bindings().size());
        assertFalse(artifact.ordered());
    }

    @Test
    void lowersExtensionJoinAndThenRankInSeparateStages() {
        var artifact = compiler.compile(
                "indicator('', '', '主力净流入', '2026-04-14', '', '', '') > 0 then "
                        + "rank('', '', '成交额', 'desc', '2026-04-14', '', '', '') <= 10 limit 0,10");
        assertTrue(artifact.sql().contains("LEFT JOIN newzl.v_hsj_stock_hq_ext"));
        assertTrue(artifact.sql().contains("prefiltered AS"));
        assertTrue(artifact.sql().contains("DENSE_RANK() OVER"));
        assertTrue(artifact.sql().contains("LIMIT 10"));
        assertTrue(artifact.ordered());
        assertEquals("Rank", artifact.logicalPlan().stream().filter(n -> n.kind().equals("Rank")).findFirst().orElseThrow().kind());
    }

    @Test
    void rejectsMissingDataDefinitionsBeforeSqlGeneration() {
        CompileException error = assertThrows(CompileException.class, () -> compiler.compile(
                "indicator('', '', '归母净利润', '2026-04-14', '', '', '') > 0"));
        assertEquals("EXECUTION_INDICATOR_UNSUPPORTED", error.code());
    }
}
