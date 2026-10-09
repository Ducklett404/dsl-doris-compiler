package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.*;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

final class ProjectCombinationRegressionTest {
    private static String indicator(String name, String count) {
        return "indicator('', '', '" + name + "', '2026-04-14', '', '', '" + count + "')";
    }

    @Test void repeatedMetricHasOneDiagnosticInputButDifferentWindowsStaySeparate() {
        String dsl = indicator("3日均线", "") + " > " + indicator("5日均线", "")
                + " and " + indicator("5日均线", "") + " > " + indicator("20日均线", "");
        var artifact = new StockSlotSqlCompiler().compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        var inputs = artifact.coveragePlan().inputs();
        assertEquals(3, inputs.size());
        assertEquals(3, inputs.stream().map(StockSlotCoveragePlan.Input::inputId).distinct().count());
        assertEquals(Set.of(3, 5, 20), new HashSet<>(inputs.stream().map(StockSlotCoveragePlan.Input::requiredObservations).toList()));
        assertTrue(artifact.sql().contains("f3"), "Main expression aliases are retained; only diagnosis deduplicates");
    }

    @Test void countResultAndUnknownInputAreDifferentDiagnosticRoles() {
        var artifact = new StockSlotSqlCompiler().compile(indicator("均价", "CONS=3日") + " > 0 and "
                + indicator("均价", "") + " > 0", StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        var inputs = artifact.coveragePlan().inputs();
        assertTrue(inputs.stream().anyMatch(i -> i.role().equals("COUNT_RESULT")));
        assertTrue(inputs.stream().anyMatch(i -> i.role().equals("COUNT_INPUT")));
        assertTrue(inputs.stream().anyMatch(i -> i.role().equals("VALUE")));
        assertEquals(inputs.size(), inputs.stream().map(StockSlotCoveragePlan.Input::inputId).distinct().count());
    }

    @Test void decimalPricesKeepExactRsiAccumulationAndFiftyBoundary() {
        var compiler = new StockSlotSqlCompiler();
        for (var mode : List.of(StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE,
                StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE)) {
            var artifact = compiler.compile("(" + indicator("均价", "") + " > 0 and "
                    + indicator("3日均线", "") + " > 1) or " + indicator("RSI(5)", "") + " > 50", mode);
            String sql = artifact.sql();
            assertTrue(sql.contains("`v2` - LAG(`v2`)"), "Subtract exact prices before conversion");
            assertTrue(sql.contains("SUM(GREATEST(price_delta,0)) OVER"));
            assertTrue(sql.contains("SUM(GREATEST(-price_delta,0)) OVER"));
            assertTrue(sql.contains("SUM(ABS(price_delta)) OVER"));
            assertTrue(sql.contains("AS DECIMAL(30,8)) / NULLIF(CAST("));
            assertTrue(sql.contains("AS DECIMAL(24,4)),0)"));
            assertFalse(sql.contains(" AS DOUBLE"));
            assertTrue(sql.contains("COUNT(price_delta) OVER"));
            assertTrue(sql.contains(") > 0 THEN CAST("), "Zero loss remains NULL");
            assertTrue(sql.contains(" OR (`f3` > ?)"), "Unknown left branch must not erase the RSI OR branch");
        }
    }

    @Test void movingAverageKeepsSubPriceScaleDifferencesInBothReferencePaths() {
        String dsl = indicator("3日均线", "") + " > " + indicator("5日均线", "")
                + " and " + indicator("5日均线", "") + " >= " + indicator("20日均线", "");
        for (var mode : List.of(StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE,
                StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE)) {
            var artifact = new StockSlotSqlCompiler().compile(dsl, mode);
            assertTrue(artifact.sql().contains("AVG(CAST(`v1` AS DECIMAL(38,18))) OVER"));
            assertFalse(artifact.sql().contains("AVG(`v1`) OVER"));
            assertFalse(artifact.sql().contains(" AS DOUBLE"), "Do not trade truncation for unstable float equality");
            assertTrue(artifact.sql().contains("COUNT(`v1`) OVER"), "Full non-null window remains mandatory");
            assertTrue(artifact.sql().contains("ROWS BETWEEN 19 PRECEDING AND CURRENT ROW"));
        }
    }

    @Test void movingAveragePrecisionDoesNotRewriteFieldAggregations() {
        var compiler = new StockSlotSqlCompiler();
        for (String fn : List.of("AVG", "MIN", "MAX", "SUM")) {
            String dsl = "indicator('', '', '收盘价', '2026-04-14近5日', '', '" + fn + "', '') > 0";
            if (fn.equals("SUM")) dsl = dsl.replace("收盘价", "成交量");
            var artifact = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
            assertTrue(artifact.sql().contains(fn + "(`v1`) OVER"));
            assertFalse(artifact.sql().contains(" AS DECIMAL(38,18)"));
        }
    }

    @Test void deferredExtensionUsesExactObservedKeysAndOnlyRegisteredProjection() {
        String dsl = "((" + indicator("均价", "") + " > 1) or (" + indicator("主力净流入", "")
                + " < 0)) and ((" + indicator("20日均线", "") + " > 1) or (" + indicator("RSI(5)", "") + " > 50))";
        var compiler = new StockSlotSqlCompiler();
        var project = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        var reference = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
        var extension = new StockSlotRegistryLoader().loadDefault().table("extension");
        String projection = String.join(",", extension.fields().values().stream().distinct().sorted()
                .map(field -> extension.alias() + "." + field).toList());
        String sql = project.sql();
        assertTrue(sql.contains("extension_tail AS (\n  SELECT " + projection + "\n  FROM "
                + extension.qualifiedName() + " " + extension.alias()));
        assertTrue(sql.contains("WHERE EXISTS (SELECT 1 FROM observed_tail extension_keys WHERE "
                + "e.mktcode=extension_keys.mktcode AND e.tgtcode=extension_keys.tgtcode AND e.bizdate=extension_keys.bizdate)"));
        assertTrue(sql.contains("FROM observed_tail LEFT JOIN extension_tail e ON "
                + "e.mktcode=observed_tail.mktcode AND e.tgtcode=observed_tail.tgtcode AND e.bizdate=observed_tail.bizdate\n)"));
        assertFalse(sql.contains("SELECT e.*"));
        assertFalse(sql.contains("INTERVAL"));
        assertFalse(sql.contains("WHERE e.ZJLXMainNetTur"));
        assertTrue(sql.contains("NULLIF(e.ZJLXMainNetTur,-999999) AS `v2`"));
        assertTrue(sql.contains("observation_rank<=20"));
        assertTrue(sql.contains("(`f1` > ?) OR (`f2` < ?)"), "NULL extension must retain the basic-price OR branch");
        assertTrue(project.coveragePlan().sql().contains("extension_tail AS"));
        assertTrue(project.coveragePlan().combinedSql().contains("extension_tail AS"));
        assertTrue(project.logicalPlan().stream().anyMatch(n -> n.kind().equals("SemiJoin")
                && n.detail().contains("exact observed tail")));
        assertTrue(project.logicalPlan().stream().anyMatch(n -> n.kind().equals("LeftJoin")));
        assertFalse(reference.sql().contains("extension_tail AS"));
        assertFalse(reference.sql().contains("observed_tail AS"));
        assertTrue(reference.sql().contains("LEFT JOIN " + extension.qualifiedName() + " e ON"));
        assertEquals(reference.bindings(), project.bindings(), "Semijoin adds no user values or placeholders");
        assertEquals(List.of(LocalDate.of(2026, 4, 14), LocalDate.of(2026, 4, 14),
                BigDecimal.ONE, BigDecimal.ZERO, BigDecimal.ONE, new BigDecimal("50")), project.bindings());
        assertEquals(reference.dslVersion(), project.dslVersion());
        assertEquals(reference.semanticModel(), project.semanticModel());
        assertEquals(reference.windowContracts(), project.windowContracts());
        assertEquals(reference.coveragePlan().inputs(), project.coveragePlan().inputs());
        assertEquals(project.sql(), compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE).sql());
    }

    @Test void deferredExtensionRetainsHistoricalFundsForWindowsAndOccurrences() {
        for (String dsl : List.of(
                "position('', '', '主力净流入', '3日', '2026-04-14', '', '', '') = '高'",
                indicator("主力净流入", "CONS>=3日") + " > 0")) {
            var compiler = new StockSlotSqlCompiler();
            var project = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
            var reference = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
            String sql = project.sql();
            assertTrue(sql.contains("observation_rank<=3"));
            assertTrue(sql.indexOf("extension_tail AS") < sql.indexOf("features AS"));
            assertTrue(sql.contains("e.bizdate=extension_keys.bizdate"));
            assertFalse(sql.contains("WHERE e.bizdate = ?"), "Historical extension rows cannot be restricted to evaluation date");
            assertFalse(sql.contains("WHERE `v1` IS NOT NULL"), "Missing observations must not shrink a strict window");
            assertTrue(sql.contains("NULLIF(e.ZJLXMainNetTur,-999999) AS `v1`"));
            assertEquals(reference.bindings(), project.bindings());
            assertEquals(reference.windowContracts(), project.windowContracts());
            assertFalse(reference.sql().contains("extension_tail AS"));
        }
    }

    @Test void exactKeySemijoinPreservesLeftBagNullsSentinelsAndExtensionDuplicates() {
        var date = LocalDate.of(2026, 4, 14);
        var historical = LocalDate.of(2026, 3, 2); // Suspension gap is not a calendar cutoff.
        var present = new TailKey("0", "000001", date);
        var sourceNull = new TailKey("0", "000002", date);
        var sentinel = new TailKey("0", "000003", date);
        var absent = new TailKey("0", "000004", date);
        var old = new TailKey("0", "000001", historical);
        List<TailKey> tail = List.of(present, sourceNull, sentinel, absent, old, present);
        List<ExtensionFixture> extension = List.of(
                new ExtensionFixture(present, 10L), new ExtensionFixture(present, 20L),
                new ExtensionFixture(sourceNull, null), new ExtensionFixture(sentinel, -999999L),
                new ExtensionFixture(old, -5L),
                new ExtensionFixture(new TailKey("1", "000001", date), 99L),
                new ExtensionFixture(new TailKey("0", "000001", date.plusDays(1)), 98L),
                new ExtensionFixture(new TailKey("0", "999999", date), 97L));
        List<ExtensionFixture> selected = extension.stream().filter(e -> tail.contains(e.key())).toList();
        assertEquals(5, selected.size(), "Wrong market/date and orphan extensions are excluded without deduplicating matches");
        List<EnrichedFixture> direct = fixtureLeftJoin(tail, extension);
        List<EnrichedFixture> restricted = fixtureLeftJoin(tail, selected);
        assertEquals(direct, restricted, "EXISTS restriction preserves the original left-join bag");
        assertEquals(8, restricted.size());
        assertEquals(3, restricted.stream().filter(e -> e.net() == null).count(), "Source NULL, sentinel and absent extension all survive");
        assertTrue(restricted.contains(new EnrichedFixture(old, -5L)), "Retained historical observation keeps its matching funds");
        assertEquals(4, restricted.stream().filter(e -> e.key().equals(present)).count(), "Neither tail nor extension duplicates are deduplicated");
        assertTrue(restricted.stream().noneMatch(e -> e.net() != null && e.net() >= 97));
    }

    private record TailKey(String market, String security, LocalDate date) {}
    private record ExtensionFixture(TailKey key, Long net) {}
    private record EnrichedFixture(TailKey key, Long net) {}

    // Independent relational fixture; real compiled SQL is additionally checked by the native/raw oracle matrix.
    private static List<EnrichedFixture> fixtureLeftJoin(List<TailKey> tail, List<ExtensionFixture> extension) {
        var result = new ArrayList<EnrichedFixture>();
        for (var key : tail) {
            var matches = extension.stream().filter(e -> e.key().equals(key)).toList();
            if (matches.isEmpty()) result.add(new EnrichedFixture(key, null));
            else for (var e : matches)
                result.add(new EnrichedFixture(key, Objects.equals(e.net(), -999999L) ? null : e.net()));
        }
        return result;
    }

    @Test void markdownDisclosesIndependentDiagnosticTimesWithoutAddingThemTwice() {
        var compilation = new StockSlotSqlCompiler().compile(indicator("均价", "") + " > 1");
        var quality = new DorisExecutionArtifact.DataQuality("PROJECT_SCOPED", false, "a".repeat(64),
                "COMPLETE_QUERY_INPUTS", "2026-04-14", List.of("basic"), 1, 0, List.of(), List.of(),
                0, 0, List.of("Project definitions"), 15, List.of(),
                new DorisExecutionArtifact.DiagnosticTimings(1, 2, 3, 4, 5));
        var artifact = new DorisExecutionArtifact(compilation, List.of("mktcode", "tgtcode"),
                List.of(List.of("0", "000001")), false, new DorisExecutionArtifact.Timings(1, 0, 2, 3, 1, 20),
                new DorisExecutionArtifact.Limits(10, 100000000, 1, 10000, 2147483648L), "sha256:abc",
                new DorisExecutionArtifact.SnapshotVersion("snapshot", "1", "hash"), "1",
                List.of(), new DorisExecutionArtifact.QueryProfileSummary(false, null, null, null, null, "NOT_RUN"), quality);
        String markdown = DorisExecutionMarkdownRenderer.render(artifact);
        assertTrue(markdown.contains("| 缺值统计及样本标记 | 4.000 |"));
        assertTrue(markdown.contains("| 样本历史读取与解释 | 5.000 |"));
        assertTrue(markdown.contains("| 总耗时 | 20.000 |"));
        assertTrue(markdown.contains("不重复相加"));
    }
}
