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

    @Test void crossSectionAndUnboundedMixedInputsRetainFullHistory() {
        var compiler = new StockSlotSqlCompiler(registry);
        String rsi = "indicator('', '', 'RSI(5)', '2026-04-14', '', '', '') > 50";
        for (String suffix : List.of(" and record_high('', '', '收盘价', '历史', '2026-04-14', '', '', '')",
                " and queryData('', '600000', '收盘价', '2026-04-14', '')>1"))
            assertFalse(compiler.compile(rsi+suffix, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql().contains("observed_tail"));
    }
}
