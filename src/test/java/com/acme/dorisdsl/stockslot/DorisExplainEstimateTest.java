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

    @Test void acceptsRunV5AbsentDateRankPlanWithOnlyPureWrappersAboveEmptySource() {
        // Complete main EXPLAIN captured in run-v5/absent-2000-01-01--1-plans.json.
        // Kept in the test, not read dynamically from reports, so CI is independent.
        String explain = """
                PLAN FRAGMENT 0
                  OUTPUT EXPRS:
                    mktcode[#29]
                    tgtcode[#30]
                  PARTITION: UNPARTITIONED

                  HAS_COLO_PLAN_NODE: false

                  VRESULT SINK
                     MYSQL_PROTOCOL

                  9:VSORT(1389)
                  |  order by: r1[#28] ASC
                  |  algorithm: full sort
                  |  offset: 0
                  |  final projections: mktcode[#26], tgtcode[#27]
                  |  final project output tuple id: 10
                  |  distribute expr lists:
                  |
                  8:VANALYTIC(1377)
                  |  functions: [row_number()]
                  |  order by: v1[#21] DESC NULLS LAST, mktcode[#19] ASC NULLS FIRST, tgtcode[#20] ASC NULLS FIRST
                  |  window: ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                  |  predicates: (r1[#22] <= 5)
                  |  final projections: mktcode[#19], tgtcode[#20], r1[#22]
                  |  final project output tuple id: 8
                  |  distribute expr lists:
                  |
                  7:VMERGING-EXCHANGE
                     offset: 0
                     distribute expr lists: mktcode[#19], tgtcode[#20]

                PLAN FRAGMENT 1

                  PARTITION: HASH_PARTITIONED: mktcode[#4], tgtcode[#5]

                  HAS_COLO_PLAN_NODE: false

                  STREAM DATA SINK
                    EXCHANGE ID: 07
                    UNPARTITIONED
                IS_MERGE: true

                  6:VSORT(1365)
                  |  order by: v1[#21] DESC, mktcode[#19] ASC, tgtcode[#20] ASC
                  |  algorithm: full sort
                  |  local merge sort
                  |  merge by exchange
                  |  offset: 0
                  |  distribute expr lists:
                  |
                  5:VPartitionTopN(1361)
                  |  functions: row_number
                  |  order by: v1[#18] DESC, mktcode[#16] ASC, tgtcode[#17] ASC
                  |  has global limit: false
                  |  partition limit: 5
                  |  partition topn phase: TWO_PHASE_LOCAL_PTOPN
                  |  distribute expr lists: mktcode[#13], tgtcode[#14]
                  |
                  4:VANALYTIC(1349)
                  |  functions: [row_number()]
                  |  partition by: mktcode[#8], tgtcode[#9]
                  |  order by: bizdate[#10] DESC NULLS LAST
                  |  window: ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                  |  predicates: (bizdate[#10] = '2000-01-01'), (observation_rank[#12] <= 1), avgPx[#11] IS NOT NULL
                  |  final projections: mktcode[#8], tgtcode[#9], avgPx[#11]
                  |  final project output tuple id: 4
                  |  distribute expr lists: mktcode[#8], tgtcode[#9]
                  |
                  3:VSORT(1345)
                  |  order by: mktcode[#8] ASC, tgtcode[#9] ASC, bizdate[#10] DESC
                  |  algorithm: full sort
                  |  offset: 0
                  |  distribute expr lists: mktcode[#4], tgtcode[#5]
                  |
                  2:VEXCHANGE
                     offset: 0
                     distribute expr lists:

                PLAN FRAGMENT 2

                  PARTITION: UNPARTITIONED

                  HAS_COLO_PLAN_NODE: false

                  STREAM DATA SINK
                    EXCHANGE ID: 02
                    HASH_PARTITIONED: mktcode[#4], tgtcode[#5]

                  1:VPartitionTopN(1337)
                  |  functions: row_number
                  |  partition by: mktcode[#0], tgtcode[#1]
                  |  order by: bizdate[#6] DESC
                  |  has global limit: false
                  |  partition limit: 1
                  |  partition topn phase: TWO_PHASE_LOCAL_PTOPN
                  |  distribute expr lists:
                  |
                  0:VEMPTYSET(1333)



                ========== STATISTICS ==========
                """;
        assertEquals(0, DorisQueryExecutor.parseEstimatedRows(explain.lines().toList()));
    }

    @Test void emptySourceWrapperProofRequiresAnEmptySourceNotJustKnownOperators() {
        assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of(
                "  2:VSORT(1)", "  1:VANALYTIC(2)", "  0:VEXCHANGE")));
        assertEquals(0, DorisQueryExecutor.parseEstimatedRows(List.of(
                "  2:vsort(1)", "  |----1:vemptyset(2)", "  0:emptyset")));
    }

    @Test void emptySourceCannotHideScansJoinsUnionsTableFunctionsOrUnknownOperators() {
        for (String operator : List.of("VOlapScanNode", "VFILE_SCAN_NODE", "VHASH JOIN", "VNESTED LOOP JOIN",
                "VUNION", "VTABLE_FUNCTION_NODE", "TABLE_FUNCTION", "UNKNOWN_OPERATOR")) {
            assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of(
                    "  2:VSORT(1)", "  |----1:VEMPTYSET(2)", "  0:" + operator)), operator);
        }
    }

    @Test void wrapperNamesMustMatchEntireTokenWithoutUnknownSuffixOrAdditionalWords() {
        for (String name : List.of("VSORT_UNKNOWN", "VSORT-UNKNOWN", "VSORT MALICIOUS",
                "VMERGING", "VMERGING-EXCHANGE_UNKNOWN", "VMERGING-EXCHANGE MALICIOUS",
                "VANALYTIC_EXTRA", "VPartitionTopNExtra", "VEXCHANGE_HIDDEN_SCAN")) {
            assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of(
                    "  1:" + name + "(123)", "  0:VEMPTYSET(1)")), name);
        }
    }

    @Test void malformedNumberedHeadersDoNotDisappearFromTheEmptySourceProof() {
        for (String header : List.of("1.5:VSORT(12)", "1e3:VSORT(12)", "-1:VSORT(12)",
                "x1:VSORT(12)", "1 junk:VSORT(12)", "1 :VSORT(12)", "1::VSORT(12)",
                "1:VSORT()", "1:VSORT(12x)", "1:VSORT(12) extra", "|----x:VSORT(12)",
                "1:VSORT(12);", "1:VSORT(12):extra", "1 VSORT(12)", "1", "1.5 VSORT(12)")) {
            assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of(
                    "  " + header, "  0:VEMPTYSET(1)")), header);
        }
    }

    @Test void nonnumericUnknownHeadersCannotHideOperatorsWithoutAVPrefix() {
        for (String header : List.of("|----x:UNKNOWN_OPERATOR", "x:OLAP_SCAN", "x:TABLE_FUNCTION",
                "|----x:HASH JOIN", "x1:UNKNOWN_OPERATOR", "bad node:OLAP_SCAN", "|----x:UNKNOWN_OPERATOR(12)",
                ":OLAP_SCAN", "|----:UNKNOWN_OPERATOR", "functions_unknown:row_number", "PARTITION_EXTRA:UNPARTITIONED")) {
            for (String indent : List.of("", "  "))
                assertEquals(-1, DorisQueryExecutor.parseEstimatedRows(List.of(
                        indent + header, "  0:VEMPTYSET(1)")), indent + header);
        }
    }

    @Test void actualExplainAttributeLabelsAreNotMisclassifiedAsUnknownNodeHeaders() {
        assertEquals(0, DorisQueryExecutor.parseEstimatedRows(List.of(
                "  OUTPUT EXPRS:", "  PARTITION: UNPARTITIONED", "  HAS_COLO_PLAN_NODE: false",
                "  |  functions: row_number", "  |  window: ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW",
                "  |  order by: bizdate[#6] DESC", "  |  algorithm: full sort", "  |  offset: 0", "  |  limit: 5",
                "  |  final projections: mktcode[#26], tgtcode[#27]", "  |  final project output tuple id: 10",
                "  |  intermediate projections: mktcode[#8], tgtcode[#9]", "  |  intermediate tuple id: 4",
                "  |  distribute expr lists: mktcode[#13], tgtcode[#14]", "  |  predicates: (r1[#22] <= 5)",
                "  |  has global limit: false", "  |  partition limit: 5", "  |  partition topn phase: TWO_PHASE_LOCAL_PTOPN",
                "    EXCHANGE ID: 02", "    HASH_PARTITIONED: mktcode[#4], tgtcode[#5]", "IS_MERGE: true",
                "  1:VPartitionTopN(2)", "  0:VEMPTYSET(1)")));
    }
}
