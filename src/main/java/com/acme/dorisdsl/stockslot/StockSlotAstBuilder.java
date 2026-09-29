package com.acme.dorisdsl.stockslot;

import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.Token;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

final class StockSlotAstBuilder extends StockSlotDslBaseVisitor<Object> {
    @Override
    public StockSlotAst.Document visitDocument(StockSlotDslParser.DocumentContext ctx) {
        StockSlotAst.SelectionLimit limit = null;
        if (ctx.LIMIT() != null) {
            int minimum = signed(ctx.signedInteger(0));
            int maximum = signed(ctx.signedInteger(1));
            limit = new StockSlotAst.SelectionLimit(minimum, maximum, span(ctx.signedInteger(0).getParent()));
        }
        return new StockSlotAst.Document(expr(ctx.expression()), limit, span(ctx));
    }

    @Override public StockSlotAst.Expr visitExpression(StockSlotDslParser.ExpressionContext ctx) {
        return expr(ctx.thenExpression());
    }

    @Override public StockSlotAst.Expr visitThenExpression(StockSlotDslParser.ThenExpressionContext ctx) {
        StockSlotAst.Expr result = expr(ctx.orExpression(0));
        for (int i = 1; i < ctx.orExpression().size(); i++)
            result = binary("THEN", result, expr(ctx.orExpression(i)), ctx);
        return result;
    }

    @Override public StockSlotAst.Expr visitOrExpression(StockSlotDslParser.OrExpressionContext ctx) {
        StockSlotAst.Expr result = expr(ctx.andExpression(0));
        for (int i = 1; i < ctx.andExpression().size(); i++)
            result = binary("OR", result, expr(ctx.andExpression(i)), ctx);
        return result;
    }

    @Override public StockSlotAst.Expr visitAndExpression(StockSlotDslParser.AndExpressionContext ctx) {
        StockSlotAst.Expr result = expr(ctx.comparisonExpression(0));
        for (int i = 1; i < ctx.comparisonExpression().size(); i++)
            result = binary("AND", result, expr(ctx.comparisonExpression(i)), ctx);
        return result;
    }

    @Override public StockSlotAst.Expr visitComparisonExpression(StockSlotDslParser.ComparisonExpressionContext ctx) {
        StockSlotAst.Expr left = expr(ctx.additiveExpression(0));
        if (ctx.additiveExpression().size() == 1) return left;
        return binary(ctx.getChild(1).getText().toUpperCase(Locale.ROOT), left,
                expr(ctx.additiveExpression(1)), ctx);
    }

    @Override public StockSlotAst.Expr visitAdditiveExpression(StockSlotDslParser.AdditiveExpressionContext ctx) {
        StockSlotAst.Expr result = expr(ctx.multiplicativeExpression(0));
        for (int i = 1; i < ctx.multiplicativeExpression().size(); i++)
            result = binary(ctx.getChild(2 * i - 1).getText(), result, expr(ctx.multiplicativeExpression(i)), ctx);
        return result;
    }

    @Override public StockSlotAst.Expr visitMultiplicativeExpression(StockSlotDslParser.MultiplicativeExpressionContext ctx) {
        StockSlotAst.Expr result = expr(ctx.unaryExpression(0));
        for (int i = 1; i < ctx.unaryExpression().size(); i++)
            result = binary(ctx.getChild(2 * i - 1).getText(), result, expr(ctx.unaryExpression(i)), ctx);
        return result;
    }

    @Override public StockSlotAst.Expr visitUnaryExpression(StockSlotDslParser.UnaryExpressionContext ctx) {
        if (ctx.primary() != null) return expr(ctx.primary());
        return new StockSlotAst.Unary(ctx.getChild(0).getText(), expr(ctx.unaryExpression()),
                StockSlotAst.ValueType.UNKNOWN, span(ctx));
    }

    @Override public StockSlotAst.Expr visitPrimary(StockSlotDslParser.PrimaryContext ctx) {
        if (ctx.functionCall() != null) return expr(ctx.functionCall());
        if (ctx.literal() != null) return expr(ctx.literal());
        return expr(ctx.expression());
    }

    @Override public StockSlotAst.Expr visitFunctionCall(StockSlotDslParser.FunctionCallContext ctx) {
        List<StockSlotAst.Expr> arguments = new ArrayList<>();
        if (ctx.argumentList() != null)
            for (var argument : ctx.argumentList().expression()) arguments.add(expr(argument));
        return new StockSlotAst.FunctionCall(ctx.IDENTIFIER().getText().toLowerCase(Locale.ROOT), arguments,
                StockSlotAst.ValueType.UNKNOWN, span(ctx));
    }

    @Override public StockSlotAst.Expr visitLiteral(StockSlotDslParser.LiteralContext ctx) {
        String text = ctx.getText();
        if (ctx.PERCENT() != null)
            return new StockSlotAst.Literal(new BigDecimal(text.substring(0, text.length() - 1)),
                    StockSlotAst.ValueType.PERCENT, span(ctx));
        if (ctx.NUMBER() != null || ctx.INTEGER() != null)
            return StockSlotAst.Literal.number(new BigDecimal(text), span(ctx));
        if (ctx.STRING() != null)
            return new StockSlotAst.Literal(text.substring(1, text.length() - 1).replace("''", "'"),
                    StockSlotAst.ValueType.STRING, span(ctx));
        if (ctx.TRUE() != null || ctx.FALSE() != null)
            return new StockSlotAst.Literal(Boolean.valueOf(text.toLowerCase(Locale.ROOT)),
                    StockSlotAst.ValueType.BOOLEAN, span(ctx));
        return new StockSlotAst.Literal(null, StockSlotAst.ValueType.NULL, span(ctx));
    }

    private StockSlotAst.Binary binary(String operator, StockSlotAst.Expr left, StockSlotAst.Expr right,
                                       ParserRuleContext ctx) {
        return new StockSlotAst.Binary(operator, left, right, StockSlotAst.ValueType.UNKNOWN, span(ctx));
    }

    private int signed(StockSlotDslParser.SignedIntegerContext ctx) {
        int value = Integer.parseInt(ctx.INTEGER().getText());
        return ctx.MINUS() == null ? value : -value;
    }

    private StockSlotAst.Expr expr(ParserRuleContext ctx) { return (StockSlotAst.Expr) visit(ctx); }

    private StockSlotAst.SourceSpan span(ParserRuleContext ctx) {
        Token start = ctx.getStart();
        Token stop = ctx.getStop() == null ? start : ctx.getStop();
        int end = stop.getCharPositionInLine() + Math.max(1, stop.getText() == null ? 1 : stop.getText().length()) + 1;
        return new StockSlotAst.SourceSpan(start.getLine(), start.getCharPositionInLine() + 1, stop.getLine(), end);
    }
}
