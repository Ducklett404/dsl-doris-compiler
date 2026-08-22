package com.acme.dorisdsl.parser;

import com.acme.dorisdsl.ast.Ast;
import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.Token;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class AstBuilder extends StockDslBaseVisitor<Object> {
    @Override
    public Ast.Query visitQuery(StockDslParser.QueryContext ctx) {
        var asOf = LocalDate.parse(ctx.DATE().getText());
        int expressionIndex = 0;
        Ast.QueryContext context = ctx.contextClause() == null ? Ast.QueryContext.empty() : visitContextClause(ctx.contextClause());
        Ast.Expr where = ctx.WHERE() == null ? null : expr(ctx.expression(expressionIndex++));
        Ast.Adjustment adjustment = ctx.adjustmentMode() == null
                ? Ast.Adjustment.NONE
                : Ast.Adjustment.valueOf(ctx.adjustmentMode().getText().toUpperCase(Locale.ROOT));
        Ast.OrderBy orderBy = null;
        if (ctx.ORDER() != null) {
            var direction = ctx.direction() == null ? Ast.Direction.ASC
                    : Ast.Direction.valueOf(ctx.direction().getText().toUpperCase(Locale.ROOT));
            orderBy = new Ast.OrderBy(expr(ctx.expression(expressionIndex)), direction);
        }
        int limit = ctx.LIMIT() == null ? 100 : Integer.parseInt(ctx.INT().getText());
        return new Ast.Query(asOf, context, where, adjustment, orderBy, limit, span(ctx));
    }

    @Override
    public Ast.QueryContext visitContextClause(StockDslParser.ContextClauseContext ctx) {
        Map<String, List<Object>> values = new LinkedHashMap<>();
        for (var item : ctx.contextItem()) {
            String key = item.identifier().getText().toUpperCase(Locale.ROOT);
            List<Object> itemValues = new ArrayList<>();
            if (item.literal() != null) {
                itemValues.add(((Ast.Literal) visit(item.literal())).value());
            } else {
                @SuppressWarnings("unchecked")
                List<Ast.Expr> literals = (List<Ast.Expr>) visit(item.listLiteral());
                for (Ast.Expr literal : literals) itemValues.add(((Ast.Literal) literal).value());
            }
            values.put(key, List.copyOf(itemValues));
        }
        return new Ast.QueryContext(values);
    }

    @Override public Ast.Expr visitExpression(StockDslParser.ExpressionContext ctx) { return expr(ctx.orExpression()); }

    @Override
    public Ast.Expr visitOrExpression(StockDslParser.OrExpressionContext ctx) {
        Ast.Expr result = expr(ctx.andExpression(0));
        for (int i = 1; i < ctx.andExpression().size(); i++) {
            result = new Ast.Binary("OR", result, expr(ctx.andExpression(i)), Ast.DataType.UNKNOWN, span(ctx));
        }
        return result;
    }

    @Override
    public Ast.Expr visitAndExpression(StockDslParser.AndExpressionContext ctx) {
        Ast.Expr result = expr(ctx.notExpression(0));
        for (int i = 1; i < ctx.notExpression().size(); i++) {
            result = new Ast.Binary("AND", result, expr(ctx.notExpression(i)), Ast.DataType.UNKNOWN, span(ctx));
        }
        return result;
    }

    @Override
    public Ast.Expr visitNotExpression(StockDslParser.NotExpressionContext ctx) {
        if (ctx.NOT() != null) return new Ast.Unary("NOT", expr(ctx.notExpression()), Ast.DataType.UNKNOWN, span(ctx));
        return expr(ctx.predicate());
    }

    @Override
    public Ast.Expr visitPredicate(StockDslParser.PredicateContext ctx) {
        var parts = ctx.additiveExpression();
        Ast.Expr first = expr(parts.get(0));
        if (ctx.comparisonOperator() != null) {
            return new Ast.Binary(ctx.comparisonOperator().getText(), first, expr(parts.get(1)), Ast.DataType.UNKNOWN, span(ctx));
        }
        if (ctx.BETWEEN() != null) {
            return new Ast.Between(first, expr(parts.get(1)), expr(parts.get(2)), Ast.DataType.UNKNOWN, span(ctx));
        }
        if (ctx.IN() != null) {
            @SuppressWarnings("unchecked")
            List<Ast.Expr> values = (List<Ast.Expr>) visit(ctx.listLiteral());
            return new Ast.InList(first, values, Ast.DataType.UNKNOWN, span(ctx));
        }
        if (ctx.IS() != null) {
            return new Ast.IsNull(first, ctx.NOT() != null, Ast.DataType.UNKNOWN, span(ctx));
        }
        return first;
    }

    @Override
    public Ast.Expr visitAdditiveExpression(StockDslParser.AdditiveExpressionContext ctx) {
        Ast.Expr result = expr(ctx.multiplicativeExpression(0));
        for (int i = 1; i < ctx.multiplicativeExpression().size(); i++) {
            String op = ctx.getChild(2 * i - 1).getText();
            result = new Ast.Binary(op, result, expr(ctx.multiplicativeExpression(i)), Ast.DataType.UNKNOWN, span(ctx));
        }
        return result;
    }

    @Override
    public Ast.Expr visitMultiplicativeExpression(StockDslParser.MultiplicativeExpressionContext ctx) {
        Ast.Expr result = expr(ctx.unaryExpression(0));
        for (int i = 1; i < ctx.unaryExpression().size(); i++) {
            String op = ctx.getChild(2 * i - 1).getText();
            result = new Ast.Binary(op, result, expr(ctx.unaryExpression(i)), Ast.DataType.UNKNOWN, span(ctx));
        }
        return result;
    }

    @Override
    public Ast.Expr visitUnaryExpression(StockDslParser.UnaryExpressionContext ctx) {
        if (ctx.primary() != null) return expr(ctx.primary());
        return new Ast.Unary(ctx.getChild(0).getText(), expr(ctx.unaryExpression()), Ast.DataType.UNKNOWN, span(ctx));
    }

    @Override
    public Ast.Expr visitPrimary(StockDslParser.PrimaryContext ctx) {
        if (ctx.functionCall() != null) return expr(ctx.functionCall());
        if (ctx.identifier() != null) return expr(ctx.identifier());
        if (ctx.literal() != null) return expr(ctx.literal());
        return expr(ctx.expression());
    }

    @Override
    public Ast.Expr visitFunctionCall(StockDslParser.FunctionCallContext ctx) {
        List<Ast.Expr> args = new ArrayList<>();
        if (ctx.argumentList() != null) {
            for (var argument : ctx.argumentList().functionArgument()) args.add(expr(argument));
        }
        return new Ast.FunctionCall(ctx.identifier().getText().toUpperCase(Locale.ROOT), args,
                Ast.DataType.UNKNOWN, span(ctx));
    }

    @Override
    public Ast.Expr visitFunctionArgument(StockDslParser.FunctionArgumentContext ctx) {
        if (ctx.identifier() != null) {
            return new Ast.NamedArgument(ctx.identifier().getText().toUpperCase(Locale.ROOT),
                    expr(ctx.expression()), Ast.DataType.UNKNOWN, span(ctx));
        }
        return expr(ctx.expression());
    }

    @Override
    public Ast.Expr visitIdentifier(StockDslParser.IdentifierContext ctx) {
        return new Ast.Identifier(ctx.getText().toUpperCase(Locale.ROOT), Ast.DataType.UNKNOWN, span(ctx));
    }

    @Override
    public Ast.Expr visitLiteral(StockDslParser.LiteralContext ctx) {
        String text = ctx.getText();
        if (ctx.PERCENT() != null) {
            return new Ast.Literal(new BigDecimal(text.substring(0, text.length() - 1)).movePointLeft(2),
                    Ast.DataType.Percent, span(ctx));
        }
        if (ctx.DECIMAL() != null || ctx.INT() != null)
            return new Ast.Literal(new BigDecimal(text), Ast.DataType.ScalarNumber, span(ctx));
        if (ctx.STRING() != null)
            return new Ast.Literal(text.substring(1, text.length() - 1).replace("''", "'"), Ast.DataType.StringCategory, span(ctx));
        if (ctx.DATE() != null) return new Ast.Literal(LocalDate.parse(text), Ast.DataType.TradeDate, span(ctx));
        if (ctx.TRUE() != null || ctx.FALSE() != null)
            return new Ast.Literal(Boolean.valueOf(text), Ast.DataType.BooleanSeries, span(ctx));
        return new Ast.Literal(null, Ast.DataType.NULL, span(ctx));
    }

    @Override
    public Object visitListLiteral(StockDslParser.ListLiteralContext ctx) {
        List<Ast.Expr> values = new ArrayList<>();
        for (var literal : ctx.literal()) values.add(expr(literal));
        return values;
    }

    private Ast.Expr expr(ParserRuleContext ctx) { return (Ast.Expr) visit(ctx); }

    private Ast.SourceSpan span(ParserRuleContext ctx) {
        Token start = ctx.getStart();
        Token stop = ctx.getStop() == null ? start : ctx.getStop();
        int endColumn = stop.getCharPositionInLine() + Math.max(stop.getText() == null ? 1 : stop.getText().length(), 1) + 1;
        return new Ast.SourceSpan(start.getLine(), start.getCharPositionInLine() + 1, stop.getLine(), endColumn);
    }
}
