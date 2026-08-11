package com.acme.dorisdsl.rewrite;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompilationArtifact;

import java.math.BigDecimal;
import java.math.MathContext;
import java.util.ArrayList;
import java.util.List;

public final class RuleEngine {
    public Result rewrite(Ast.Query query) {
        List<CompilationArtifact.RuleTrace> trace = new ArrayList<>();
        Ast.Expr where = query.where() == null ? null : fold(query.where(), trace);
        Ast.OrderBy orderBy = query.orderBy() == null ? null
                : new Ast.OrderBy(fold(query.orderBy().expression(), trace), query.orderBy().direction());
        trace.add(new CompilationArtifact.RuleTrace("R-010", "Canonicalized expression tree and preserved predicate order"));
        return new Result(new Ast.Query(query.asOf(), query.context(), where, query.adjustment(), orderBy, query.limit(), query.span()), trace);
    }

    private Ast.Expr fold(Ast.Expr expr, List<CompilationArtifact.RuleTrace> trace) {
        return switch (expr) {
            case Ast.Binary binary -> {
                Ast.Expr left = fold(binary.left(), trace);
                Ast.Expr right = fold(binary.right(), trace);
                if (left instanceof Ast.Literal l && right instanceof Ast.Literal r
                        && l.value() instanceof BigDecimal lv && r.value() instanceof BigDecimal rv
                        && binary.operator().matches("[+\\-*/]")) {
                    BigDecimal value = switch (binary.operator()) {
                        case "+" -> lv.add(rv);
                        case "-" -> lv.subtract(rv);
                        case "*" -> lv.multiply(rv);
                        case "/" -> lv.divide(rv, MathContext.DECIMAL64);
                        default -> throw new IllegalStateException();
                    };
                    trace.add(new CompilationArtifact.RuleTrace("R-001", "Folded numeric constant expression"));
                    yield new Ast.Literal(value, binary.type(), binary.span());
                }
                yield new Ast.Binary(binary.operator(), left, right, binary.type(), binary.span());
            }
            case Ast.Unary unary -> new Ast.Unary(unary.operator(), fold(unary.operand(), trace), unary.type(), unary.span());
            case Ast.FunctionCall call -> new Ast.FunctionCall(call.name(), call.arguments().stream().map(e -> fold(e, trace)).toList(), call.type(), call.span());
            case Ast.Between between -> new Ast.Between(fold(between.value(), trace), fold(between.lower(), trace), fold(between.upper(), trace), between.type(), between.span());
            case Ast.InList in -> new Ast.InList(fold(in.value(), trace), in.options().stream().map(e -> fold(e, trace)).toList(), in.type(), in.span());
            case Ast.IsNull isNull -> new Ast.IsNull(fold(isNull.value(), trace), isNull.negated(), isNull.type(), isNull.span());
            case Ast.NamedArgument named -> new Ast.NamedArgument(named.name(), fold(named.value(), trace), named.type(), named.span());
            default -> expr;
        };
    }

    public record Result(Ast.Query query, List<CompilationArtifact.RuleTrace> trace) {
        public Result { trace = List.copyOf(trace); }
    }
}
