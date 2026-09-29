package com.acme.dorisdsl.competition;

import com.acme.dorisdsl.compiler.CompileException;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class SlotSafeSqlCompilerTest {
    private final VerifiedIndicatorCatalog catalog = new VerifiedIndicatorCatalog(List.of(
            new VerifiedIndicatorCatalog.Metric("测试价", List.of("测试现价"),
                    VerifiedIndicatorCatalog.Column.LAST_PX,
                    VerifiedIndicatorCatalog.Unit.NUMBER, new BigDecimal("100"), "Synthetic test fixture"),
            new VerifiedIndicatorCatalog.Metric("测试率", List.of(),
                    VerifiedIndicatorCatalog.Column.TURN_RATIO,
                    VerifiedIndicatorCatalog.Unit.PERCENT, new BigDecimal("100"), "Synthetic test fixture")));
    private final SlotSafeSqlCompiler compiler = new SlotSafeSqlCompiler(catalog);

    @Test void emitsOnlyWhitelistedIdentifiersAndBoundRawThresholds() {
        var artifact = compiler.compile("""
                indicator('', '', '测试现价', '2026-09-18', '', '', '') > 10.25
                and indicator('', '', '测试率', '2026-09-18', '', '', '') <= 5%
                """);
        assertEquals(LocalDate.of(2026, 9, 18), artifact.typedQuery().asOf());
        assertEquals(List.of(LocalDate.of(2026, 9, 18), 1025L, 500L), artifact.bindings());
        assertTrue(artifact.sql().contains("FROM `newzl`.`hsj_stock_hq_basic` AS q"));
        assertTrue(artifact.sql().contains("q.`lastPx` > ? AND q.`turnRatio` <= ?"));
        assertTrue(artifact.sql().contains("ORDER BY q.`mktcode`, q.`tgtcode`"));
        assertFalse(artifact.sql().contains("测试现价"));
        assertFalse(artifact.sql().contains("1025"));
    }

    @Test void referenceFixtureKeepsMarketCodeAndDateDistinct() {
        var artifact = compiler.compile("indicator('', '', '测试价', '2026-09-18', '', '', '') > 10");
        var rows = List.of(
                row(0, "000001", "2026-09-18", 1001L),
                row(1, "000001", "2026-09-18", 1100L),
                row(0, "000002", "2026-09-18", 1000L),
                row(0, "000003", "2026-09-17", 1200L));
        assertEquals(List.of(
                new SlotSafeReferenceEvaluator.SecurityKey(0, "000001"),
                new SlotSafeReferenceEvaluator.SecurityKey(1, "000001")),
                new SlotSafeReferenceEvaluator().select(artifact.typedQuery(), rows));
    }

    @Test void handlesNegativeThresholdAndOrWithoutDroppingNullRowsIntoResults() {
        var artifact = compiler.compile("""
                indicator('', '', '测试价', '2026-09-18', '', '', '') > -1
                or indicator('', '', '测试率', '2026-09-18', '', '', '') < 2%
                """);
        assertEquals(List.of(LocalDate.of(2026, 9, 18), -100L, 200L), artifact.bindings());
        var rows = List.of(
                new SlotSafeReferenceEvaluator.QuoteRow(0, "A", LocalDate.parse("2026-09-18"),
                        Map.of(VerifiedIndicatorCatalog.Column.LAST_PX, 0L)),
                new SlotSafeReferenceEvaluator.QuoteRow(0, "B", LocalDate.parse("2026-09-18"),
                        Map.of(VerifiedIndicatorCatalog.Column.TURN_RATIO, 100L)),
                new SlotSafeReferenceEvaluator.QuoteRow(0, "C", LocalDate.parse("2026-09-18"),
                        Map.of(VerifiedIndicatorCatalog.Column.LAST_PX, -200L,
                                VerifiedIndicatorCatalog.Column.TURN_RATIO, 300L)));
        assertEquals(List.of(new SlotSafeReferenceEvaluator.SecurityKey(0, "A"),
                        new SlotSafeReferenceEvaluator.SecurityKey(0, "B")),
                new SlotSafeReferenceEvaluator().select(artifact.typedQuery(), rows));
    }

    @Test void rejectsUnknownOrUnverifiedBusinessSemantics() {
        assertCode("DSL_INDICATOR_UNVERIFIED", "indicator('', '', '最新价', '2026-09-18', '', '', '') > 10");
        assertCode("DSL_DATE_UNRESOLVED", "indicator('', '', '测试价', '今天', '', '', '') > 10");
        assertCode("DSL_SCOPE_UNRESOLVED", "indicator('沪', '', '测试价', '2026-09-18', '', '', '') > 10");
        assertCode("DSL_SCOPE_UNRESOLVED", "indicator('', '银行', '测试价', '2026-09-18', '', '', '') > 10");
        assertCode("DSL_APPROX_UNRESOLVED", "indicator('', '', '测试价', '2026-09-18', '', '', '') ~= 10");
        assertCode("DSL_LIMIT_UNRESOLVED", "indicator('', '', '测试价', '2026-09-18', '', '', '') > 10 limit 0,-1");
        assertCode("DSL_UNIT_MISMATCH", "indicator('', '', '测试率', '2026-09-18', '', '', '') > 5");
        assertCode("DSL_SCALE_INEXACT", "indicator('', '', '测试价', '2026-09-18', '', '', '') > 10.005");
        assertCode("DSL_RAW_RANGE", "indicator('', '', '测试率', '2026-09-18', '', '', '') > 21474837%");
    }

    @Test void rejectsRankMixedDatesAndUnsafeArithmetic() {
        String price = "indicator('', '', '测试价', '2026-09-18', '', '', '')";
        assertCode("DSL_RANK_UNRESOLVED", price + " > 10 then rank('', '', '测试价', 'desc', '2026-09-18', '', '', '') <= 5");
        assertCode("DSL_MIXED_DATES", price + " > 10 and indicator('', '', '测试率', '2026-09-17', '', '', '') < 5%");
        assertCode("DSL_SAFE_SUBSET", price + " > 2 * 5");
        assertCode("DSL_SAFE_SUBSET", "rank('', '', '测试价', 'desc', '2026-09-18', '', '', '') <= 5");
    }

    @Test void catalogIsExplicitlyReviewedAndAliasesCannotInjectSql() throws Exception {
        Path draft = Path.of("examples/competition_verified_catalog.template.json");
        assertThrows(IllegalArgumentException.class, () -> VerifiedIndicatorCatalog.load(draft));
        Path fixture = Path.of(getClass().getResource("/verified-slot-catalog.synthetic.json").toURI());
        var loaded = VerifiedIndicatorCatalog.load(fixture);
        var sql = new SlotSafeSqlCompiler(loaded)
                .compile("indicator('', '', '测试现价', '2026-09-18', '', '', '') > 10").sql();
        assertTrue(sql.contains("q.`lastPx` > ?"));
        assertFalse(sql.contains("测试现价"));
        var injectedAliasCatalog = new VerifiedIndicatorCatalog(List.of(
                new VerifiedIndicatorCatalog.Metric("safe", List.of("x` OR 1=1 --"),
                        VerifiedIndicatorCatalog.Column.LAST_PX, VerifiedIndicatorCatalog.Unit.NUMBER,
                        BigDecimal.ONE, "Synthetic test fixture")));
        var injectedAliasSql = new SlotSafeSqlCompiler(injectedAliasCatalog)
                .compile("indicator('', '', 'x` OR 1=1 --', '2026-09-18', '', '', '') > 0").sql();
        assertFalse(injectedAliasSql.contains("OR 1=1"));
        assertThrows(IllegalArgumentException.class, () -> new VerifiedIndicatorCatalog(List.of(
                new VerifiedIndicatorCatalog.Metric("X", List.of("X"),
                        VerifiedIndicatorCatalog.Column.VOLUME, VerifiedIndicatorCatalog.Unit.NUMBER,
                        BigDecimal.ONE, "Synthetic test fixture"))));
    }

    private void assertCode(String code, String dsl) {
        assertEquals(code, assertThrows(CompileException.class, () -> compiler.compile(dsl)).code());
    }

    private static SlotSafeReferenceEvaluator.QuoteRow row(int market, String code, String date, long price) {
        return new SlotSafeReferenceEvaluator.QuoteRow(market, code, LocalDate.parse(date),
                Map.of(VerifiedIndicatorCatalog.Column.LAST_PX, price));
    }
}
