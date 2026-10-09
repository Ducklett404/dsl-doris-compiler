package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;
import java.time.LocalDate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

final class ProjectAvailabilityDiagnosticsTest {
    final StockSlotRegistry registry = new StockSlotRegistryLoader().loadDefault();
    final StockSlotSqlCompiler compiler = new StockSlotSqlCompiler(registry);
    String indicator(String name, String count) { return "indicator('', '', '" + name + "', '2026-04-14', '', '', '" + count + "')"; }
    String position(int n) { return "position('', '', '收盘价', '" + n + "日', '2026-04-14', '', '', '')"; }
    StockSlotCoveragePlan plan(String dsl) { return compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).coveragePlan(); }
    List<String> sample(StockSlotCoveragePlan p, String role) {
        var s = new ArrayList<>(List.of("1", "000001", "0"));
        for (var input : p.inputs()) s.add(input.role().equals(role) ? "1" : "0");
        return s;
    }
    List<StockSlotAvailabilityDiagnostics.SampleDetail> explain(StockSlotCoveragePlan p, String role, String... prices) {
        var s = sample(p, role); var fetch = StockSlotAvailabilityDiagnostics.fetchPlan(p, registry, List.of(s));
        var rows = new ArrayList<List<String>>();
        for (int i = 0; i < prices.length; i++) {
            var row = new ArrayList<>(List.of("1", "000001", LocalDate.of(2026, 4, 14).minusDays((prices.length-i-1)*41L).toString(), "1"));
            for (var field : fetch.fields()) row.add(prices[i]);
            rows.add(row);
        }
        return StockSlotAvailabilityDiagnostics.explain(p, registry, List.of(s), fetch, rows);
    }
    List<StockSlotAvailabilityDiagnostics.Reason> reasons(List<StockSlotAvailabilityDiagnostics.SampleDetail> details) {
        return details.getFirst().inputs().stream().flatMap(i -> i.reasons().stream()).toList();
    }
    List<StockSlotAvailabilityDiagnostics.SampleDetail> operandDetails(String dsl, Map<String,String> values) {
        var p=plan(dsl); var s=sample(p,"VALUE"); var fetch=StockSlotAvailabilityDiagnostics.fetchPlan(p,registry,List.of(s));
        var row=new ArrayList<>(List.of("1","000001","2026-04-14","1"));
        fetch.fields().forEach(f -> row.add(values.getOrDefault(f.field(),"1")));
        return StockSlotAvailabilityDiagnostics.explain(p,registry,List.of(s),fetch,List.of(row));
    }
    @Test void derivedZeroDenominatorsNameTheActualRawOperand() {
        for (var item:Map.of("均价",List.of("avgPx","volume"),"涨跌幅",List.of("risePct","preClosePx")).entrySet()) {
            var cause=reasons(operandDetails(indicator(item.getKey(),"")+">0",Map.of(item.getValue().get(0),"NULL",item.getValue().get(1),"0"))).getFirst();
            assertEquals("ZERO_DENOMINATOR",cause.code()); assertEquals(item.getKey()+" / "+item.getValue().get(1),cause.indicator());
            assertEquals(List.of("2026-04-14"),cause.relatedDates());
        }
    }
    @Test void everyDerivedOperandNullIsRetainedIncludingAdjustmentFactors() {
        var recipes=Map.of("总市值",List.of("marketValue","lastPx","totalShare"),
            "流通市值",List.of("listedMarketValue","lastPx","listedShare"),
            "前复权收盘价",List.of("closeQfq","closePx","qfqMulti","qfqAdd"),
            "后复权收盘价",List.of("closeHfq","closePx","hfqMulti","hfqAdd"));
        for (var entry:recipes.entrySet()) {
            var values=new HashMap<String,String>();entry.getValue().forEach(k->values.put(k,"NULL"));
            var causes=reasons(operandDetails(indicator(entry.getKey(),"")+">0",values));
            assertEquals(entry.getValue().size()-1,causes.size());
            assertTrue(causes.stream().allMatch(r->r.code().equals("SOURCE_OPERAND_NULL")));
        }
    }
    @Test void zeroDenominatorAndNullNumeratorBothRemainVisible() {
        var causes=reasons(operandDetails(indicator("均价","")+">0",Map.of("avgPx","NULL","turnover","NULL","volume","0")));
        assertEquals(Set.of("SOURCE_OPERAND_NULL","ZERO_DENOMINATOR"),causes.stream().map(StockSlotAvailabilityDiagnostics.Reason::code).collect(java.util.stream.Collectors.toSet()));
    }
    @Test void derivedNullWithoutRawEvidenceIsExplicitlyPartial() {
        var detail=operandDetails(indicator("均价","")+">0",Map.of("avgPx","NULL")).getFirst().inputs().getFirst();
        assertEquals("PARTIAL_DETAIL",detail.status()); assertEquals("UNCLASSIFIED_SQL_NULL",detail.reasons().getFirst().code());
    }
    @Test void derivedPositionFetchesRawOperandsAndKeepsLimits() {
        var p=plan("position('', '', '均价', '3日', '2026-04-14', '', '', '')='高'");
        var fetch=StockSlotAvailabilityDiagnostics.fetchPlan(p,registry,List.of(sample(p,"VALUE")));
        assertEquals(Set.of("avgPxPosition","turnover","volume"),fetch.fields().stream().map(StockSlotAvailabilityDiagnostics.Field::field).collect(java.util.stream.Collectors.toSet()));
        assertEquals(4,fetch.maxRows());assertEquals(3,fetch.historyRows());
    }
    @Test void positionExplanationMatchesDeclaredDecimalRoundingForFallbackFields() {
        var p=plan("position('', '', '前复权收盘价', '3日', '2026-04-14', '', '', '')='高'");
        assertEquals("FLAT_WINDOW",reasons(explain(p,"VALUE","1.0000000000001","1.0000000000002","1.0000000000003")).getFirst().code());
    }

    @Test void identitiesSurviveUnrelatedCallOrderWhitespaceAndLimitButDistinguishPeriods() {
        var a = plan(position(3) + "='高' AND " + position(20) + "='低' limit 0,2");
        var b = plan("  " + position(20) + " = '低' AND\n" + position(3) + " = '高' limit 0,5");
        assertEquals(a.inputs().stream().map(StockSlotCoveragePlan.Input::inputId).collect(java.util.stream.Collectors.toSet()),
                b.inputs().stream().map(StockSlotCoveragePlan.Input::inputId).collect(java.util.stream.Collectors.toSet()));
        assertEquals(2, a.inputs().stream().map(StockSlotCoveragePlan.Input::inputId).distinct().count());
        assertEquals(Set.of(3,20), a.inputs().stream().map(StockSlotCoveragePlan.Input::requiredObservations).collect(java.util.stream.Collectors.toSet()));
    }
    @Test void countIdentitiesIncludePredicateAndDiagnosticRole() {
        var a = plan(indicator("收盘价", "CONS>=3日") + ">1");
        var b = plan(indicator("收盘价", "CONS>=3日") + ">2");
        assertTrue(a.inputs().stream().filter(i -> i.role().startsWith("COUNT")).noneMatch(i -> b.inputs().stream().anyMatch(j -> j.inputId().equals(i.inputId()))));
        assertEquals(3, a.inputs().stream().map(StockSlotCoveragePlan.Input::inputId).distinct().count());
    }
    @Test void priceNullIsDatedByActualSparseObservation() {
        var details = explain(plan(indicator("3日均线", "") + ">0"), "VALUE", "3", "NULL", "2");
        var cause = reasons(details).getFirst();
        assertEquals("SOURCE_NULL", cause.code());
        assertEquals(List.of("2026-03-04"), cause.relatedDates());
        assertEquals("EXPLAINED", details.getFirst().inputs().getFirst().status());
    }
    @Test void insufficientHistoryDoesNotInventAbsentTradingDates() {
        var cause = reasons(explain(plan(position(3)+"='高'"), "VALUE", "1", "2")).getFirst();
        assertEquals("INSUFFICIENT_OBSERVATIONS", cause.code());
        assertEquals(3,cause.requiredObservations()); assertEquals(2,cause.minimumObserved());
        assertEquals(List.of("2026-04-14"),cause.relatedDates());
    }
    @Test void flatWindowContainsEvidenceDatesAndNoMissingValueClaim() {
        var cause = reasons(explain(plan(position(3)+"='高'"), "VALUE", "2", "2", "2")).getFirst();
        assertEquals("FLAT_WINDOW",cause.code()); assertEquals(3,cause.totalRelatedDates());
        assertEquals(3,cause.minimumObserved());
    }
    @Test void rsiUsesPredecessorAndZeroLossRemainsUnavailable() {
        var p = plan(indicator("RSI(2)", "")+">50");
        assertEquals(3,p.inputs().getFirst().requiredObservations());
        assertEquals("ZERO_LOSS_DENOMINATOR",reasons(explain(p,"VALUE","1","2","3")).getFirst().code());
        assertEquals("SOURCE_NULL",reasons(explain(p,"VALUE","NULL","2","1")).getFirst().code());
    }
    @Test void countInputEvaluatesEarlierIndicatorWindowsWhileCountResultOnlyNeedsObservations() {
        var p = plan(indicator("3日均线","CONS=2日")+">0");
        var count = p.inputs().stream().filter(i -> i.role().equals("COUNT_INPUT")).findFirst().orElseThrow();
        assertEquals(5,count.requiredObservations());
        var issues = reasons(explain(p,"COUNT_INPUT","NULL","3","1","2","1"));
        assertTrue(issues.stream().anyMatch(r -> r.code().equals("UNKNOWN_PREDICATE") && r.relatedDates().equals(List.of("2026-01-22"))));
        assertTrue(issues.stream().anyMatch(r -> r.code().equals("SOURCE_NULL") && r.relatedDates().equals(List.of("2025-11-01"))));
        assertEquals("UNCLASSIFIED_SQL_NULL",reasons(explain(p,"COUNT_RESULT","NULL","3","1","2","1")).getFirst().code());
    }
    @Test void datesAreCappedButTotalIsPreserved() {
        var p = plan(indicator("收盘价","EXIST>=25日")+">0");
        String[] values = new String[25]; Arrays.fill(values,"NULL");
        var cause = reasons(explain(p,"COUNT_INPUT",values)).stream().filter(r -> r.code().equals("SOURCE_NULL")).findFirst().orElseThrow();
        assertEquals(25,cause.totalRelatedDates()); assertEquals(20,cause.relatedDates().size()); assertTrue(cause.datesTruncated());
    }
    @Test void sentinelAndMissingExtensionRemainSeparateReasons() {
        var p = plan(indicator("主力净流入","")+">0");
        assertEquals("SENTINEL_VALUE",reasons(explain(p,"VALUE","-999999")).getFirst().code());
        var s = sample(p,"VALUE"); var fetch = StockSlotAvailabilityDiagnostics.fetchPlan(p,registry,List.of(s));
        var details = StockSlotAvailabilityDiagnostics.explain(p,registry,List.of(s),fetch,List.of(List.of("1","000001","2026-04-14","0","NULL")));
        assertEquals("EXTENSION_ROW_MISSING",reasons(details).getFirst().code());
    }
    @Test void pairZeroDenominatorAndPreviousNullHaveDistinctEvidence() {
        var p = plan("close_together('', '', '收盘价', '开盘价', '2026-04-14', '', '')=true");
        assertEquals("ZERO_DENOMINATOR",reasons(explain(p,"VALUE","0")).getFirst().code());
        p=plan("cross_above('', '', '收盘价', '开盘价', '2026-04-14', '', '')=true");
        assertTrue(reasons(explain(p,"VALUE","NULL","2")).stream().allMatch(r -> r.code().equals("SOURCE_NULL") && r.relatedDates().equals(List.of("2026-03-04"))));
    }
    @Test void longHistoryClippingIsPartialAndUnboundedOldNullsAreNotMissingInputs() {
        var p=plan("position('', '', '收盘价', '历史', '2026-04-14', '', '', '')='高'");
        String[] prices = new String[10002]; Arrays.fill(prices,"2");
        var detail=explain(p,"VALUE",prices).getFirst();
        assertTrue(detail.historyTruncated()); assertEquals("PARTIAL_DETAIL",detail.inputs().getFirst().status());
        assertEquals("DETAIL_HISTORY_LIMIT",detail.inputs().getFirst().reasons().getFirst().code());
        assertEquals("UNCLASSIFIED_SQL_NULL",reasons(explain(p,"VALUE","NULL","1","2")).getFirst().code());
    }
    @Test void lookupBindsSecurityTextAndCapsTransferAndProjection() {
        var p=plan(position(5)+"='高'"); var sample=new ArrayList<>(sample(p,"VALUE")); sample.set(1,"x' OR 1=1 --");
        var fetch=StockSlotAvailabilityDiagnostics.fetchPlan(p,registry,List.of(sample));
        assertFalse(fetch.sql().contains(sample.get(1))); assertTrue(fetch.bindings().contains(sample.get(1)));
        assertEquals(6,fetch.maxRows()); assertEquals(fetch.bindings().size(),fetch.sql().chars().filter(c->c=='?').count());
        assertThrows(IllegalArgumentException.class,()->StockSlotAvailabilityDiagnostics.fetchPlan(p,registry,Collections.nCopies(21,sample)));
    }
    @Test void serializedInputsExcludeInternalExpressionAndContainStableMetadata() throws Exception {
        var p=plan(position(3)+"='高'"); var json=JsonSupport.MAPPER.valueToTree(p.inputs().getFirst());
        assertFalse(json.has("expression")); assertEquals(64,json.get("inputId").asText().length());
        assertEquals("3 条观察记录",json.get("window").asText());
    }
    @Test void anchoredAggregationReportsItsFullWindow() {
        var p=plan("indicator('', '', '收盘价', '2026-04-14近5日', '', 'AVG', '')>0");
        assertEquals(5,p.inputs().getFirst().requiredObservations());
        assertEquals("INSUFFICIENT_OBSERVATIONS",reasons(explain(p,"VALUE","1","2")).getFirst().code());
    }
    @Test void crossSecurityLookupIsExplicitlyPartial() {
        var p=plan("queryData('', '999999', '收盘价', '2026-04-14', 'MAX')>0");
        assertEquals("DETAIL_NOT_SUPPORTED",reasons(explain(p,"VALUE","1")).getFirst().code());
    }
    @Test void repeatedValueIdentitiesDoNotDependOnCountShapeOrOrder() {
        var a=plan(indicator("RSI(2)","CONS>=2日")+">1 AND "+indicator("RSI(2)","EXIST>=2日")+">2");
        var b=plan(indicator("RSI(2)","EXIST>=2日")+">2 AND "+indicator("RSI(2)","CONS>=2日")+">1");
        var av=a.inputs().stream().filter(i->i.role().equals("VALUE")).toList();
        var bv=b.inputs().stream().filter(i->i.role().equals("VALUE")).toList();
        // The same scalar RSI input is now diagnosed once, independent of the
        // two distinct count predicates; COUNT_INPUT/COUNT_RESULT remain separate.
        assertEquals(1,av.size()); assertEquals(1,bv.size());
        assertEquals(1,av.stream().map(StockSlotCoveragePlan.Input::inputId).distinct().count());
        assertEquals(av.getFirst().inputId(),bv.getFirst().inputId());
        for (var p : List.of(a,b)) {
            assertEquals(2,p.inputs().stream().filter(i->i.role().equals("COUNT_INPUT")).count());
            assertEquals(2,p.inputs().stream().filter(i->i.role().equals("COUNT_RESULT")).count());
            assertEquals(p.inputs().size(),p.inputs().stream().map(StockSlotCoveragePlan.Input::inputId).distinct().count());
        }
    }
    @Test void costlyNestedWindowsStopExplainingWithoutChangingCountFlags() {
        var p=plan(indicator("RSI(5000)","CONS=5000日")+">0");
        String[] prices=new String[10001]; Arrays.fill(prices,"2");
        var details=explain(p,"COUNT_INPUT",prices);
        assertEquals("PARTIAL_DETAIL",details.getFirst().inputs().getFirst().status());
        assertTrue(reasons(details).stream().anyMatch(r->r.code().equals("DETAIL_WORK_LIMIT")));
    }
    @Test void unboundedPositionRequiresCurrentPriceEvenWhenHistoricalExtremaExist() {
        var p=plan("position('', '', '收盘价', '历史', '2026-04-14', '', '', '')='中'");
        var causes=reasons(explain(p,"VALUE","1","2","NULL"));
        assertEquals(1,causes.size()); assertEquals("SOURCE_NULL",causes.getFirst().code());
        assertEquals(List.of("2026-04-14"),causes.getFirst().relatedDates());
        assertTrue(p.sql().contains(" IS NULL OR NOT ("));
    }
    @Test void integerAndSentinelPositionInputsDoNotRequireAPriceCompanion() {
        var p=plan("position('', '', '成交量', '3日', '2026-04-14', '', '', '')='高'");
        assertEquals("FLAT_WINDOW",reasons(explain(p,"VALUE","2","2","2")).getFirst().code());
        p=plan("position('', '', '主力净流入', '3日', '2026-04-14', '', '', '')='高'");
        assertEquals("SENTINEL_VALUE",reasons(explain(p,"VALUE","1","-999999","2")).getFirst().code());
    }
}
