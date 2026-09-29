package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.StockSlotAst;
import com.acme.dorisdsl.stockslot.StockSlotCompiler;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotDslTest {
    private final StockSlotCompiler compiler = new StockSlotCompiler();

    @Test
    void parsesAllTwelveCoreFunctionsWithEmptySlots() {
        List<String> expressions = List.of(
                "indicator('', '', '', '', '', '', '') = 'all'",
                "rank('', '', '', 'desc', '', '', '', '') > 0",
                "belong_industry('', '', '', '', '') = 'all'",
                "queryData('', '', '', '', '') = 'all'",
                "cross_above('', '', '', '', '', '', '')",
                "cross_down('', '', '', '', '', '', '')",
                "close_together('', '', '', '', '', '', '')",
                "reset('', '', '', '', '', '', '')",
                "golden_cross('', '', '', '', '', '', '')",
                "record_high('', '', '', '', '', '', '', '')",
                "record_low('', '', '', '', '', '', '', '')",
                "position('', '', '', '', '', '', '', '') = '高'");
        for (String expression : expressions) {
            var artifact = compiler.classify(expression);
            assertEquals("PARSED", artifact.status(), () -> expression + " -> " + artifact.diagnostics());
        }
    }

    @Test
    void preservesFormalPrecedenceAndSelectionLimit() {
        var artifact = compiler.classify("indicator('', '', 'A', '', '', '', '') = 1 or "
                + "indicator('', '', 'B', '', '', '', '') = 2 and "
                + "indicator('', '', 'C', '', '', '', '') = 3 then "
                + "rank('', '', 'C', 'desc', '', '', '', '') <= 10 limit 5,-1");
        assertEquals("PARSED", artifact.status(), artifact.diagnostics().toString());
        var document = artifact.semanticModel().document();
        assertEquals(5, document.selectionLimit().minimum());
        assertEquals(-1, document.selectionLimit().maximum());
        var then = assertInstanceOf(StockSlotAst.Binary.class, document.expression());
        assertEquals("THEN", then.operator());
        var or = assertInstanceOf(StockSlotAst.Binary.class, then.left());
        assertEquals("OR", or.operator());
        var and = assertInstanceOf(StockSlotAst.Binary.class, or.right());
        assertEquals("AND", and.operator());
    }

    @Test
    void structuresSetsCountsChineseTimeAndPlaceholders() {
        String dsl = "indicator('沪|^深&京', '白酒|AI', 'RSI(9)', '2024年1季报后2季度', "
                + "'ETF|LOF', 'AVG', 'CONS>=3日') > 1";
        var artifact = compiler.classify(dsl);
        assertEquals("PARSED", artifact.status(), artifact.diagnostics().toString());
        var slots = artifact.semanticModel().calls().getFirst().slots();
        assertInstanceOf(StockSlotAst.SetExpr.class, slots.get(0).structuredValue());
        var indicator = assertInstanceOf(StockSlotAst.IndicatorInstantiation.class, slots.get(2).structuredValue());
        assertEquals("RSI(N)", indicator.template());
        assertEquals("9", indicator.parameters().get("N"));
        var time = assertInstanceOf(StockSlotAst.TimeExpression.class, slots.get(3).structuredValue());
        assertEquals("1季报", time.reportPeriod());
        assertEquals(new StockSlotAst.TimeOffset("后", 2, "季度"), time.offsets().getFirst());
        var count = assertInstanceOf(StockSlotAst.CountExpression.class, slots.get(6).structuredValue());
        assertEquals("CONS", count.mode());
    }

    @Test
    void supportsComparisonsBetweenArithmeticAndThenRule() {
        for (String operator : List.of("=", "!=", ">", ">=", "<", "<=", "~=")) {
            var artifact = compiler.classify("indicator('', '', '市盈率', '', '', '', '') " + operator + " 5");
            assertEquals("PARSED", artifact.status(), artifact.diagnostics().toString());
        }
        assertEquals("PARSED", compiler.classify(
                "indicator('', '', '市盈率', '', '', '', '') between '[1,5)'").status());
        assertEquals("PARSED", compiler.classify(
                "indicator('', '', '市盈率', '', '', '', '') / indicator('', '', '市净率', '', '', '', '') > 5").status());
        var unsupported = compiler.classify("indicator('', '', '市盈率', '', '', '', '') > 5 then "
                + "indicator('', '', '市净率', '', '', '', '') > 1");
        assertEquals("UNSUPPORTED", unsupported.status());
        assertTrue(unsupported.diagnostics().stream().anyMatch(d -> d.code().equals("THEN_REQUIRES_RANK")));
    }

    @Test
    void alwaysReturnsExplainedUnsupportedClassification() {
        var unknown = compiler.classify("evil('', '') = 1");
        assertEquals("UNSUPPORTED", unknown.status());
        assertTrue(unknown.diagnostics().stream().anyMatch(d -> d.code().equals("UNSUPPORTED_FUNCTION")));
        var syntax = compiler.classify("indicator('");
        assertEquals("UNSUPPORTED", syntax.status());
        assertFalse(syntax.diagnostics().isEmpty());
        assertTrue(syntax.diagnostics().stream().noneMatch(d -> d.code().equals("INTERNAL_CLASSIFICATION_ERROR")));
    }
}
