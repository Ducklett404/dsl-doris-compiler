package com.acme.dorisdsl.stockslot;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

final class DorisExplainEstimateTest {
    @Test void takesLargestRecognizedDorisEstimate() {
        assertEquals(13_650_347, DorisQueryExecutor.parseEstimatedRows(List.of(
                "cardinality=5,573", "rows: 13650347", "estimated rows = 100")));
    }

    @Test void refusesUnknownExplainShape() {
        assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of("PLAN FRAGMENT 0", "unknown estimate")));
    }

    @Test void acceptsExplicitEmptySetWithoutScanEstimate() {
        assertEquals(0, DorisQueryExecutor.parseEstimatedRows(List.of(
                "PLAN FRAGMENT 0", "  VRESULT SINK", "  0:VEMPTYSET(490)")));
        assertEquals(0, DorisQueryExecutor.parseEstimatedRows(List.of("  0:EMPTYSET")));
    }

    @Test void emptySetDoesNotHideUnknownScanOrOperator() {
        assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of(
                "  2:VHASH JOIN", "  |----1:VEMPTYSET", "  0:VOlapScanNode")));
        assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of("  1:VEMPTYSET", "  0:UNKNOWN_OPERATOR")));
    }

    @Test void emptySetInTextIsNotAPlanNode() {
        assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of("output: 'VEMPTYSET'", "PLAN FRAGMENT 0")));
    }
}
