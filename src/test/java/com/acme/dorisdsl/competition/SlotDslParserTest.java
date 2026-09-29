package com.acme.dorisdsl.competition;

import com.acme.dorisdsl.compiler.CompileException;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class SlotDslParserTest {
    private final SlotDslParserFacade parser = new SlotDslParserFacade();

    @Test void keepsThenDistinctFromAndAndPreservesSlots() {
        var query = parser.parse("""
                indicator('沪|深', '', '最新价', '今天', '', '', '') > 10
                then rank('沪|深', '', '涨跌幅', 'desc', '今天', '', '', '') <= 5
                and indicator('', '', '涨停', '今天', '', '', '') = True limit 0,10
                """);
        assertInstanceOf(SlotAst.Then.class, query.filter());
        var then = (SlotAst.Then) query.filter();
        assertInstanceOf(SlotAst.Binary.class, then.rankingStage());
        var filter = (SlotAst.Comparison) then.candidateFilter();
        var call = (SlotAst.Call) filter.left();
        assertEquals("indicator", call.function());
        assertEquals("沪|深", call.slots().get(0).value());
        assertEquals("'沪|深'", call.slots().get(0).raw());
        assertEquals(SlotAst.SetTokenKind.PIPE, call.slots().get(0).setTokens().get(1).kind());
        assertEquals(0, query.resultBounds().minimum());
        assertEquals(10, query.resultBounds().maximum());
    }

    @Test void preservesIntervalPercentAndQuotedApostrophe() {
        var query = parser.parse("indicator('', '', 'O''Brien', '', '', '', '') between '[1%,5%)'");
        var interval = assertInstanceOf(SlotAst.Interval.class, query.filter());
        var call = assertInstanceOf(SlotAst.Call.class, interval.value());
        assertEquals("O'Brien", call.slots().get(2).value());
        assertEquals("[1%,5%)", interval.bounds().value());
    }

    @Test void respectsArithmeticPrecedence() {
        var query = parser.parse("indicator('', '', '价格', '', '', '', '') > 2 + 3 * 4%");
        var comparison = assertInstanceOf(SlotAst.Comparison.class, query.filter());
        var addition = assertInstanceOf(SlotAst.Binary.class, comparison.right());
        assertEquals("+", addition.operator());
        var multiplication = assertInstanceOf(SlotAst.Binary.class, addition.right());
        assertEquals("*", multiplication.operator());
        assertEquals(SlotAst.LiteralKind.PERCENT,
                assertInstanceOf(SlotAst.Literal.class, multiplication.right()).literalKind());
    }

    @Test void rejectsUnknownFunctionWrongArityAndUnrankedThen() {
        assertEquals("DSL_FUNCTION_UNKNOWN", assertThrows(CompileException.class,
                () -> parser.parse("mystery('') = True")).code());
        assertEquals("DSL_FUNCTION_ARITY", assertThrows(CompileException.class,
                () -> parser.parse("indicator('沪') = True")).code());
        assertEquals("DSL_THEN_RANK_REQUIRED", assertThrows(CompileException.class,
                () -> parser.parse("indicator('', '', '', '', '', '', '') = True then cross_above('', '', '', '', '', '', '') = True")).code());
    }

    @Test void keepsNegativeLimitSentinelUninterpretedAndRejectsMalformedSlot() {
        var bounds = parser.parse("rank('', '', '', 'desc', '', '', '', '') <= 5 limit 7,-1").resultBounds();
        assertEquals(7, bounds.minimum());
        assertEquals(-1, bounds.maximum());
        assertEquals("DSL_SYNTAX", assertThrows(CompileException.class,
                () -> parser.parse("indicator('沪', '', '价格', today, '', '', '') > 5")).code());
    }

    @Test void reportsSyntaxLocation() {
        var error = assertThrows(CompileException.class,
                () -> parser.parse("indicator('', '', '', '', '', '', '') >\n"));
        assertEquals("DSL_SYNTAX", error.code());
        assertEquals(2, error.line());
    }
}
