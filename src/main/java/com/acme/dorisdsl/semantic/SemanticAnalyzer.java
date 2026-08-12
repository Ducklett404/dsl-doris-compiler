package com.acme.dorisdsl.semantic;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.registry.Registry;

import java.util.ArrayList;

public final class SemanticAnalyzer {
    private final Registry registry;

    public SemanticAnalyzer(Registry registry) { this.registry = registry; }

    public Ast.Query analyze(Ast.Query query) {
        if (query.limit() < 1 || query.limit() > 10_000)
            throw error("LIMIT_RANGE", "LIMIT must be between 1 and 10000", query.span());
        Ast.Expr where = query.where() == null ? null : infer(query.where());
        if (where != null && where.type() != Ast.DataType.BOOLEAN)
            throw error("WHERE_TYPE", "WHERE expression must be boolean", where.span());
        Ast.OrderBy orderBy = query.orderBy() == null ? null
                : new Ast.OrderBy(infer(query.orderBy().expression()), query.orderBy().direction());
        return new Ast.Query(query.asOf(), where, query.adjustment(), orderBy, query.limit(), query.span());
    }

    private Ast.Expr infer(Ast.Expr expr) {
        return switch (expr) {
            case Ast.Literal value -> value;
            case Ast.Identifier id -> {
                var field = registry.field(id.name(), id.span().line(), id.span().column());
                yield new Ast.Identifier(id.name(), field.type(), id.span());
            }
            case Ast.FunctionCall call -> {
                var definition = registry.function(call.name(), call.span().line(), call.span().column());
                int count = call.arguments().size();
                if (count < definition.minArgs() || count > definition.maxArgs())
                    throw error("FUNCTION_ARITY", call.name() + " expects " + definition.minArgs() + ".." + definition.maxArgs() + " arguments", call.span());
                var arguments = call.arguments().stream().map(this::infer).toList();
                if (isWindowFunction(definition.loweringKind())) {
                    requireNumeric(arguments.get(0));
                    if (!(arguments.get(1) instanceof Ast.Literal l) || l.type() != Ast.DataType.NUMBER)
                        throw error("WINDOW_LITERAL", call.name() + " window must be a numeric literal", arguments.get(1).span());
                }
                if (definition.loweringKind() == com.acme.dorisdsl.registry.RegistryConfig.LoweringKind.CROSS_UP ||
                        definition.loweringKind() == com.acme.dorisdsl.registry.RegistryConfig.LoweringKind.CROSS_DOWN) {
                    requireNumeric(arguments.get(0));
                    requireNumeric(arguments.get(1));
                }
                yield new Ast.FunctionCall(call.name(), arguments, definition.returnType(), call.span());
            }
            case Ast.Binary binary -> inferBinary(binary);
            case Ast.Unary unary -> {
                Ast.Expr operand = infer(unary.operand());
                if (unary.operator().equalsIgnoreCase("NOT")) {
                    if (operand.type() != Ast.DataType.BOOLEAN) throw error("NOT_TYPE", "NOT requires boolean", unary.span());
                    yield new Ast.Unary("NOT", operand, Ast.DataType.BOOLEAN, unary.span());
                }
                requireNumeric(operand);
                yield new Ast.Unary(unary.operator(), operand, operand.type(), unary.span());
            }
            case Ast.Between between -> {
                Ast.Expr value = infer(between.value());
                Ast.Expr lower = infer(between.lower());
                Ast.Expr upper = infer(between.upper());
                requireComparable(value, lower, between.span());
                requireComparable(value, upper, between.span());
                yield new Ast.Between(value, lower, upper, Ast.DataType.BOOLEAN, between.span());
            }
            case Ast.InList in -> {
                Ast.Expr value = infer(in.value());
                var options = new ArrayList<Ast.Expr>();
                for (Ast.Expr option : in.options()) {
                    Ast.Expr typed = infer(option);
                    requireComparable(value, typed, in.span());
                    options.add(typed);
                }
                if (options.isEmpty()) throw error("EMPTY_IN", "IN list cannot be empty", in.span());
                yield new Ast.InList(value, options, Ast.DataType.BOOLEAN, in.span());
            }
        };
    }

    private Ast.Expr inferBinary(Ast.Binary binary) {
        Ast.Expr left = infer(binary.left());
        Ast.Expr right = infer(binary.right());
        String op = binary.operator().toUpperCase();
        if (op.equals("AND") || op.equals("OR")) {
            if (left.type() != Ast.DataType.BOOLEAN || right.type() != Ast.DataType.BOOLEAN)
                throw error("BOOLEAN_TYPE", op + " requires boolean operands", binary.span());
            return new Ast.Binary(op, left, right, Ast.DataType.BOOLEAN, binary.span());
        }
        if (op.matches("=|!=|<>|>|>=|<|<=")) {
            requireComparable(left, right, binary.span());
            return new Ast.Binary(op, left, right, Ast.DataType.BOOLEAN, binary.span());
        }
        requireNumeric(left);
        requireNumeric(right);
        Ast.DataType result = left.type() == Ast.DataType.PRICE ? Ast.DataType.PRICE : Ast.DataType.NUMBER;
        return new Ast.Binary(op, left, right, result, binary.span());
    }

    private void requireComparable(Ast.Expr left, Ast.Expr right, Ast.SourceSpan span) {
        if (left.type() == Ast.DataType.NULL || right.type() == Ast.DataType.NULL) return;
        if (isNumeric(left.type()) && isNumeric(right.type())) return;
        if (left.type() != right.type()) throw error("TYPE_MISMATCH", "Cannot compare " + left.type() + " with " + right.type(), span);
    }

    private void requireNumeric(Ast.Expr expr) {
        if (!isNumeric(expr.type())) throw error("NUMERIC_TYPE", "Expected numeric expression, got " + expr.type(), expr.span());
    }

    private boolean isNumeric(Ast.DataType type) {
        return switch (type) {
            case NUMBER, PRICE, RATIO, PERCENT, VOLUME -> true;
            default -> false;
        };
    }

    private boolean isWindowFunction(com.acme.dorisdsl.registry.RegistryConfig.LoweringKind kind) {
        return switch (kind) {
            case WINDOW_AVG, WINDOW_EMA, WINDOW_STDDEV, RETURN_N, RSI -> true;
            default -> false;
        };
    }

    private CompileException error(String code, String message, Ast.SourceSpan span) {
        return new CompileException(code, message, span.line(), span.column());
    }
}
