package com.acme.dorisdsl.competition;

import com.acme.dorisdsl.compiler.CompileException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;

/** Fail-closed conversion from syntax AST to a small, unit-aware semantic IR. */
public final class SlotSemanticAnalyzer {
    private static final int MAX_NODES = 256;
    private static final int MAX_DEPTH = 64;
    private final VerifiedIndicatorCatalog catalog;

    public SlotSemanticAnalyzer(VerifiedIndicatorCatalog catalog) {
        this.catalog = java.util.Objects.requireNonNull(catalog);
    }

    public SlotTypedQuery.Query analyze(SlotAst.Query query) {
        if (query.resultBounds() != null)
            throw error("DSL_LIMIT_UNRESOLVED", "Organizer limit bounds are not yet safe to lower to SQL",
                    query.resultBounds().span());
        Context context = new Context();
        SlotTypedQuery.Predicate filter = analyzePredicate(query.filter(), context, 1);
        return new SlotTypedQuery.Query(context.date, filter, query.span());
    }

    private SlotTypedQuery.Predicate analyzePredicate(SlotAst.Expr expression, Context context, int depth) {
        if (++context.nodes > MAX_NODES || depth > MAX_DEPTH)
            throw error("DSL_EXPRESSION_COMPLEXITY", "Slot expression is too complex", expression.span());
        if (expression instanceof SlotAst.Then)
            throw error("DSL_RANK_UNRESOLVED", "then/rank candidate-set semantics are unverified", expression.span());
        if (expression instanceof SlotAst.Binary binary) {
            if (!binary.operator().equals("and") && !binary.operator().equals("or"))
                throw error("DSL_SAFE_SUBSET", "Arithmetic expressions are outside the verified subset", binary.span());
            var left = analyzePredicate(binary.left(), context, depth + 1);
            var right = analyzePredicate(binary.right(), context, depth + 1);
            var kind = binary.operator().equals("and")
                    ? SlotTypedQuery.JunctionKind.AND : SlotTypedQuery.JunctionKind.OR;
            return new SlotTypedQuery.Junction(kind, left, right, binary.span());
        }
        if (expression instanceof SlotAst.Comparison comparison)
            return analyzeComparison(comparison, context);
        if (expression instanceof SlotAst.Interval)
            throw error("DSL_INTERVAL_UNSUPPORTED", "between interval semantics are not in the verified subset", expression.span());
        throw error("DSL_SAFE_SUBSET", "Only direct indicator comparisons joined by and/or are supported",
                expression.span());
    }

    private SlotTypedQuery.MetricComparison analyzeComparison(SlotAst.Comparison comparison, Context context) {
        if (comparison.operator().equals("~="))
            throw error("DSL_APPROX_UNRESOLVED", "Approximation tolerance is unverified", comparison.span());
        if (!(comparison.left() instanceof SlotAst.Call call) || !call.function().equals("indicator"))
            throw error("DSL_SAFE_SUBSET", "Left side must be a direct indicator(...) call", comparison.left().span());
        var slots = call.slots();
        int[] unsupportedSlots = {0, 1, 4, 5, 6};
        for (int index : unsupportedSlots)
            if (!slots.get(index).value().isEmpty())
                throw error("DSL_SCOPE_UNRESOLVED", "Market, scope, select type, aggregation and count expressions require verified mappings",
                        slots.get(index).span());
        LocalDate date = parseAbsoluteDate(slots.get(3));
        if (context.date == null) context.date = date;
        else if (!context.date.equals(date))
            throw error("DSL_MIXED_DATES", "Safe subset requires one absolute date for every predicate",
                    slots.get(3).span());
        var metric = catalog.require(slots.get(2).value(), slots.get(2).span());
        var operator = switch (comparison.operator()) {
            case "=" -> SlotTypedQuery.ComparisonOperator.EQ;
            case "!=", "<>" -> SlotTypedQuery.ComparisonOperator.NE;
            case ">" -> SlotTypedQuery.ComparisonOperator.GT;
            case ">=" -> SlotTypedQuery.ComparisonOperator.GE;
            case "<" -> SlotTypedQuery.ComparisonOperator.LT;
            case "<=" -> SlotTypedQuery.ComparisonOperator.LE;
            default -> throw error("DSL_SAFE_SUBSET", "Unsupported comparison operator", comparison.span());
        };
        NumericLiteral literal = numericLiteral(comparison.right());
        if (metric.unit() == VerifiedIndicatorCatalog.Unit.PERCENT && !literal.percent()
                || metric.unit() == VerifiedIndicatorCatalog.Unit.NUMBER && literal.percent())
            throw error("DSL_UNIT_MISMATCH", "Literal unit does not match verified indicator unit",
                    comparison.right().span());
        try {
            long raw = literal.value().multiply(metric.rawPerDisplayUnit()).longValueExact();
            if (metric.column().storesInt32() && (raw < Integer.MIN_VALUE || raw > Integer.MAX_VALUE))
                throw error("DSL_RAW_RANGE", "Threshold exceeds the mapped INTEGER storage range",
                        comparison.right().span());
            return new SlotTypedQuery.MetricComparison(metric, operator, raw, comparison.span());
        } catch (ArithmeticException e) {
            throw error("DSL_SCALE_INEXACT", "Threshold cannot be represented exactly by stored integer units",
                    comparison.right().span());
        }
    }

    private static NumericLiteral numericLiteral(SlotAst.Expr expression) {
        int sign = 1;
        SlotAst.Expr value = expression;
        while (value instanceof SlotAst.Unary unary) {
            if (unary.operator().equals("-")) sign = -sign;
            else if (!unary.operator().equals("+"))
                throw error("DSL_SAFE_SUBSET", "Unsupported unary operator", unary.span());
            value = unary.operand();
        }
        if (!(value instanceof SlotAst.Literal literal)
                || literal.literalKind() != SlotAst.LiteralKind.NUMBER
                && literal.literalKind() != SlotAst.LiteralKind.PERCENT)
            throw error("DSL_SAFE_SUBSET", "Right side must be one numeric literal", expression.span());
        boolean percent = literal.literalKind() == SlotAst.LiteralKind.PERCENT;
        String text = percent ? literal.raw().substring(0, literal.raw().length() - 1) : literal.raw();
        return new NumericLiteral(new BigDecimal(text).multiply(BigDecimal.valueOf(sign)), percent);
    }

    private static LocalDate parseAbsoluteDate(SlotAst.Slot slot) {
        if (!slot.value().matches("\\d{4}-\\d{2}-\\d{2}"))
            throw error("DSL_DATE_UNRESOLVED", "Only an explicit ISO date is safe until relative-date rules are verified",
                    slot.span());
        try { return LocalDate.parse(slot.value()); }
        catch (DateTimeParseException e) {
            throw error("DSL_DATE_INVALID", "Invalid ISO date", slot.span());
        }
    }

    private static CompileException error(String code, String message, SlotAst.Span span) {
        return new CompileException(code, message, span.line(), span.column());
    }

    private record NumericLiteral(BigDecimal value, boolean percent) {}
    private static final class Context {
        LocalDate date;
        int nodes;
    }
}
