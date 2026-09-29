package com.acme.dorisdsl.rewrite;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompilationArtifact;

import java.math.BigDecimal;
import java.math.MathContext;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public final class RuleEngine {
    public static final String VERSION = "rules-1.0.0";
    private static final RewriteRule CONSTANT_FOLDING = rule("R-001", "numeric literal arithmetic",
            "both operands are numeric literals", "replace binary arithmetic with one numeric literal", "ALGEBRAIC_IDENTITY", 10);
    private static final RewriteRule BOOLEAN_SIMPLIFICATION = rule("R-002", "boolean literal identities",
            "AND/OR has a boolean literal operand", "remove neutral terms or collapse decisive terms", "BOOLEAN_ALGEBRA", 20);
    private static final RewriteRule DEDUPLICATE_PREDICATES = rule("R-003", "duplicate AND predicates",
            "AND tree contains equivalent predicate signatures", "remove repeated predicates", "IDEMPOTENT_AND", 30);
    private static final RewriteRule COMPARISON_CANONICALIZATION = rule("R-004", "literal-on-left comparison",
            "comparison has literal left and expression right", "swap operands and invert comparison direction", "COMPARISON_SYMMETRY", 40);
    private static final RewriteRule CANONICALIZE_TREE = rule("R-010", "expression tree canonical form",
            "typed AST is valid", "preserve predicate order after local rewrites", "SEMANTIC_PRESERVING", 100);

    public Result rewrite(Ast.Query query) {
        List<CompilationArtifact.RuleTrace> trace = new ArrayList<>();
        Ast.Expr where = query.where() == null ? null : rewriteExpr(query.where(), trace);
        where = where == null ? null : deduplicateAnd(where, trace);
        Ast.OrderBy orderBy = query.orderBy() == null ? null
                : new Ast.OrderBy(rewriteExpr(query.orderBy().expression(), trace), query.orderBy().direction());
        trace(trace, CANONICALIZE_TREE, "Canonicalized expression tree and preserved predicate order");
        return new Result(new Ast.Query(query.asOf(), query.context(), where, query.adjustment(), orderBy, query.limit(), query.span()), trace);
    }

    private Ast.Expr rewriteExpr(Ast.Expr expr, List<CompilationArtifact.RuleTrace> trace) {
        return switch (expr) {
            case Ast.Binary binary -> rewriteBinary(binary, trace);
            case Ast.Unary unary -> rewriteUnary(unary, trace);
            case Ast.FunctionCall call -> new Ast.FunctionCall(call.name(), call.arguments().stream().map(e -> rewriteExpr(e, trace)).toList(), call.type(), call.span());
            case Ast.Between between -> new Ast.Between(rewriteExpr(between.value(), trace), rewriteExpr(between.lower(), trace), rewriteExpr(between.upper(), trace), between.type(), between.span());
            case Ast.InList in -> new Ast.InList(rewriteExpr(in.value(), trace), in.options().stream().map(e -> rewriteExpr(e, trace)).toList(), in.type(), in.span());
            case Ast.IsNull isNull -> new Ast.IsNull(rewriteExpr(isNull.value(), trace), isNull.negated(), isNull.type(), isNull.span());
            case Ast.NamedArgument named -> new Ast.NamedArgument(named.name(), rewriteExpr(named.value(), trace), named.type(), named.span());
            default -> expr;
        };
    }

    private Ast.Expr rewriteBinary(Ast.Binary binary, List<CompilationArtifact.RuleTrace> trace) {
        Ast.Expr left = rewriteExpr(binary.left(), trace);
        Ast.Expr right = rewriteExpr(binary.right(), trace);
        String op = binary.operator().toUpperCase();
        Ast.Binary rewritten = new Ast.Binary(op, left, right, binary.type(), binary.span());
        Ast.Expr folded = foldNumeric(rewritten, trace);
        if (folded != rewritten) return folded;
        Ast.Expr simplified = simplifyBoolean(rewritten, trace);
        if (simplified != rewritten) return simplified;
        if (isComparison(op) && left instanceof Ast.Literal && !(right instanceof Ast.Literal)) {
            trace(trace, COMPARISON_CANONICALIZATION, "Moved literal to the right side of comparison");
            return new Ast.Binary(invert(op), right, left, binary.type(), binary.span());
        }
        return rewritten;
    }

    private Ast.Expr rewriteUnary(Ast.Unary unary, List<CompilationArtifact.RuleTrace> trace) {
        Ast.Expr operand = rewriteExpr(unary.operand(), trace);
        if (unary.operator().equalsIgnoreCase("NOT") && operand instanceof Ast.Literal literal
                && literal.value() instanceof Boolean value) {
            trace(trace, BOOLEAN_SIMPLIFICATION, "Folded NOT boolean literal");
            return new Ast.Literal(!value, Ast.DataType.BooleanSeries, unary.span());
        }
        return new Ast.Unary(unary.operator().toUpperCase(), operand, unary.type(), unary.span());
    }

    private Ast.Expr foldNumeric(Ast.Binary binary, List<CompilationArtifact.RuleTrace> trace) {
        if (binary.left() instanceof Ast.Literal l && binary.right() instanceof Ast.Literal r
                && l.value() instanceof BigDecimal lv && r.value() instanceof BigDecimal rv
                && binary.operator().matches("[+\\-*/]")) {
            BigDecimal value = switch (binary.operator()) {
                case "+" -> lv.add(rv);
                case "-" -> lv.subtract(rv);
                case "*" -> lv.multiply(rv);
                case "/" -> lv.divide(rv, MathContext.DECIMAL64);
                default -> throw new IllegalStateException();
            };
            trace(trace, CONSTANT_FOLDING, "Folded numeric constant expression");
            return new Ast.Literal(value, binary.type(), binary.span());
        }
        return binary;
    }

    private Ast.Expr simplifyBoolean(Ast.Binary binary, List<CompilationArtifact.RuleTrace> trace) {
        String op = binary.operator().toUpperCase();
        if (!op.equals("AND") && !op.equals("OR")) return binary;
        Boolean left = booleanLiteral(binary.left());
        Boolean right = booleanLiteral(binary.right());
        if (op.equals("AND")) {
            if (Boolean.TRUE.equals(left)) return traceAndReturn(trace, BOOLEAN_SIMPLIFICATION, "Removed TRUE left operand from AND", binary.right());
            if (Boolean.TRUE.equals(right)) return traceAndReturn(trace, BOOLEAN_SIMPLIFICATION, "Removed TRUE right operand from AND", binary.left());
            if (Boolean.FALSE.equals(left) || Boolean.FALSE.equals(right)) return traceAndReturn(trace, BOOLEAN_SIMPLIFICATION, "Collapsed AND with FALSE", new Ast.Literal(false, Ast.DataType.BooleanSeries, binary.span()));
        }
        if (op.equals("OR")) {
            if (Boolean.FALSE.equals(left)) return traceAndReturn(trace, BOOLEAN_SIMPLIFICATION, "Removed FALSE left operand from OR", binary.right());
            if (Boolean.FALSE.equals(right)) return traceAndReturn(trace, BOOLEAN_SIMPLIFICATION, "Removed FALSE right operand from OR", binary.left());
            if (Boolean.TRUE.equals(left) || Boolean.TRUE.equals(right)) return traceAndReturn(trace, BOOLEAN_SIMPLIFICATION, "Collapsed OR with TRUE", new Ast.Literal(true, Ast.DataType.BooleanSeries, binary.span()));
        }
        return binary;
    }

    private Ast.Expr deduplicateAnd(Ast.Expr expr, List<CompilationArtifact.RuleTrace> trace) {
        List<Ast.Expr> predicates = new ArrayList<>();
        flattenAnd(expr, predicates);
        if (predicates.size() < 2) return expr;
        Set<String> seen = new LinkedHashSet<>();
        List<Ast.Expr> unique = new ArrayList<>();
        for (Ast.Expr predicate : predicates) if (seen.add(signature(predicate))) unique.add(predicate);
        if (unique.size() == predicates.size()) return expr;
        trace(trace, DEDUPLICATE_PREDICATES, "Removed duplicate AND predicate");
        return rebuildAnd(unique, expr.type(), expr.span());
    }

    private void flattenAnd(Ast.Expr expr, List<Ast.Expr> out) {
        if (expr instanceof Ast.Binary binary && binary.operator().equalsIgnoreCase("AND")) {
            flattenAnd(binary.left(), out);
            flattenAnd(binary.right(), out);
        } else out.add(expr);
    }

    private Ast.Expr rebuildAnd(List<Ast.Expr> predicates, Ast.DataType type, Ast.SourceSpan span) {
        Ast.Expr result = predicates.get(0);
        for (int i = 1; i < predicates.size(); i++) result = new Ast.Binary("AND", result, predicates.get(i), type, span);
        return result;
    }

    private Ast.Expr traceAndReturn(List<CompilationArtifact.RuleTrace> trace, RewriteRule rule, String description, Ast.Expr expr) {
        trace(trace, rule, description);
        return expr;
    }

    private Boolean booleanLiteral(Ast.Expr expr) {
        return expr instanceof Ast.Literal literal && literal.value() instanceof Boolean value ? value : null;
    }

    private boolean isComparison(String op) { return op.matches("=|!=|<>|>|>=|<|<="); }

    private String invert(String op) {
        return switch (op) {
            case ">" -> "<";
            case ">=" -> "<=";
            case "<" -> ">";
            case "<=" -> ">=";
            default -> op;
        };
    }

    private String signature(Ast.Expr expr) {
        return switch (expr) {
            case Ast.Identifier id -> id.name();
            case Ast.Literal literal -> String.valueOf(literal.value());
            case Ast.FunctionCall call -> call.name() + "(" + call.arguments().stream().map(this::signature).reduce((a, b) -> a + "," + b).orElse("") + ")";
            case Ast.Binary binary -> "(" + signature(binary.left()) + binary.operator().toUpperCase() + signature(binary.right()) + ")";
            case Ast.Unary unary -> unary.operator().toUpperCase() + signature(unary.operand());
            case Ast.Between between -> signature(between.value()) + " BETWEEN " + signature(between.lower()) + " AND " + signature(between.upper());
            case Ast.InList in -> signature(in.value()) + " IN " + in.options().stream().map(this::signature).toList();
            case Ast.IsNull isNull -> signature(isNull.value()) + (isNull.negated() ? " IS NOT NULL" : " IS NULL");
            case Ast.NamedArgument named -> named.name() + "=" + signature(named.value());
        };
    }

    private static RewriteRule rule(String id, String pattern, String precondition, String transform, String proof, int priority) {
        return new RewriteRule(id, pattern, precondition, transform, proof, priority, "1.0.0", List.of());
    }

    private static void trace(List<CompilationArtifact.RuleTrace> trace, RewriteRule rule, String description) {
        trace.add(new CompilationArtifact.RuleTrace(rule.ruleId(), description, rule.semanticProofTag(), rule.priority(), rule.version()));
    }

    public record Result(Ast.Query query, List<CompilationArtifact.RuleTrace> trace) {
        public Result { trace = List.copyOf(trace); }
    }
}
