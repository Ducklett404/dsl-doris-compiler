package com.acme.dorisdsl.stockslot;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class StockSlotSemanticAnalyzer {
    private static final Set<String> SELECT_TYPES = Set.of(
            "行业", "概念", "指数", "板块", "可转债", "债券", "场内基金", "场外基金", "公募基金",
            "私募基金", "ETF", "LOF", "REITs", "期货", "货币");
    private static final Pattern DIRECTION = Pattern.compile("^(asc|desc)(?:(?::)(rank|dense_rank|row_number))?$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern COUNT = Pattern.compile("^(CONS|EXIST)(>=|<=|!=|=|>|<)(每|\\d+)(年|季度|月|周|日)?$");
    private static final Pattern REPORT_PERIOD = Pattern.compile("(1季报|半年报|3季报|年报)");
    private static final Pattern OFFSET = Pattern.compile("(开始|前|后)(\\d+)(年|季度|月|周|日)");
    private static final Pattern RANGE = Pattern.compile("^[\\[(][^,]+,[^,]+[\\])]$");
    private static final Pattern MA = Pattern.compile("^(\\d+)(年|季度|月|周|日)均线$");
    private static final Pattern RSI = Pattern.compile("^RSI\\((\\d+)\\)$", Pattern.CASE_INSENSITIVE);
    private static final Pattern SELF_SELECTED_GROUP = Pattern.compile("^我的自选股_(.+)分组$");

    private final StockSlotRegistry registry;

    public StockSlotSemanticAnalyzer(StockSlotRegistry registry) { this.registry = registry; }

    public Result analyze(StockSlotAst.Document document) {
        List<StockSlotDiagnostic> diagnostics = new ArrayList<>();
        List<StockSlotAst.CallSemantics> calls = new ArrayList<>();
        StockSlotAst.Expr expression = infer(document.expression(), diagnostics, calls);
        if (expression.type() != StockSlotAst.ValueType.BOOLEAN && expression.type() != StockSlotAst.ValueType.UNKNOWN)
            unsupported(diagnostics, "ROOT_NOT_BOOLEAN", "Top-level stock selection expression must be boolean", expression.span());

        StockSlotAst.SelectionLimit limit = document.selectionLimit();
        if (limit != null && (limit.minimum() < 0 || (limit.maximum() != -1 && limit.maximum() < limit.minimum())))
            unsupported(diagnostics, "SELECTION_LIMIT_RANGE",
                    "limit x,y requires x >= 0 and y = -1 or y >= x", limit.span());
        var typed = new StockSlotAst.Document(expression, limit, document.span());
        return new Result(new StockSlotAst.SemanticModel(typed, calls), diagnostics);
    }

    private StockSlotAst.Expr infer(StockSlotAst.Expr expression, List<StockSlotDiagnostic> diagnostics,
                                    List<StockSlotAst.CallSemantics> calls) {
        return switch (expression) {
            case StockSlotAst.Literal literal -> literal;
            case StockSlotAst.Unary unary -> {
                StockSlotAst.Expr operand = infer(unary.operand(), diagnostics, calls);
                if (!numeric(operand.type()))
                    unsupported(diagnostics, "UNARY_NUMERIC", "Unary +/- requires a numeric value", unary.span());
                yield new StockSlotAst.Unary(unary.operator(), operand, operand.type(), unary.span());
            }
            case StockSlotAst.FunctionCall call -> inferCall(call, diagnostics, calls);
            case StockSlotAst.Binary binary -> inferBinary(binary, diagnostics, calls);
        };
    }

    private StockSlotAst.Expr inferCall(StockSlotAst.FunctionCall call, List<StockSlotDiagnostic> diagnostics,
                                        List<StockSlotAst.CallSemantics> calls) {
        StockSlotRegistryConfig.FunctionDefinition definition;
        try { definition = registry.function(call.name()); }
        catch (RuntimeException e) {
            unsupported(diagnostics, "UNSUPPORTED_FUNCTION", "Unsupported stock-slot-v1 function: " + call.name(), call.span());
            return new StockSlotAst.FunctionCall(call.name(), call.arguments(), StockSlotAst.ValueType.UNKNOWN, call.span());
        }
        if (call.arguments().size() != definition.parameters().size()) {
            unsupported(diagnostics, "FUNCTION_ARITY", call.name() + " requires exactly " + definition.parameters().size()
                    + " arguments, got " + call.arguments().size(), call.span());
            return new StockSlotAst.FunctionCall(call.name(), call.arguments(), definition.returnType(), call.span());
        }

        List<StockSlotAst.SlotSemantics> slots = new ArrayList<>();
        for (int i = 0; i < call.arguments().size(); i++) {
            StockSlotAst.Expr argument = call.arguments().get(i);
            var parameter = definition.parameters().get(i);
            String slot = parameter.name();
            if (!(argument instanceof StockSlotAst.Literal literal) || literal.type() != StockSlotAst.ValueType.STRING) {
                unsupported(diagnostics, "SLOT_LITERAL_REQUIRED", call.name() + "." + slot
                        + " must be a quoted string (empty string is allowed)", argument.span());
                slots.add(new StockSlotAst.SlotSemantics(slot, null, null));
                continue;
            }
            String raw = (String) literal.value();
            slots.add(new StockSlotAst.SlotSemantics(slot, raw,
                    structureSlot(parameter.type(), slot, raw, argument.span(), diagnostics)));
        }
        calls.add(new StockSlotAst.CallSemantics(call.name(), call.span(), slots));
        StockSlotAst.ValueType returnType = definition.returnType();
        if (definition.returnTypeFromParameter() != null) {
            for (int i = 0; i < definition.parameters().size(); i++) {
                if (!definition.parameters().get(i).name().equals(definition.returnTypeFromParameter())) continue;
                if (call.arguments().get(i) instanceof StockSlotAst.Literal literal && literal.value() instanceof String name) {
                    try { returnType = registry.indicator(name).valueType(); }
                    catch (RuntimeException ignored) { returnType = StockSlotAst.ValueType.UNKNOWN; }
                }
            }
        }
        return new StockSlotAst.FunctionCall(call.name(), call.arguments(), returnType, call.span());
    }

    private Object structureSlot(StockSlotRegistryConfig.ParameterType type, String slot, String raw, StockSlotAst.SourceSpan span,
                                 List<StockSlotDiagnostic> diagnostics) {
        return switch (type) {
            case SET -> {
                StockSlotAst.SetExpr set = parseSet(raw, span, diagnostics);
                if (slot.equals("market")) for (String term : setTerms(set))
                    if (!registry.recognizedMarkets().contains(term))
                        unsupported(diagnostics, "UNSUPPORTED_MARKET", "Unknown market: " + term, span);
                if (slot.equals("select_type")) for (String term : setTerms(set))
                    if (!SELECT_TYPES.contains(term))
                        unsupported(diagnostics, "UNSUPPORTED_SELECT_TYPE", "Unknown select_type: " + term, span);
                yield set;
            }
            case DIRECTION -> {
                if (!DIRECTION.matcher(raw).matches())
                    unsupported(diagnostics, "UNSUPPORTED_DIRECTION",
                            "direction must be asc/desc or asc|desc:rank|dense_rank|row_number", span);
                yield raw.toLowerCase(Locale.ROOT);
            }
            case AGGREGATION -> {
                String normalized = raw.toUpperCase(Locale.ROOT);
                if (!registry.allowedAggregations().contains(normalized))
                    unsupported(diagnostics, "UNSUPPORTED_AGGREGATION", "Unknown agg_func: " + raw, span);
                yield normalized;
            }
            case COUNT_EXPRESSION -> count(raw, span, diagnostics);
            case DATE, PERIOD -> time(raw);
            case INDICATOR -> indicator(raw);
            case STRING, SECURITY -> raw;
        };
    }

    private StockSlotAst.Expr inferBinary(StockSlotAst.Binary binary, List<StockSlotDiagnostic> diagnostics,
                                          List<StockSlotAst.CallSemantics> calls) {
        StockSlotAst.Expr left = infer(binary.left(), diagnostics, calls);
        StockSlotAst.Expr right = infer(binary.right(), diagnostics, calls);
        String operator = binary.operator().toUpperCase(Locale.ROOT);
        if (operator.matches("AND|OR|THEN")) {
            requireBoolean(left, operator, diagnostics, binary.span());
            requireBoolean(right, operator, diagnostics, binary.span());
            if (operator.equals("THEN") && !containsRank(right))
                unsupported(diagnostics, "THEN_REQUIRES_RANK", "then may only introduce an expression containing rank", right.span());
            return new StockSlotAst.Binary(operator, left, right, StockSlotAst.ValueType.BOOLEAN, binary.span());
        }
        if (operator.matches("[+\\-*/]")) {
            if (!numericOrUnknown(left.type()) || !numericOrUnknown(right.type()))
                unsupported(diagnostics, "ARITHMETIC_TYPE", operator + " requires numeric indicators", binary.span());
            return new StockSlotAst.Binary(operator, left, right, StockSlotAst.ValueType.NUMBER, binary.span());
        }
        if (operator.equals("BETWEEN") && (!(right instanceof StockSlotAst.Literal literal)
                || literal.type() != StockSlotAst.ValueType.STRING || !RANGE.matcher((String) literal.value()).matches()))
            unsupported(diagnostics, "BETWEEN_RANGE", "between requires a quoted interval such as '[1,5)'", right.span());
        return new StockSlotAst.Binary(operator, left, right, StockSlotAst.ValueType.BOOLEAN, binary.span());
    }

    private StockSlotAst.SetExpr parseSet(String raw, StockSlotAst.SourceSpan span,
                                          List<StockSlotDiagnostic> diagnostics) {
        if (raw.isEmpty()) return new StockSlotAst.SetTerm("");
        try {
            return new SetParser(raw).parse();
        } catch (IllegalArgumentException e) {
            unsupported(diagnostics, "SET_EXPRESSION", e.getMessage(), span);
            return new StockSlotAst.SetTerm(raw);
        }
    }

    private List<String> setTerms(StockSlotAst.SetExpr expression) {
        List<String> result = new ArrayList<>();
        collectSetTerms(expression, result);
        result.removeIf(String::isEmpty);
        return result;
    }

    private void collectSetTerms(StockSlotAst.SetExpr expression, List<String> result) {
        switch (expression) {
            case StockSlotAst.SetTerm term -> result.add(term.value());
            case StockSlotAst.SetUnary unary -> collectSetTerms(unary.operand(), result);
            case StockSlotAst.SetBinary binary -> {
                collectSetTerms(binary.left(), result);
                collectSetTerms(binary.right(), result);
            }
        }
    }

    private Object count(String raw, StockSlotAst.SourceSpan span, List<StockSlotDiagnostic> diagnostics) {
        if (raw.isEmpty()) return null;
        Matcher matcher = COUNT.matcher(raw);
        if (!matcher.matches()) {
            unsupported(diagnostics, "COUNT_EXPRESSION", "Invalid CONS/EXIST expression: " + raw, span);
            return raw;
        }
        return new StockSlotAst.CountExpression(matcher.group(1), matcher.group(2), matcher.group(3), matcher.group(4));
    }

    private StockSlotAst.TimeExpression time(String raw) {
        Matcher report = REPORT_PERIOD.matcher(raw);
        List<StockSlotAst.TimeOffset> offsets = new ArrayList<>();
        Matcher offset = OFFSET.matcher(raw);
        while (offset.find()) offsets.add(new StockSlotAst.TimeOffset(offset.group(1),
                Integer.parseInt(offset.group(2)), offset.group(3)));
        return new StockSlotAst.TimeExpression(raw, report.find() ? report.group(1) : null, offsets);
    }

    private StockSlotAst.IndicatorInstantiation indicator(String raw) {
        Matcher matcher = MA.matcher(raw);
        if (matcher.matches()) return new StockSlotAst.IndicatorInstantiation(raw, "X" + matcher.group(2) + "均线",
                Map.of("X", matcher.group(1)));
        matcher = RSI.matcher(raw);
        if (matcher.matches()) return new StockSlotAst.IndicatorInstantiation(raw, "RSI(N)", Map.of("N", matcher.group(1)));
        matcher = SELF_SELECTED_GROUP.matcher(raw);
        if (matcher.matches()) return new StockSlotAst.IndicatorInstantiation(raw, "我的自选股_STR分组", Map.of("STR", matcher.group(1)));
        return new StockSlotAst.IndicatorInstantiation(raw, raw, Map.of());
    }

    private void requireBoolean(StockSlotAst.Expr expression, String operator,
                                List<StockSlotDiagnostic> diagnostics, StockSlotAst.SourceSpan span) {
        if (expression.type() != StockSlotAst.ValueType.BOOLEAN && expression.type() != StockSlotAst.ValueType.UNKNOWN)
            unsupported(diagnostics, "BOOLEAN_TYPE", operator + " requires boolean operands", span);
    }

    private boolean containsRank(StockSlotAst.Expr expression) {
        return switch (expression) {
            case StockSlotAst.FunctionCall call -> call.name().equalsIgnoreCase("rank");
            case StockSlotAst.Binary binary -> containsRank(binary.left()) || containsRank(binary.right());
            case StockSlotAst.Unary unary -> containsRank(unary.operand());
            default -> false;
        };
    }

    private boolean numeric(StockSlotAst.ValueType type) {
        return type == StockSlotAst.ValueType.NUMBER || type == StockSlotAst.ValueType.PERCENT;
    }
    private boolean numericOrUnknown(StockSlotAst.ValueType type) { return numeric(type) || type == StockSlotAst.ValueType.UNKNOWN; }

    private void unsupported(List<StockSlotDiagnostic> diagnostics, String code, String message,
                             StockSlotAst.SourceSpan span) {
        diagnostics.add(new StockSlotDiagnostic("ERROR", code, message, span.line(), span.column()));
    }

    public record Result(StockSlotAst.SemanticModel semanticModel, List<StockSlotDiagnostic> diagnostics) {
        public Result { diagnostics = List.copyOf(diagnostics); }
    }

    private static final class SetParser {
        private final String source;
        private int index;
        private SetParser(String source) { this.source = source; }

        private StockSlotAst.SetExpr parse() {
            StockSlotAst.SetExpr result = parseOr();
            if (index != source.length()) throw error();
            return result;
        }
        private StockSlotAst.SetExpr parseOr() {
            StockSlotAst.SetExpr result = parseXor();
            while (take('|')) result = new StockSlotAst.SetBinary("|", result, parseXor());
            return result;
        }
        private StockSlotAst.SetExpr parseXor() {
            StockSlotAst.SetExpr result = parseAnd();
            while (take('^')) result = new StockSlotAst.SetBinary("^", result, parseAnd());
            return result;
        }
        private StockSlotAst.SetExpr parseAnd() {
            StockSlotAst.SetExpr result = parseUnary();
            while (take('&')) result = new StockSlotAst.SetBinary("&", result, parseUnary());
            return result;
        }
        private StockSlotAst.SetExpr parseUnary() {
            if (take('^')) return new StockSlotAst.SetUnary("^", parseUnary());
            int start = index;
            while (index < source.length() && "|&^".indexOf(source.charAt(index)) < 0) index++;
            String value = source.substring(start, index).trim();
            if (value.isEmpty()) throw error();
            return new StockSlotAst.SetTerm(value);
        }
        private boolean take(char expected) {
            if (index < source.length() && source.charAt(index) == expected) { index++; return true; }
            return false;
        }
        private IllegalArgumentException error() {
            return new IllegalArgumentException("Invalid set expression near offset " + index + ": " + source);
        }
    }
}
