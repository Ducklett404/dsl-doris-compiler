package com.acme.dorisdsl.competition;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Parameterized Doris SQL for one-date, verified direct-indicator comparisons only. */
public final class SlotSafeSqlCompiler {
    private final SlotDslParserFacade parser = new SlotDslParserFacade();
    private final SlotSemanticAnalyzer semanticAnalyzer;

    public SlotSafeSqlCompiler(VerifiedIndicatorCatalog catalog) {
        semanticAnalyzer = new SlotSemanticAnalyzer(Objects.requireNonNull(catalog));
    }

    public record Artifact(SlotTypedQuery.Query typedQuery, String sql, List<Object> bindings) {
        public Artifact { bindings = List.copyOf(bindings); }
    }

    public Artifact compile(String source) {
        SlotTypedQuery.Query typed = semanticAnalyzer.analyze(parser.parse(source));
        List<Object> bindings = new ArrayList<>();
        bindings.add(typed.asOf());
        String predicate = render(typed.filter(), bindings);
        String sql = "SELECT q.`mktcode`, q.`tgtcode`\n"
                + "FROM `newzl`.`hsj_stock_hq_basic` AS q\n"
                + "WHERE q.`bizdate` = ? AND (" + predicate + ")\n"
                + "ORDER BY q.`mktcode`, q.`tgtcode`";
        return new Artifact(typed, sql, bindings);
    }

    private static String render(SlotTypedQuery.Predicate predicate, List<Object> bindings) {
        if (predicate instanceof SlotTypedQuery.Junction junction) {
            String left = render(junction.left(), bindings);
            String right = render(junction.right(), bindings);
            return "(" + left + (junction.kind() == SlotTypedQuery.JunctionKind.AND ? " AND " : " OR ")
                    + right + ")";
        }
        var comparison = (SlotTypedQuery.MetricComparison) predicate;
        bindings.add(comparison.rawThreshold());
        String operator = switch (comparison.operator()) {
            case EQ -> "=";
            case NE -> "<>";
            case GT -> ">";
            case GE -> ">=";
            case LT -> "<";
            case LE -> "<=";
        };
        return "q.`" + comparison.metric().column().sqlName() + "` " + operator + " ?";
    }
}
