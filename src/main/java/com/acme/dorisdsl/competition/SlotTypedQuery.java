package com.acme.dorisdsl.competition;

import java.time.LocalDate;

/** Narrow, typed representation of the currently safe direct-indicator subset. */
public final class SlotTypedQuery {
    private SlotTypedQuery() {}

    public record Query(LocalDate asOf, Predicate filter, SlotAst.Span span) {}
    public sealed interface Predicate permits Junction, MetricComparison {
        SlotAst.Span span();
    }
    public enum JunctionKind { AND, OR }
    public record Junction(JunctionKind kind, Predicate left, Predicate right, SlotAst.Span span)
            implements Predicate {}
    public enum ComparisonOperator { EQ, NE, GT, GE, LT, LE }
    public record MetricComparison(VerifiedIndicatorCatalog.Metric metric, ComparisonOperator operator,
                                   long rawThreshold, SlotAst.Span span) implements Predicate {}
}
