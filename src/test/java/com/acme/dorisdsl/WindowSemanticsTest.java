package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.plan.WindowSpec;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class WindowSemanticsTest {
    private DslCompiler compiler;

    @BeforeEach void setUp() {
        compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    }

    @Test void emitsWindowSpecsForMaAndLagWithNullPolicies() {
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
                LIMIT 10
                """);

        assertEquals(4, artifact.windowSpecs().size());
        assertTrue(artifact.windowSpecs().stream().anyMatch(spec ->
                spec.alias().equals("ma_close_5")
                        && spec.length() == 5
                        && spec.unit() == WindowSpec.Unit.TRADING_DAY
                        && spec.partitionKeys().equals(List.of("symbol"))
                        && spec.orderKeys().equals(List.of("trade_date"))
                        && spec.nullPolicy() == WindowSpec.NullPolicy.STRICT_FULL_WINDOW
                        && spec.requireFullWindow()));
        assertTrue(artifact.windowSpecs().stream().anyMatch(spec ->
                spec.alias().equals("prev_ma_close_5")
                        && spec.function().equals("LAG")
                        && spec.nullPolicy() == WindowSpec.NullPolicy.ALLOW_PARTIAL_WINDOW));
        assertEquals(21, artifact.requiredLookbackTradingDays());
    }

    @Test void baseCteExpandsTradingDayRangeBeforeFinalTargetDateFilter() {
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
                LIMIT 10
                """);
        String sql = artifact.sql();

        int baseRange = sql.indexOf("WHERE q.trade_date BETWEEN");
        int metrics = sql.indexOf("metrics AS");
        int signals = sql.indexOf("signals AS");
        int finalFilter = sql.indexOf("WHERE trade_date = ?");
        int crossPredicate = sql.indexOf("AND (`ma_close_5` > `ma_close_20`");

        assertTrue(baseRange > 0, "base CTE must expand scan range");
        assertTrue(baseRange < metrics, "range expansion must happen before metric windows");
        assertTrue(metrics < signals, "MA windows must be computed before LAG signal windows");
        assertTrue(signals < finalFilter, "target-date filter must be in the final query");
        assertTrue(finalFilter < crossPredicate, "CROSS_UP predicate must run after target-date filter location");
        assertEquals(3, artifact.bindings().stream().filter(value -> value.toString().equals("2026-08-07")).count());
        assertFalse(sql.contains("2026-08-07"), "dates must stay parameterized, not literalized");
        assertFalse(sql.contains("WHERE q.trade_date = ?\n),\nmetrics"), "base CTE must not filter to target date before windows");
    }

    @Test void noWindowQueryStillFiltersTargetDateInBaseOnly() {
        var artifact = compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5");
        assertEquals(0, artifact.windowSpecs().size());
        assertEquals(0, artifact.requiredLookbackTradingDays());
        assertTrue(artifact.sql().contains("WHERE q.trade_date = ?"));
        assertFalse(artifact.sql().contains("metrics AS"));
        assertFalse(artifact.sql().contains("signals AS"));
    }

    @Test void fixtureDataDocumentsSuspensionIpoAndShortWindowCases() throws Exception {
        String calendar = Files.readString(fixture("trading_calendar.csv"));
        String quotes = Files.readString(fixture("quotes.csv"));

        assertTrue(calendar.contains("suspended_day_gap"));
        assertTrue(quotes.contains("target_date_after_suspension"));
        assertTrue(quotes.contains("listed_first_day_window_shortage"));
        assertFalse(quotes.contains("AAA,2026-08-05"), "suspended day should have no quote row");
    }

    private Path fixture(String name) throws URISyntaxException {
        return Path.of(getClass().getResource("/window-fixtures/" + name).toURI());
    }

}
