package com.acme.dorisdsl.semantic;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.registry.RegistryConfig;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public final class SemanticAnalyzer {
    public static final int MAX_EXPRESSION_DEPTH = 64;
    public static final int MAX_IN_LIST_SIZE = 500;
    public static final int MAX_WINDOW_LENGTH = 500;
    public static final int MAX_CONTEXT_LIST_SIZE = 200;
    private static final Set<String> ALLOWED_CONTEXT_KEYS = Set.of("MARKET", "INDUSTRY", "UNIVERSE", "USER");
    private static final Set<String> ALLOWED_WINDOW_UNITS = Set.of("TRADING_DAY");
    private final Registry registry;

    public SemanticAnalyzer(Registry registry) { this.registry = registry; }

    public Ast.Query analyze(Ast.Query query) {
        if (query.limit() < 1 || query.limit() > 10_000)
            throw error("LIMIT_RANGE", "LIMIT must be between 1 and 10000", query.span());
        validateContext(query.context(), query.span());
        Ast.Expr where = query.where() == null ? null : infer(query.where(), 1);
        if (where != null && where.type() != Ast.DataType.BooleanSeries)
            throw typeError("WHERE_TYPE", "WHERE expression must be BooleanSeries", where,
                    "Use comparison, IS NULL, IN, BETWEEN, CROSS_UP, or boolean operators in WHERE.");
        Ast.OrderBy orderBy = query.orderBy() == null ? null
                : new Ast.OrderBy(validateOrderBy(infer(query.orderBy().expression(), 1)), query.orderBy().direction());
        return new Ast.Query(query.asOf(), query.context(), where, query.adjustment(), orderBy, query.limit(), query.span());
    }

    private Ast.Expr infer(Ast.Expr expr, int depth) {
        if (depth > MAX_EXPRESSION_DEPTH) throw error("EXPRESSION_DEPTH", "Expression depth exceeds " + MAX_EXPRESSION_DEPTH, expr.span());
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
                var arguments = call.arguments().stream().map(argument -> inferFunctionArgument(argument, depth + 1)).toList();
                if (definition.loweringKind() == RegistryConfig.LoweringKind.WINDOW_AVG) {
                    validateWindowFunction(call.name(), arguments, call.span());
                }
                if (definition.loweringKind() == RegistryConfig.LoweringKind.CROSS_UP) {
                    requireTimeSeries(arguments.get(0), "CROSS_UP operands must be numeric series ordered by symbol and trade_date.");
                    requireTimeSeries(arguments.get(1), "CROSS_UP operands must be numeric series ordered by symbol and trade_date.");
                }
                if (definition.loweringKind() == RegistryConfig.LoweringKind.RANK_BY) validateRankBy(call.name(), arguments, call.span());
                yield new Ast.FunctionCall(call.name(), arguments, definition.returnType(), call.span());
            }
            case Ast.Binary binary -> inferBinary(binary, depth);
            case Ast.Unary unary -> {
                Ast.Expr operand = infer(unary.operand(), depth + 1);
                if (unary.operator().equalsIgnoreCase("NOT")) {
                    if (operand.type() != Ast.DataType.BooleanSeries)
                        throw typeError("NOT_TYPE", "NOT requires BooleanSeries", operand,
                                "Apply NOT to a predicate, for example NOT (CLOSE IS NULL).");
                    yield new Ast.Unary("NOT", operand, Ast.DataType.BooleanSeries, unary.span());
                }
                requireNumeric(operand);
                yield new Ast.Unary(unary.operator(), operand, operand.type(), unary.span());
            }
            case Ast.Between between -> {
                Ast.Expr value = infer(between.value(), depth + 1);
                Ast.Expr lower = infer(between.lower(), depth + 1);
                Ast.Expr upper = infer(between.upper(), depth + 1);
                requireComparable(value, lower, between.span());
                requireComparable(value, upper, between.span());
                yield new Ast.Between(value, lower, upper, Ast.DataType.BooleanSeries, between.span());
            }
            case Ast.InList in -> {
                Ast.Expr value = infer(in.value(), depth + 1);
                if (in.options().size() > MAX_IN_LIST_SIZE)
                    throw error("IN_LIST_TOO_LARGE", "IN list cannot contain more than " + MAX_IN_LIST_SIZE + " values", in.span());
                var options = new ArrayList<Ast.Expr>();
                for (Ast.Expr option : in.options()) {
                    Ast.Expr typed = infer(option, depth + 1);
                    requireComparable(value, typed, in.span());
                    options.add(typed);
                }
                if (options.isEmpty()) throw error("EMPTY_IN", "IN list cannot be empty", in.span());
                yield new Ast.InList(value, options, Ast.DataType.BooleanSeries, in.span());
            }
            case Ast.IsNull isNull -> {
                Ast.Expr value = infer(isNull.value(), depth + 1);
                yield new Ast.IsNull(value, isNull.negated(), Ast.DataType.BooleanSeries, isNull.span());
            }
            case Ast.NamedArgument named -> throw error("NAMED_ARGUMENT_POSITION", "Named arguments are only allowed inside function calls", named.span());
        };
    }

    private Ast.Expr inferFunctionArgument(Ast.Expr argument, int depth) {
        if (argument instanceof Ast.NamedArgument named) {
            return new Ast.NamedArgument(named.name(), inferNamedValue(named), Ast.DataType.UNKNOWN, named.span());
        }
        return infer(argument, depth);
    }

    private Ast.Expr inferNamedValue(Ast.NamedArgument named) {
        if ("UNIT".equals(named.name())) {
            if (named.value() instanceof Ast.Identifier id)
                return new Ast.Literal(id.name(), Ast.DataType.StringCategory, id.span());
            if (named.value() instanceof Ast.Literal literal && literal.type() == Ast.DataType.StringCategory)
                return literal;
            throw error("WINDOW_UNIT", "Window unit must be TRADING_DAY", named.span());
        }
        return infer(named.value(), 1);
    }

    private Ast.Expr inferBinary(Ast.Binary binary, int depth) {
        Ast.Expr left = infer(binary.left(), depth + 1);
        Ast.Expr right = infer(binary.right(), depth + 1);
        String op = binary.operator().toUpperCase();
        if (op.equals("AND") || op.equals("OR")) {
            if (left.type() != Ast.DataType.BooleanSeries || right.type() != Ast.DataType.BooleanSeries)
                throw typeError("BOOLEAN_TYPE", op + " requires BooleanSeries operands", binary,
                        "Use AND/OR only between predicates.");
            return new Ast.Binary(op, left, right, Ast.DataType.BooleanSeries, binary.span());
        }
        if (op.matches("=|!=|<>|>|>=|<|<=")) {
            requireComparable(left, right, binary.span());
            return new Ast.Binary(op, left, right, Ast.DataType.BooleanSeries, binary.span());
        }
        requireNumeric(left);
        requireNumeric(right);
        if ((isSeries(left.type()) && isSeries(right.type()) && left.type() != right.type())
                || (!isSeries(left.type()) && !isSeries(right.type()) && left.type() != right.type())) {
            throw typeError("TYPE_MISMATCH", "Cannot apply " + op + " to " + left.type() + " and " + right.type(), binary,
                    "Use arithmetic only between compatible numeric series or between numeric scalars.");
        }
        Ast.DataType result = arithmeticResult(left.type(), right.type());
        return new Ast.Binary(op, left, right, result, binary.span());
    }

    private void validateWindowFunction(String name, List<Ast.Expr> arguments, Ast.SourceSpan span) {
        if (arguments.size() < 2 || arguments.get(0) instanceof Ast.NamedArgument || arguments.get(1) instanceof Ast.NamedArgument)
            throw error("WINDOW_ARGUMENTS", name + " requires value and numeric window positional arguments", span);
        requireTimeSeries(arguments.get(0), name + " first argument must be a numeric time series.");
        if (!(arguments.get(1) instanceof Ast.Literal l) || l.type() != Ast.DataType.ScalarNumber)
            throw typeError("WINDOW_LITERAL", name + " window must be a ScalarNumber literal", arguments.get(1),
                    "Use an integer literal window, for example MA(CLOSE, 20, unit=TRADING_DAY).");
        int window = literalInt(l);
        if (window < 1 || window > MAX_WINDOW_LENGTH)
            throw error("WINDOW_RANGE", "Window must be between 1 and " + MAX_WINDOW_LENGTH, arguments.get(1).span());
        if (arguments.size() == 3) {
            if (!(arguments.get(2) instanceof Ast.NamedArgument named) || !"UNIT".equals(named.name()))
                throw error("WINDOW_UNIT", name + " third argument must be unit=TRADING_DAY", arguments.get(2).span());
            Object value = ((Ast.Literal) named.value()).value();
            if (!(value instanceof String unit) || !ALLOWED_WINDOW_UNITS.contains(unit.toUpperCase(Locale.ROOT)))
                throw error("WINDOW_UNIT", "Window unit must be TRADING_DAY", named.span());
        }
    }

    private void validateRankBy(String name, List<Ast.Expr> arguments, Ast.SourceSpan span) {
        if (arguments.isEmpty() || arguments.get(0) instanceof Ast.NamedArgument)
            throw error("RANK_ARGUMENTS", name + " requires a positional numeric expression", span);
        requireNumeric(arguments.get(0));
        if (arguments.size() == 2) {
            Ast.Expr direction = arguments.get(1);
            if (direction instanceof Ast.NamedArgument named) {
                if (!"DIRECTION".equals(named.name())) throw error("RANK_DIRECTION", "RANK_BY named argument must be direction", named.span());
                direction = named.value();
            }
            if (!(direction instanceof Ast.Literal literal) || literal.type() != Ast.DataType.StringCategory)
                throw error("RANK_DIRECTION", "RANK_BY direction must be ASC or DESC", direction.span());
            String value = literal.value().toString().toUpperCase(Locale.ROOT);
            if (!value.equals("ASC") && !value.equals("DESC"))
                throw error("RANK_DIRECTION", "RANK_BY direction must be ASC or DESC", direction.span());
        }
    }

    private void requireComparable(Ast.Expr left, Ast.Expr right, Ast.SourceSpan span) {
        if (left.type() == Ast.DataType.NULL || right.type() == Ast.DataType.NULL) return;
        if (isNumeric(left.type()) && isNumeric(right.type())) return;
        if (left.type() != right.type()) throw new CompileException("TYPE_MISMATCH",
                "Cannot compare " + left.type() + " with " + right.type(), span.line(), span.column(),
                left.type() + " vs " + right.type(), "Compare values with compatible domain types.");
    }

    private void requireNumeric(Ast.Expr expr) {
        if (!isNumeric(expr.type())) throw typeError("NUMERIC_TYPE", "Expected numeric expression, got " + expr.type(), expr,
                "Use a PriceSeries, RatioSeries, Percent, VolumeSeries, or ScalarNumber expression.");
    }

    private boolean isNumeric(Ast.DataType type) {
        return switch (type) {
            case ScalarNumber, PriceSeries, RatioSeries, Percent, VolumeSeries -> true;
            default -> false;
        };
    }

    private boolean isSeries(Ast.DataType type) {
        return switch (type) {
            case PriceSeries, RatioSeries, VolumeSeries, BooleanSeries -> true;
            default -> false;
        };
    }

    private boolean isTimeSeries(Ast.DataType type) {
        return switch (type) {
            case PriceSeries, RatioSeries, VolumeSeries -> true;
            default -> false;
        };
    }

    private void requireTimeSeries(Ast.Expr expr, String suggestion) {
        if (!isTimeSeries(expr.type())) throw typeError("SERIES_TYPE", "Expected numeric time series, got " + expr.type(), expr, suggestion);
    }

    private Ast.DataType arithmeticResult(Ast.DataType left, Ast.DataType right) {
        if (left == Ast.DataType.PriceSeries || right == Ast.DataType.PriceSeries) return Ast.DataType.PriceSeries;
        if (left == Ast.DataType.VolumeSeries || right == Ast.DataType.VolumeSeries) return Ast.DataType.VolumeSeries;
        if (left == Ast.DataType.RatioSeries || right == Ast.DataType.RatioSeries) return Ast.DataType.RatioSeries;
        if (left == Ast.DataType.Percent || right == Ast.DataType.Percent) return Ast.DataType.Percent;
        return Ast.DataType.ScalarNumber;
    }

    private Ast.Expr validateOrderBy(Ast.Expr expr) {
        if (expr.type() == Ast.DataType.BooleanSeries || expr.type() == Ast.DataType.SecurityId || expr.type() == Ast.DataType.TradeDate) {
            throw typeError("ORDER_BY_TYPE", "ORDER BY expression must resolve to a target-date scalar value", expr,
                    "Order by a numeric metric, rank, price, ratio, volume, or string category available on the target date.");
        }
        return expr;
    }

    private int literalInt(Ast.Literal literal) {
        try {
            return ((BigDecimal) literal.value()).intValueExact();
        } catch (ArithmeticException e) {
            throw error("WINDOW_LITERAL", "Window must be an integer literal", literal.span());
        }
    }

    private void validateContext(Ast.QueryContext context, Ast.SourceSpan span) {
        for (var entry : context.values().entrySet()) {
            String key = entry.getKey().toUpperCase(Locale.ROOT);
            if (!ALLOWED_CONTEXT_KEYS.contains(key)) throw error("CONTEXT_KEY", "Unsupported context key: " + entry.getKey(), span);
            if (entry.getValue().isEmpty()) throw error("CONTEXT_EMPTY", "Context value cannot be empty: " + entry.getKey(), span);
            if (entry.getValue().size() > MAX_CONTEXT_LIST_SIZE)
                throw error("CONTEXT_LIST_TOO_LARGE", "Context list cannot contain more than " + MAX_CONTEXT_LIST_SIZE + " values", span);
            for (Object value : entry.getValue()) {
                if (!(value instanceof String)) throw error("CONTEXT_VALUE", "Context values must be strings", span);
            }
        }
    }

    private CompileException error(String code, String message, Ast.SourceSpan span) {
        return new CompileException(code, message, span.line(), span.column());
    }

    private CompileException typeError(String code, String message, Ast.Expr expr, String suggestion) {
        return new CompileException(code, message, expr.span().line(), expr.span().column(), describe(expr), suggestion);
    }

    private String describe(Ast.Expr expr) {
        return switch (expr) {
            case Ast.Literal literal -> literal.value() == null ? "NULL" : literal.value().toString();
            case Ast.Identifier id -> id.name();
            case Ast.FunctionCall call -> call.name() + "(...)";
            case Ast.Binary binary -> describe(binary.left()) + " " + binary.operator() + " " + describe(binary.right());
            case Ast.Unary unary -> unary.operator() + " " + describe(unary.operand());
            case Ast.Between between -> describe(between.value()) + " BETWEEN ...";
            case Ast.InList in -> describe(in.value()) + " IN [...]";
            case Ast.IsNull isNull -> describe(isNull.value()) + (isNull.negated() ? " IS NOT NULL" : " IS NULL");
            case Ast.NamedArgument named -> named.name() + "=" + describe(named.value());
        };
    }
}
