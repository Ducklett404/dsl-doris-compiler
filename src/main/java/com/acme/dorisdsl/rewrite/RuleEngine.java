package com.acme.dorisdsl.rewrite;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompilationArtifact;
import com.acme.dorisdsl.compiler.CompileException;

import java.math.BigDecimal;
import java.math.MathContext;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/** Deterministic, phased executor for a validated declarative rule set. */
public final class RuleEngine {
    private static final Comparator<RuleCatalog.RuleDefinition> ORDER = Comparator
            .comparingInt(RuleCatalog.RuleDefinition::priority).reversed()
            .thenComparing(RuleCatalog.RuleDefinition::id);
    private final RuleCatalog.RuleSet ruleSet;

    public RuleEngine(RuleCatalog.RuleSet ruleSet) { this.ruleSet = ruleSet; }

    public Result rewrite(Ast.Query input) {
        Ast.Query query = input;
        List<CompilationArtifact.RuleTrace> trace = new ArrayList<>();
        for (var phase : RuleCatalog.Phase.values()) {
            List<RuleCatalog.RuleDefinition> rules = ruleSet.rules().stream()
                    .filter(RuleCatalog.RuleDefinition::enabled)
                    .filter(rule -> rule.phase() == phase)
                    .sorted(ORDER).toList();
            if (rules.isEmpty()) continue;
            Set<String> seen = new HashSet<>();
            seen.add(query.toString());
            boolean converged = false;
            for (int iteration = 1; iteration <= ruleSet.maxIterations(); iteration++) {
                QueryRewrite rewritten = rewriteQuery(query, rules, phase, iteration, trace);
                if (!rewritten.changed()) { converged = true; break; }
                query = rewritten.query();
                if (!seen.add(query.toString())) throw failure("RULE_CYCLE",
                        "Rule cycle in " + phase + " for config " + ruleSet.version());
            }
            if (!converged) throw failure("RULE_ITERATION_LIMIT",
                    "Rule phase " + phase + " exceeded maxIterations=" + ruleSet.maxIterations());
        }
        return new Result(query, ruleSet.version(), trace);
    }

    private QueryRewrite rewriteQuery(Ast.Query query, List<RuleCatalog.RuleDefinition> rules,
                                      RuleCatalog.Phase phase, int iteration,
                                      List<CompilationArtifact.RuleTrace> trace) {
        NodeRewrite where = query.where() == null ? new NodeRewrite(null, false)
                : rewriteExpr(query.where(), rules, phase, iteration, trace);
        NodeRewrite order = query.orderBy() == null ? new NodeRewrite(null, false)
                : rewriteExpr(query.orderBy().expression(), rules, phase, iteration, trace);
        if (!where.changed() && !order.changed()) return new QueryRewrite(query, false);
        Ast.OrderBy orderBy = query.orderBy() == null ? null
                : new Ast.OrderBy(order.expr(), query.orderBy().direction());
        return new QueryRewrite(new Ast.Query(query.asOf(), where.expr(), query.adjustment(), orderBy,
                query.limit(), query.span()), true);
    }

    private NodeRewrite rewriteExpr(Ast.Expr original, List<RuleCatalog.RuleDefinition> rules,
                                    RuleCatalog.Phase phase, int iteration,
                                    List<CompilationArtifact.RuleTrace> trace) {
        Ast.Expr children = switch (original) {
            case Ast.Binary value -> new Ast.Binary(value.operator(),
                    rewriteExpr(value.left(), rules, phase, iteration, trace).expr(),
                    rewriteExpr(value.right(), rules, phase, iteration, trace).expr(), value.type(), value.span());
            case Ast.Unary value -> new Ast.Unary(value.operator(),
                    rewriteExpr(value.operand(), rules, phase, iteration, trace).expr(), value.type(), value.span());
            case Ast.FunctionCall value -> new Ast.FunctionCall(value.name(), value.arguments().stream()
                    .map(arg -> rewriteExpr(arg, rules, phase, iteration, trace).expr()).toList(), value.type(), value.span());
            case Ast.Between value -> new Ast.Between(
                    rewriteExpr(value.value(), rules, phase, iteration, trace).expr(),
                    rewriteExpr(value.lower(), rules, phase, iteration, trace).expr(),
                    rewriteExpr(value.upper(), rules, phase, iteration, trace).expr(), value.type(), value.span());
            case Ast.InList value -> new Ast.InList(rewriteExpr(value.value(), rules, phase, iteration, trace).expr(),
                    value.options().stream().map(arg -> rewriteExpr(arg, rules, phase, iteration, trace).expr()).toList(),
                    value.type(), value.span());
            default -> original;
        };
        boolean childrenChanged = !children.equals(original);
        List<RuleCatalog.RuleDefinition> candidates = rules.stream().filter(rule -> matches(rule, children)).toList();
        if (candidates.isEmpty()) return new NodeRewrite(children, childrenChanged);
        RuleCatalog.RuleDefinition winner = candidates.getFirst();
        List<RuleCatalog.RuleDefinition> conflicting = candidates.stream()
                .filter(rule -> rule.conflictGroup().equals(winner.conflictGroup())).toList();
        if (conflicting.size() > 1 && ruleSet.conflictPolicy() == RuleCatalog.ConflictPolicy.ERROR)
            throw failure("RULE_CONFLICT", "Rules conflict on " + nodeType(children) + ": "
                    + conflicting.stream().map(RuleCatalog.RuleDefinition::id).collect(Collectors.joining(",")));

        Ast.Expr output = apply(winner, children);
        if (nodeType(output) != winner.outputNodeType()) throw failure("RULE_OUTPUT_TYPE",
                winner.id() + " declared " + winner.outputNodeType() + " but produced " + nodeType(output));
        String conflict = conflicting.size() == 1 ? "NONE" : "HIGHEST_PRIORITY[" + winner.conflictGroup() + "]:"
                + winner.id() + ">" + conflicting.subList(1, conflicting.size()).stream().map(RuleCatalog.RuleDefinition::id)
                .collect(Collectors.joining(","));
        trace.add(new CompilationArtifact.RuleTrace(winner.id(), ruleSet.version(), phase.name(), iteration,
                nodeType(children).name(), nodeType(output).name(), winner.priority(), conflict,
                winner.equivalence(), winner.description()));
        return new NodeRewrite(output, true);
    }

    private boolean matches(RuleCatalog.RuleDefinition rule, Ast.Expr expr) {
        if (nodeType(expr) != rule.matchNodeType()) return false;
        var when = rule.when();
        if (!(expr instanceof Ast.Binary binary)) return when == null;
        if (when == null) return true;
        if (!when.operators().isEmpty() && !when.operators().contains(binary.operator())) return false;
        if (Boolean.TRUE.equals(when.numericLiteralOperands()) && !(numeric(binary.left()) && numeric(binary.right()))) return false;
        if (Boolean.TRUE.equals(when.nonZeroRightOperand()) && "/".equals(binary.operator()) && numeric(binary.right())
                && ((BigDecimal) ((Ast.Literal) binary.right()).value()).compareTo(BigDecimal.ZERO) == 0) return false;
        return !Boolean.TRUE.equals(when.commutativeOnly()) || Set.of("+", "*").contains(binary.operator());
    }

    private Ast.Expr apply(RuleCatalog.RuleDefinition rule, Ast.Expr expr) {
        Ast.Binary binary = (Ast.Binary) expr;
        return switch (rule.action()) {
            case FOLD_NUMERIC_BINARY -> {
                BigDecimal left = (BigDecimal) ((Ast.Literal) binary.left()).value();
                BigDecimal right = (BigDecimal) ((Ast.Literal) binary.right()).value();
                BigDecimal value = switch (binary.operator()) {
                    case "+" -> left.add(right);
                    case "-" -> left.subtract(right);
                    case "*" -> left.multiply(right);
                    case "/" -> left.divide(right, MathContext.DECIMAL64);
                    default -> throw failure("RULE_ACTION_INVALID", "Unsupported numeric operator: " + binary.operator());
                };
                yield new Ast.Literal(value, binary.type(), binary.span());
            }
            case SWAP_COMMUTATIVE_OPERANDS -> new Ast.Binary(binary.operator(), binary.right(), binary.left(),
                    binary.type(), binary.span());
        };
    }

    private static boolean numeric(Ast.Expr expression) {
        return expression instanceof Ast.Literal literal && literal.value() instanceof BigDecimal;
    }

    private static RuleCatalog.NodeType nodeType(Ast.Expr expression) {
        return switch (expression) {
            case Ast.Literal ignored -> RuleCatalog.NodeType.LITERAL;
            case Ast.Identifier ignored -> RuleCatalog.NodeType.IDENTIFIER;
            case Ast.FunctionCall ignored -> RuleCatalog.NodeType.FUNCTION_CALL;
            case Ast.Binary ignored -> RuleCatalog.NodeType.BINARY;
            case Ast.Unary ignored -> RuleCatalog.NodeType.UNARY;
            case Ast.Between ignored -> RuleCatalog.NodeType.BETWEEN;
            case Ast.InList ignored -> RuleCatalog.NodeType.IN_LIST;
        };
    }

    private static CompileException failure(String code, String message) {
        return new CompileException(code, message, 1, 1);
    }

    private record NodeRewrite(Ast.Expr expr, boolean changed) {}
    private record QueryRewrite(Ast.Query query, boolean changed) {}
    public record Result(Ast.Query query, String ruleConfigVersion, List<CompilationArtifact.RuleTrace> trace) {
        public Result { trace = List.copyOf(trace); }
    }
}
