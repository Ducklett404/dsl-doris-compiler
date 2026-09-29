package com.acme.dorisdsl.reference;

import com.acme.dorisdsl.ast.Ast;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

public final class ReferenceExecutor {
    private final ExpressionRuntime runtime = new ExpressionRuntime();

    public List<String> execute(Ast.Query query, ReferenceDataSet data) {
        List<Candidate> candidates = new ArrayList<>();
        for (var row : data.quotes()) {
            if (!row.tradeDate().equals(query.asOf())) continue;
            var values = values(row, data);
            if (runtime.predicate(query.where(), values))
                candidates.add(new Candidate(row.symbol(), orderValue(query, values)));
        }
        sort(candidates, query.orderBy());
        return candidates.stream().limit(query.limit()).map(Candidate::symbol).toList();
    }

    private ExpressionRuntime.Values values(ReferenceDataSet.QuoteRow row, ReferenceDataSet data) {
        return new ExpressionRuntime.Values() {
            @Override public Object identifier(Ast.Identifier identifier) { return row.fields().get(identifier.name()); }
            @Override public Object function(Ast.FunctionCall function) {
                String name = function.name().toUpperCase(Locale.ROOT);
                return switch (name) {
                    case "MA" -> movingAverage(function.arguments().get(0), ExpressionRuntime.integer(function.arguments().get(1)), row, data);
                    case "CROSS_UP" -> crossUp(function, row, data);
                    case "PE_TTM", "ROE_TTM" -> financial(name, row.symbol(), row.tradeDate(), data);
                    case "ABS" -> ExpressionRuntime.number(runtime.evaluate(function.arguments().get(0), this)).abs();
                    default -> throw new IllegalArgumentException("Unsupported reference function: " + name);
                };
            }
        };
    }

    private BigDecimal movingAverage(Ast.Expr input, int window, ReferenceDataSet.QuoteRow row, ReferenceDataSet data) {
        List<ReferenceDataSet.QuoteRow> history = history(row.symbol(), row.tradeDate(), data);
        int end = history.indexOf(row);
        if (end + 1 < window) return null;
        List<BigDecimal> values = new ArrayList<>();
        for (int i = end - window + 1; i <= end; i++) {
            Object value = runtime.evaluate(input, values(history.get(i), data));
            if (value == null) return null;
            values.add(ExpressionRuntime.number(value));
        }
        return ExpressionRuntime.average(values);
    }

    private boolean crossUp(Ast.FunctionCall function, ReferenceDataSet.QuoteRow row, ReferenceDataSet data) {
        List<ReferenceDataSet.QuoteRow> history = history(row.symbol(), row.tradeDate(), data);
        int index = history.indexOf(row);
        if (index < 1) return false;
        var previous = history.get(index - 1);
        Object leftNow = runtime.evaluate(function.arguments().get(0), values(row, data));
        Object rightNow = runtime.evaluate(function.arguments().get(1), values(row, data));
        Object leftPrevious = runtime.evaluate(function.arguments().get(0), values(previous, data));
        Object rightPrevious = runtime.evaluate(function.arguments().get(1), values(previous, data));
        return leftNow != null && rightNow != null && leftPrevious != null && rightPrevious != null
                && ExpressionRuntime.number(leftNow).compareTo(ExpressionRuntime.number(rightNow)) > 0
                && ExpressionRuntime.number(leftPrevious).compareTo(ExpressionRuntime.number(rightPrevious)) <= 0;
    }

    private BigDecimal financial(String function, String symbol, LocalDate date, ReferenceDataSet data) {
        return data.financials().stream().filter(row -> row.symbol().equals(symbol)
                        && !row.visibleFrom().isAfter(date) && date.isBefore(row.visibleTo()))
                .max(Comparator.comparing(ReferenceDataSet.FinancialRow::visibleFrom))
                .map(row -> row.value(function)).orElse(null);
    }

    private List<ReferenceDataSet.QuoteRow> history(String symbol, LocalDate through, ReferenceDataSet data) {
        return data.quotes().stream().filter(row -> row.symbol().equals(symbol) && !row.tradeDate().isAfter(through)).toList();
    }

    private Object orderValue(Ast.Query query, ExpressionRuntime.Values values) {
        return query.orderBy() == null ? null : runtime.evaluate(query.orderBy().expression(), values);
    }

    static void sort(List<Candidate> values, Ast.OrderBy orderBy) {
        Comparator<Candidate> comparator = orderBy == null ? Comparator.comparing(Candidate::symbol)
                : Comparator.comparing(Candidate::orderValue, Comparator.nullsLast((a, b) -> compareValues(a, b)))
                .thenComparing(Candidate::symbol);
        if (orderBy != null && orderBy.direction() == Ast.Direction.DESC) comparator = comparator.reversed();
        values.sort(comparator);
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private static int compareValues(Object left, Object right) {
        if (left instanceof Number && right instanceof Number)
            return ExpressionRuntime.number(left).compareTo(ExpressionRuntime.number(right));
        return ((Comparable) left).compareTo(right);
    }

    record Candidate(String symbol, Object orderValue) {}
}
