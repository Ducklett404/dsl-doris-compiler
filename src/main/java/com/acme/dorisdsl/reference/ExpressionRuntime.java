package com.acme.dorisdsl.reference;

import com.acme.dorisdsl.ast.Ast;

import java.math.BigDecimal;
import java.math.MathContext;
import java.util.List;
import java.util.Objects;

final class ExpressionRuntime {
    interface Values {
        Object identifier(Ast.Identifier identifier);
        Object function(Ast.FunctionCall function);
    }

    Object evaluate(Ast.Expr expr, Values values) {
        return switch (expr) {
            case Ast.Literal literal -> literal.value();
            case Ast.Identifier identifier -> values.identifier(identifier);
            case Ast.FunctionCall function -> values.function(function);
            case Ast.Unary unary -> unary(unary.operator(), evaluate(unary.operand(), values));
            case Ast.Binary binary -> binary(binary.operator(), evaluate(binary.left(), values), evaluate(binary.right(), values));
            case Ast.Between between -> compare(evaluate(between.value(), values), evaluate(between.lower(), values)) >= 0
                    && compare(evaluate(between.value(), values), evaluate(between.upper(), values)) <= 0;
            case Ast.InList in -> {
                Object value = evaluate(in.value(), values);
                yield in.options().stream().map(option -> evaluate(option, values)).anyMatch(option -> equal(value, option));
            }
        };
    }

    boolean predicate(Ast.Expr expr, Values values) { return expr == null || Boolean.TRUE.equals(evaluate(expr, values)); }

    private Object unary(String operator, Object value) {
        if (value == null) return null;
        return switch (operator.toUpperCase()) {
            case "NOT" -> !((Boolean) value); case "+" -> value; case "-" -> number(value).negate();
            default -> throw new IllegalArgumentException("Unsupported unary operator: " + operator);
        };
    }

    private Object binary(String operator, Object left, Object right) {
        String op = operator.toUpperCase();
        if (op.equals("AND")) return Boolean.TRUE.equals(left) && Boolean.TRUE.equals(right);
        if (op.equals("OR")) return Boolean.TRUE.equals(left) || Boolean.TRUE.equals(right);
        if (left == null || right == null) return null;
        return switch (op) {
            case "+" -> number(left).add(number(right)); case "-" -> number(left).subtract(number(right));
            case "*" -> number(left).multiply(number(right)); case "/" -> number(left).divide(number(right), MathContext.DECIMAL64);
            case "=" -> equal(left, right); case "!=", "<>" -> !equal(left, right);
            case ">" -> compare(left, right) > 0; case ">=" -> compare(left, right) >= 0;
            case "<" -> compare(left, right) < 0; case "<=" -> compare(left, right) <= 0;
            default -> throw new IllegalArgumentException("Unsupported binary operator: " + operator);
        };
    }

    private boolean equal(Object left, Object right) {
        return left instanceof Number && right instanceof Number
                ? number(left).compareTo(number(right)) == 0 : Objects.equals(left, right);
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private int compare(Object left, Object right) {
        if (left == null || right == null) return -1;
        if (left instanceof Number && right instanceof Number) return number(left).compareTo(number(right));
        return ((Comparable) left).compareTo(right);
    }

    static BigDecimal number(Object value) {
        return value instanceof BigDecimal decimal ? decimal : new BigDecimal(value.toString());
    }

    static int integer(Ast.Expr expr) {
        return ((BigDecimal) ((Ast.Literal) expr).value()).intValueExact();
    }

    static BigDecimal average(List<BigDecimal> values) {
        if (values.isEmpty()) return null;
        return values.stream().reduce(BigDecimal.ZERO, BigDecimal::add)
                .divide(BigDecimal.valueOf(values.size()), MathContext.DECIMAL64);
    }
}
