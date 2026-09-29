package com.acme.dorisdsl.competition;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/** In-memory result oracle for deterministic fixtures; not a substitute for live Doris verification. */
public final class SlotSafeReferenceEvaluator {
    public record QuoteRow(int mktcode, String tgtcode, LocalDate bizdate,
                           Map<VerifiedIndicatorCatalog.Column, Long> values) {
        public QuoteRow { values = Map.copyOf(values); }
    }
    public record SecurityKey(int mktcode, String tgtcode) {}

    public List<SecurityKey> select(SlotTypedQuery.Query query, List<QuoteRow> rows) {
        List<SecurityKey> matches = new ArrayList<>();
        for (QuoteRow row : rows) {
            if (row.bizdate().equals(query.asOf()) && matches(query.filter(), row))
                matches.add(new SecurityKey(row.mktcode(), row.tgtcode()));
        }
        matches.sort(Comparator.comparingInt(SecurityKey::mktcode).thenComparing(SecurityKey::tgtcode));
        return List.copyOf(matches);
    }

    private static boolean matches(SlotTypedQuery.Predicate predicate, QuoteRow row) {
        if (predicate instanceof SlotTypedQuery.Junction junction) {
            if (junction.kind() == SlotTypedQuery.JunctionKind.AND)
                return matches(junction.left(), row) && matches(junction.right(), row);
            return matches(junction.left(), row) || matches(junction.right(), row);
        }
        var comparison = (SlotTypedQuery.MetricComparison) predicate;
        Long value = row.values().get(comparison.metric().column());
        if (value == null) return false; // SQL NULL is not selected by positive AND/OR comparisons.
        return switch (comparison.operator()) {
            case EQ -> value == comparison.rawThreshold();
            case NE -> value != comparison.rawThreshold();
            case GT -> value > comparison.rawThreshold();
            case GE -> value >= comparison.rawThreshold();
            case LT -> value < comparison.rawThreshold();
            case LE -> value <= comparison.rawThreshold();
        };
    }
}
