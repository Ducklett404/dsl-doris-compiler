package com.acme.dorisdsl.competition;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.parser.ThrowingErrorListener;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.Token;
import org.antlr.v4.runtime.tree.TerminalNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Independent entry point: the legacy SCREEN ON compiler is deliberately unchanged. */
public final class SlotDslParserFacade {
    private static final int MAX_PARENTHESES_DEPTH = 64;
    private static final Map<String, Integer> FUNCTION_ARITY = Map.ofEntries(
            Map.entry("indicator", 7), Map.entry("rank", 8), Map.entry("belong_industry", 5),
            Map.entry("querydata", 5), Map.entry("cross_above", 7), Map.entry("cross_down", 7),
            Map.entry("close_together", 7), Map.entry("reset", 7), Map.entry("golden_cross", 7),
            Map.entry("record_high", 8), Map.entry("record_low", 8), Map.entry("position", 8));

    public SlotAst.Query parse(String source) {
        if (source == null || source.isBlank())
            throw new CompileException("DSL_SYNTAX", "Slot DSL is empty", 1, 1);
        validateDepth(source);
        var lexer = new SlotDslLexer(CharStreams.fromString(source));
        lexer.removeErrorListeners();
        lexer.addErrorListener(ThrowingErrorListener.INSTANCE);
        var parser = new SlotDslParser(new CommonTokenStream(lexer));
        parser.removeErrorListeners();
        parser.addErrorListener(ThrowingErrorListener.INSTANCE);
        var tree = parser.query();
        return new Builder().build(tree);
    }

    private static void validateDepth(String source) {
        int depth = 0, line = 1, column = 1;
        boolean quoted = false;
        for (int i = 0; i < source.length(); i++) {
            char ch = source.charAt(i);
            if (ch == '\'') {
                if (quoted && i + 1 < source.length() && source.charAt(i + 1) == '\'') {
                    i++;
                    column += 2;
                    continue;
                }
                quoted = !quoted;
            } else if (!quoted && ch == '(' && ++depth > MAX_PARENTHESES_DEPTH) {
                throw new CompileException("EXPRESSION_DEPTH", "Expression depth exceeds " + MAX_PARENTHESES_DEPTH, line, column);
            } else if (!quoted && ch == ')' && depth > 0) {
                depth--;
            }
            if (ch == '\n') { line++; column = 1; }
            else column++;
        }
    }

    private static final class Builder extends SlotDslBaseVisitor<SlotAst.Expr> {
        SlotAst.Query build(SlotDslParser.QueryContext ctx) {
            SlotAst.Expr filter = visit(ctx.expression());
            SlotAst.ResultBounds bounds = null;
            if (ctx.limitClause() != null) {
                var limit = ctx.limitClause();
                int minimum = parseCount(limit.signedInt(0));
                int maximum = parseCount(limit.signedInt(1));
                bounds = new SlotAst.ResultBounds(minimum, maximum, span(limit));
            }
            return new SlotAst.Query(filter, bounds,
                    bounds == null ? filter.span() : merge(filter.span(), bounds.span()));
        }

        @Override public SlotAst.Expr visitExpression(SlotDslParser.ExpressionContext ctx) {
            return visit(ctx.thenExpression());
        }

        @Override public SlotAst.Expr visitThenExpression(SlotDslParser.ThenExpressionContext ctx) {
            SlotAst.Expr result = visit(ctx.orExpression(0));
            for (int i = 1; i < ctx.orExpression().size(); i++) {
                SlotAst.Expr stage = visit(ctx.orExpression(i));
                if (!containsRank(stage)) {
                    Token at = ctx.THEN(i - 1).getSymbol();
                    throw new CompileException("DSL_THEN_RANK_REQUIRED", "then stage must contain rank(...) predicate",
                            at.getLine(), at.getCharPositionInLine() + 1);
                }
                result = new SlotAst.Then(result, stage, merge(result.span(), stage.span()));
            }
            return result;
        }

        @Override public SlotAst.Expr visitOrExpression(SlotDslParser.OrExpressionContext ctx) {
            SlotAst.Expr result = visit(ctx.andExpression(0));
            for (int i = 1; i < ctx.andExpression().size(); i++) {
                SlotAst.Expr right = visit(ctx.andExpression(i));
                result = new SlotAst.Binary("or", result, right, merge(result.span(), right.span()));
            }
            return result;
        }

        @Override public SlotAst.Expr visitAndExpression(SlotDslParser.AndExpressionContext ctx) {
            SlotAst.Expr result = visit(ctx.comparisonExpression(0));
            for (int i = 1; i < ctx.comparisonExpression().size(); i++) {
                SlotAst.Expr right = visit(ctx.comparisonExpression(i));
                result = new SlotAst.Binary("and", result, right, merge(result.span(), right.span()));
            }
            return result;
        }

        @Override public SlotAst.Expr visitComparisonExpression(SlotDslParser.ComparisonExpressionContext ctx) {
            SlotAst.Expr left = visit(ctx.additiveExpression(0));
            if (ctx.comparisonOperator() != null) {
                SlotAst.Expr right = visit(ctx.additiveExpression(1));
                return new SlotAst.Comparison(ctx.comparisonOperator().getText(), left, right, span(ctx));
            }
            if (ctx.BETWEEN() != null)
                return new SlotAst.Interval(left, slot(ctx.STRING().getSymbol()), span(ctx));
            return left;
        }

        @Override public SlotAst.Expr visitAdditiveExpression(SlotDslParser.AdditiveExpressionContext ctx) {
            SlotAst.Expr result = visit(ctx.multiplicativeExpression(0));
            for (int i = 1; i < ctx.multiplicativeExpression().size(); i++) {
                SlotAst.Expr right = visit(ctx.multiplicativeExpression(i));
                result = new SlotAst.Binary(ctx.getChild(2 * i - 1).getText(), result, right,
                        merge(result.span(), right.span()));
            }
            return result;
        }

        @Override public SlotAst.Expr visitMultiplicativeExpression(SlotDslParser.MultiplicativeExpressionContext ctx) {
            SlotAst.Expr result = visit(ctx.unaryExpression(0));
            for (int i = 1; i < ctx.unaryExpression().size(); i++) {
                SlotAst.Expr right = visit(ctx.unaryExpression(i));
                result = new SlotAst.Binary(ctx.getChild(2 * i - 1).getText(), result, right,
                        merge(result.span(), right.span()));
            }
            return result;
        }

        @Override public SlotAst.Expr visitUnaryExpression(SlotDslParser.UnaryExpressionContext ctx) {
            if (ctx.primary() != null) return visit(ctx.primary());
            return new SlotAst.Unary(ctx.getChild(0).getText(), visit(ctx.unaryExpression()), span(ctx));
        }

        @Override public SlotAst.Expr visitPrimary(SlotDslParser.PrimaryContext ctx) {
            if (ctx.functionCall() != null) return visit(ctx.functionCall());
            if (ctx.literal() != null) return visit(ctx.literal());
            return visit(ctx.expression());
        }

        @Override public SlotAst.Expr visitFunctionCall(SlotDslParser.FunctionCallContext ctx) {
            String function = ctx.IDENTIFIER().getText();
            String key = function.toLowerCase(Locale.ROOT);
            Integer expected = FUNCTION_ARITY.get(key);
            if (expected == null)
                throw new CompileException("DSL_FUNCTION_UNKNOWN", "Unknown slot function: " + function,
                        ctx.start.getLine(), ctx.start.getCharPositionInLine() + 1);
            List<SlotAst.Slot> slots = new ArrayList<>();
            if (ctx.slotList() != null)
                for (TerminalNode node : ctx.slotList().STRING()) slots.add(slot(node.getSymbol()));
            if (slots.size() != expected)
                throw new CompileException("DSL_FUNCTION_ARITY", function + " expects " + expected
                        + " quoted slots, got " + slots.size(),
                        ctx.start.getLine(), ctx.start.getCharPositionInLine() + 1);
            for (int i = 0; i < slots.size(); i++) {
                if (i == 0 || isSelectTypeSlot(key, i)) {
                    SlotAst.Slot original = slots.get(i);
                    slots.set(i, new SlotAst.Slot(original.raw(), original.value(),
                            tokenizeSet(original.value()), original.span()));
                }
            }
            return new SlotAst.Call(key.equals("querydata") ? "queryData" : key, slots, span(ctx));
        }

        @Override public SlotAst.Expr visitLiteral(SlotDslParser.LiteralContext ctx) {
            Token token = ctx.start;
            String raw = token.getText();
            SlotAst.LiteralKind kind = ctx.STRING() != null ? SlotAst.LiteralKind.STRING
                    : ctx.PERCENT() != null ? SlotAst.LiteralKind.PERCENT
                    : ctx.TRUE() != null || ctx.FALSE() != null ? SlotAst.LiteralKind.BOOLEAN
                    : SlotAst.LiteralKind.NUMBER;
            String value = kind == SlotAst.LiteralKind.STRING ? unquote(raw) : raw;
            return new SlotAst.Literal(raw, value, kind, span(token));
        }

        private static boolean containsRank(SlotAst.Expr expr) {
            if (expr instanceof SlotAst.Call call) return call.function().equals("rank");
            if (expr instanceof SlotAst.Binary binary)
                return containsRank(binary.left()) || containsRank(binary.right());
            if (expr instanceof SlotAst.Comparison comparison)
                return containsRank(comparison.left()) || containsRank(comparison.right());
            if (expr instanceof SlotAst.Interval interval) return containsRank(interval.value());
            if (expr instanceof SlotAst.Unary unary) return containsRank(unary.operand());
            if (expr instanceof SlotAst.Then then) return containsRank(then.rankingStage());
            return false;
        }

        private static int parseCount(SlotDslParser.SignedIntContext ctx) {
            try { return Integer.parseInt(ctx.getText()); }
            catch (NumberFormatException e) {
                throw new CompileException("DSL_LIMIT_BOUNDS", "limit count is outside 32-bit integer range",
                        ctx.start.getLine(), ctx.start.getCharPositionInLine() + 1);
            }
        }

        private static SlotAst.Slot slot(Token token) {
            return new SlotAst.Slot(token.getText(), unquote(token.getText()), List.of(), span(token));
        }

        private static boolean isSelectTypeSlot(String function, int index) {
            if (function.equals("indicator")) return index == 4;
            if (function.equals("rank")) return index == 5;
            if (function.equals("cross_above") || function.equals("cross_down")
                    || function.equals("close_together") || function.equals("reset")
                    || function.equals("golden_cross") || function.equals("record_high")
                    || function.equals("record_low") || function.equals("position")) return index == 5;
            return false;
        }

        private static List<SlotAst.SetToken> tokenizeSet(String value) {
            List<SlotAst.SetToken> result = new ArrayList<>();
            int atomStart = 0;
            for (int i = 0; i < value.length(); i++) {
                SlotAst.SetTokenKind kind = switch (value.charAt(i)) {
                    case '|' -> SlotAst.SetTokenKind.PIPE;
                    case '&' -> SlotAst.SetTokenKind.AMPERSAND;
                    case '^' -> SlotAst.SetTokenKind.CARET;
                    case '(' -> SlotAst.SetTokenKind.LPAREN;
                    case ')' -> SlotAst.SetTokenKind.RPAREN;
                    default -> null;
                };
                if (kind == null) continue;
                if (atomStart < i)
                    result.add(new SlotAst.SetToken(SlotAst.SetTokenKind.ATOM,
                            value.substring(atomStart, i), atomStart, i));
                result.add(new SlotAst.SetToken(kind, value.substring(i, i + 1), i, i + 1));
                atomStart = i + 1;
            }
            if (atomStart < value.length())
                result.add(new SlotAst.SetToken(SlotAst.SetTokenKind.ATOM,
                        value.substring(atomStart), atomStart, value.length()));
            return List.copyOf(result);
        }

        private static String unquote(String raw) {
            return raw.substring(1, raw.length() - 1).replace("''", "'");
        }

        private static SlotAst.Span span(ParserRuleContext ctx) {
            return merge(span(ctx.start), span(ctx.stop));
        }

        private static SlotAst.Span span(Token token) {
            String text = token.getText();
            int line = token.getLine(), column = token.getCharPositionInLine() + 1;
            int endLine = line, endColumn = column;
            for (int i = 0; i < text.length(); i++) {
                if (text.charAt(i) == '\n') { endLine++; endColumn = 1; }
                else endColumn++;
            }
            return new SlotAst.Span(line, column, endLine, endColumn);
        }

        private static SlotAst.Span merge(SlotAst.Span left, SlotAst.Span right) {
            return new SlotAst.Span(left.line(), left.column(), right.endLine(), right.endColumn());
        }
    }
}
