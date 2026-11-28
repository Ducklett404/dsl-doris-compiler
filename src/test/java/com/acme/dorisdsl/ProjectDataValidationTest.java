package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

final class ProjectDataValidationTest {
    @TempDir Path directory;
    final StockSlotRegistry registry = new StockSlotRegistryLoader().loadDefault();

    private ProjectDataValidation.Certificate certificate(Map<String, ProjectDataValidation.Source> sources) {
        return new ProjectDataValidation.Certificate("project-data-validation-v1", "PROJECT_READY_WITH_LIMITATIONS", "source-v1", "1.0.0",
                "a".repeat(64), registry.fingerprint(), "PROJECT_INTERNAL", sources, 10, 2, List.of("Project assumptions; no official endorsement"));
    }
    private ProjectDataValidation load(ProjectDataValidation.Certificate data) throws Exception {
        Path path = directory.resolve("capabilities.json");
        Files.write(path, JsonSupport.MAPPER.writeValueAsBytes(data));
        return ProjectDataValidation.load(path, registry);
    }
    private ProjectDataValidation.Source source(String key, String status) {
        return new ProjectDataValidation.Source(registry.table(key).qualifiedName(), "VIEW", status, 20, "b".repeat(64));
    }

    @Test void basicQueriesDoNotRequireTheBlockedExtensionCapability() throws Exception {
        var validation = load(certificate(Map.of("basic", source("basic", "PROJECT_READY"), "extension", source("extension", "BLOCKED"))));
        var compiler = new StockSlotSqlCompiler(registry);
        assertEquals(Set.of("basic"), validation.requiredSources(compiler.compile("indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1")));
        assertThrows(DorisExecutionException.class, () -> validation.requiredSources(compiler.compile("indicator('', '', '主力净流入', '2026-04-14', '', '', '') > 0")));
    }

    @Test void sourceNameInjectionAndChangedRegistryAreRejectedBeforeJdbc() throws Exception {
        assertThrows(IllegalArgumentException.class, () -> load(certificate(Map.of("basic",
                new ProjectDataValidation.Source("newzl.quotes; DROP TABLE quotes", "VIEW", "PROJECT_READY", 1, "c".repeat(64))))));
        var valid = certificate(Map.of("basic", source("basic", "PROJECT_READY")));
        assertThrows(IllegalArgumentException.class, () -> load(new ProjectDataValidation.Certificate(valid.formatVersion(), valid.status(), valid.snapshotId(),
                valid.contractVersion(), valid.manifestSha256(), "f".repeat(64), valid.definitionAuthority(), valid.sources(), 0, 0, valid.limitations())));
    }

    @Test void projectSourcesAndLimitationsCannotBeMutatedAfterValidation() throws Exception {
        var validation = load(certificate(Map.of("basic", source("basic", "PROJECT_READY"))));
        assertThrows(UnsupportedOperationException.class, () -> validation.certificate().sources().clear());
        assertThrows(UnsupportedOperationException.class, () -> validation.certificate().limitations().clear());
    }

    @Test void unavailableIndustryIsRejectedEvenWhenBasicAndCodeSourcesAreReady() throws Exception {
        var validation = load(certificate(Map.of("basic", source("basic", "PROJECT_READY"), "code", source("code", "PROJECT_READY"))));
        var artifact = new StockSlotSqlCompiler(registry).compile("indicator('', '', '收盘价', '2026-04-14', '', '', '') > belong_industry('', '', '收盘价', '2026-04-14', 'AVG')");
        assertThrows(DorisExecutionException.class, () -> validation.requiredSources(artifact));
    }

    @Test void availabilityPreservesWindowBindingsAndUsesValuesBeforePredicateAndLimit() {
        var artifact = new StockSlotSqlCompiler(registry).compile("position('京', '', '收盘价', '5日', '2026-04-14', '', '', '') = '低' limit 0,2");
        var coverage = artifact.coveragePlan();
        assertNotNull(coverage);
        assertTrue(coverage.sql().contains("FROM current_rows cov"));
        assertTrue(coverage.sql().contains("cov.`f1` IS NULL"));
        assertFalse(coverage.sql().contains("LIMIT 2"));
        assertFalse(coverage.bindings().contains("低"));
        assertEquals(coverage.sql().chars().filter(c -> c == '?').count(), coverage.bindings().size());
        assertEquals(coverage.samplesSql().chars().filter(c -> c == '?').count(), coverage.bindings().size());
        assertEquals(coverage.combinedSql().chars().filter(c -> c == '?').count(), coverage.bindings().size());
        assertTrue(coverage.combinedSql().contains("sample_rank<=20"));
        assertTrue(coverage.combinedSql().contains("COUNT(*) OVER () AS observed"));
    }

    @Test void rankingAvailabilityUsesInputBeforeNullFilteringAndThen() {
        var artifact = new StockSlotSqlCompiler(registry).compile("indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1 then rank('', '', '收盘价', 'desc:row_number', '2026-04-14', '', '', '') <= 2");
        assertFalse(artifact.coveragePlan().sql().contains("rank_input AS"));
        assertFalse(artifact.coveragePlan().sql().contains("prefiltered AS"));
        assertTrue(artifact.coveragePlan().inputs().stream().anyMatch(i -> i.function().equals("rank")));
    }

    @Test void countAvailabilityIncludesUnknownHistoricalConditionsWithoutChangingCountResult() {
        var artifact = new StockSlotSqlCompiler(registry).compile("indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') > 1");
        assertTrue(artifact.coveragePlan().sql().contains("COUNT(`pc1`) OVER"));
        assertTrue(artifact.coveragePlan().inputs().stream().anyMatch(i -> i.function().equals("CONS（窗口输入）")));
        assertFalse(artifact.sql().contains("coverage_counted"));
        assertEquals(artifact.coveragePlan().sql().chars().filter(c -> c == '?').count(), artifact.coveragePlan().bindings().size());
    }

    @Test void projectFinitePositionKeepsActualObservationsAndFullReferenceRemainsUnpruned() {
        var compiler = new StockSlotSqlCompiler(registry);
        String finite = "position('', '', '收盘价', '5日', '2026-04-14', '', '', '') = '高'";
        var project = compiler.compile(finite, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        assertTrue(project.sql().contains("observation_rank<=5"));
        assertFalse(project.sql().contains("INTERVAL"));
        assertFalse(project.sql().contains("WHERE `v1` IS NOT NULL"));
        assertTrue(project.coveragePlan().sql().contains("observed_tail"));
        assertFalse(compiler.compile(finite, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).sql().contains("observed_tail"));
        assertFalse(compiler.compile(finite.replace("5日","历史"), StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql().contains("observed_tail"));
        assertTrue(compiler.compile(finite+" and indicator('', '', '3日均线', '2026-04-14', '', '', '')>1",
                StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql().contains("observation_rank<=5"));
    }

    @Test void oneObservationUsesOnlyEvaluationDateAndFiniteWindowsRestoreSparseHistories() {
        var compiler = new StockSlotSqlCompiler(registry);
        var mode = StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE;
        var rank = compiler.compile("indicator('', '', '主力净流入', '2026-04-14', '', '', '') > 0 then "
                + "rank('', '', '收盘价', 'desc:row_number', '2026-04-14', '', '', '') <= 10", mode);
        assertTrue(rank.sql().contains("WHERE b.bizdate = ?"));
        assertFalse(rank.sql().contains("history_ranked"));
        assertTrue(rank.coveragePlan().combinedSql().contains("WHERE b.bizdate = ?"));

        var ma = compiler.compile("indicator('', '', '20日均线', '2026-04-14', '', '', '') > 1", mode);
        assertTrue(ma.sql().contains("HAVING COUNT(*) < 20 AND MAX(bizdate) = ?"));
        assertTrue(ma.sql().contains("b.bizdate < ? AND EXISTS"));
        assertTrue(ma.sql().contains("k.mktcode=b.mktcode AND k.tgtcode=b.tgtcode"));
        assertTrue(ma.sql().contains("UNION ALL"));
    }

    @Test void projectRsiRetainsAnExtraPriceBeforeComputingDeltas() {
        var compiler = new StockSlotSqlCompiler(registry);
        String rsi = "indicator('', '', 'RSI(5)', '2026-04-14', '', '', '') > 50";
        var project = compiler.compile(rsi, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        assertTrue(project.sql().contains("observation_rank<=6"));
        assertTrue(project.sql().contains("FROM observed_tail\n),\nfeatures AS"));
        assertFalse(project.sql().contains("IS NOT NULL"));
        assertTrue(project.coveragePlan().sql().contains("observation_rank<=6"));
        assertFalse(compiler.compile(rsi, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).sql().contains("observed_tail"));
        var two = compiler.compile(rsi+" or indicator('', '', 'RSI(20)', '2026-04-14', '', '', '') > 50",
                StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        assertTrue(two.sql().contains("observation_rank<=21"));
    }

    @Test void projectRsiCountAndMixedWindowsRetainTheirDependencies() {
        var compiler = new StockSlotSqlCompiler(registry);
        String rsi = "indicator('', '', 'RSI(5)', '2026-04-14', '', '', '') > 50";
        assertTrue(compiler.compile(rsi.replace("'', '')", "'', 'CONS>=3日')"),
                StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql().contains("observation_rank<=8"));
        assertTrue(compiler.compile(rsi+" and indicator('', '', '20日均线', '2026-04-14', '', '', '') > 1",
                StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql().contains("observation_rank<=20"));
        assertTrue(compiler.compile(rsi.replace("'', '')", "'', 'EXIST=3日')"),
                StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql().contains("observation_rank<=25"));
    }

    @Test void countedComparisonRetainsHistoryForBothOperands() {
        var compiler = new StockSlotSqlCompiler(registry);
        String dsl = "indicator('', '', 'RSI(5)', '2026-04-14', '', '', 'CONS=3日') > indicator('', '', '20日均线', '2026-04-14', '', '', '')";
        assertTrue(compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql().contains("observation_rank<=23"));
        assertFalse(compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).sql().contains("observed_tail"));
    }

    @Test void unboundedWindowKeepsHistoryAndCountedLookupUsesDateSpecificTargets() {
        var compiler = new StockSlotSqlCompiler(registry);
        String rsi = "indicator('', '', 'RSI(5)', '2026-04-14', '', '', '')";
        String lookup = "queryData('', '600000', '收盘价', '2026-04-14', '')";
        var unbounded = compiler.compile(rsi+" > 50 and record_high('', '', '收盘价', '历史', '2026-04-14', '', '', '')",
                StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        assertFalse(unbounded.sql().contains("observed_tail"));
        String dsl = rsi.replace("'', '')", "'', 'EXIST>=3日')") + " > " + lookup;
        var plan = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        assertTrue(plan.sql().contains("observation_rank<=25"));
        assertTrue(plan.sql().contains("GROUP BY b.bizdate"));
        assertTrue(plan.sql().contains("LEFT JOIN lookup_series ON lookup_series.lookup_date="));
        assertFalse(plan.sql().contains("lookup_names"));
        assertFalse(compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).sql().contains("lookup_series"));
    }

    @Test void currentLookupsUseWholeDayAfterHistoricalCountsAndBeforeRanking() {
        String dsl = "indicator('沪', '', '5日均线', '2026-04-14', '', '', 'EXIST>=6日') > 10 and "
                + "queryData('沪', '浦发银行', '收盘价', '2026-04-14', 'AVG') >= "
                + "queryData('沪', '600000', '收盘价', '2026-04-14', '') then "
                + "rank('沪', '', '收盘价', 'asc:dense_rank', '2026-04-14', '', '', '') <= 12";
        var compiler = new StockSlotSqlCompiler(registry);
        var plan = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        var reference = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
        assertTrue(plan.sql().contains("observation_rank<=24"));
        assertTrue(plan.sql().contains("FROM counted WHERE bizdate = ?"));
        assertTrue(plan.sql().indexOf("lookup_names AS") < plan.sql().indexOf("prefiltered AS"));
        assertFalse(reference.sql().contains("lookup_names AS"));
        assertEquals(reference.windowContracts(), plan.windowContracts());
        assertEquals(reference.coveragePlan().inputs(), plan.coveragePlan().inputs());
        assertEquals(List.of("2026-04-14","2026-02-01","2026-04-14","2026-02-01","10","2026-04-14","浦发银行","浦发银行","600000","600000","12"),
                plan.bindings().stream().map(Object::toString).toList());
        var coverage = plan.coveragePlan();
        assertTrue(coverage.combinedSql().contains("FROM coverage_counted WHERE bizdate = ?"));
        assertEquals(coverage.bindings().size(), coverage.combinedSql().chars().filter(c -> c=='?').count());
    }
}
