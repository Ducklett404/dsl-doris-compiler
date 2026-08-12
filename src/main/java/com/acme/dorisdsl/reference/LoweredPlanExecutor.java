package com.acme.dorisdsl.reference;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.compiler.CompilationArtifact;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class LoweredPlanExecutor {
    private final ExpressionRuntime runtime = new ExpressionRuntime();

    public List<String> execute(CompilationArtifact artifact, ReferenceDataSet data) {
        Ast.Query query = artifact.ast();
        LocalDate scanFrom = scanStart(query.asOf(), artifact.requiredLookbackTradingDays(), data.tradingDays());
        Map<String, List<ReferenceDataSet.QuoteRow>> scans = new HashMap<>();
        data.quotes().stream().filter(row -> !row.tradeDate().isBefore(scanFrom) && !row.tradeDate().isAfter(query.asOf()))
                .forEach(row -> scans.computeIfAbsent(row.symbol(), ignored -> new ArrayList<>()).add(row));
        List<ReferenceExecutor.Candidate> candidates = new ArrayList<>();
        for (var rows : scans.values()) {
            for (int index = 0; index < rows.size(); index++) {
                var row = rows.get(index);
                if (!row.tradeDate().equals(query.asOf())) continue;
                var values = values(rows, index, data);
                if (runtime.predicate(query.where(), values)) {
                    Object order = query.orderBy() == null ? null : runtime.evaluate(query.orderBy().expression(), values);
                    candidates.add(new ReferenceExecutor.Candidate(row.symbol(), order));
                }
            }
        }
        ReferenceExecutor.sort(candidates, query.orderBy());
        return candidates.stream().limit(query.limit()).map(ReferenceExecutor.Candidate::symbol).toList();
    }

    private ExpressionRuntime.Values values(List<ReferenceDataSet.QuoteRow> rows, int index, ReferenceDataSet data) {
        return new ExpressionRuntime.Values() {
            @Override public Object identifier(Ast.Identifier identifier) { return rows.get(index).fields().get(identifier.name()); }
            @Override public Object function(Ast.FunctionCall function) {
                String name = function.name().toUpperCase(Locale.ROOT);
                return switch (name) {
                    case "MA" -> window(function.arguments().get(0), ExpressionRuntime.integer(function.arguments().get(1)), rows, index, data);
                    case "CROSS_UP" -> cross(function, rows, index, data);
                    case "PE_TTM", "ROE_TTM" -> pit(name, rows.get(index), data);
                    case "ABS" -> ExpressionRuntime.number(runtime.evaluate(function.arguments().get(0), this)).abs();
                    default -> throw new IllegalArgumentException("Unsupported lowered function: " + name);
                };
            }
        };
    }

    private BigDecimal window(Ast.Expr input, int length, List<ReferenceDataSet.QuoteRow> rows, int index,
                              ReferenceDataSet data) {
        if (index + 1 < length) return null;
        List<BigDecimal> values = new ArrayList<>();
        for (int i = index - length + 1; i <= index; i++) {
            Object value = runtime.evaluate(input, values(rows, i, data));
            if (value == null) return null;
            values.add(ExpressionRuntime.number(value));
        }
        return ExpressionRuntime.average(values);
    }

    private boolean cross(Ast.FunctionCall function, List<ReferenceDataSet.QuoteRow> rows, int index,
                          ReferenceDataSet data) {
        if (index < 1) return false;
        Object left = runtime.evaluate(function.arguments().get(0), values(rows, index, data));
        Object right = runtime.evaluate(function.arguments().get(1), values(rows, index, data));
        Object previousLeft = runtime.evaluate(function.arguments().get(0), values(rows, index - 1, data));
        Object previousRight = runtime.evaluate(function.arguments().get(1), values(rows, index - 1, data));
        return left != null && right != null && previousLeft != null && previousRight != null
                && ExpressionRuntime.number(left).compareTo(ExpressionRuntime.number(right)) > 0
                && ExpressionRuntime.number(previousLeft).compareTo(ExpressionRuntime.number(previousRight)) <= 0;
    }

    private BigDecimal pit(String function, ReferenceDataSet.QuoteRow quote, ReferenceDataSet data) {
        return data.financials().stream().filter(row -> row.symbol().equals(quote.symbol())
                        && !row.visibleFrom().isAfter(quote.tradeDate()) && quote.tradeDate().isBefore(row.visibleTo()))
                .max(Comparator.comparing(ReferenceDataSet.FinancialRow::visibleFrom))
                .map(row -> row.value(function)).orElse(null);
    }

    private LocalDate scanStart(LocalDate target, int lookback, List<LocalDate> tradingDays) {
        int targetIndex = tradingDays.indexOf(target);
        if (targetIndex < 0) return target;
        return tradingDays.get(Math.max(0, targetIndex - lookback));
    }
}
