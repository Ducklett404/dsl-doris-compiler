package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompilationArtifact;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryConfig;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.ArrayList;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

class StandardIndicatorPackTest {
    private static final Set<String> STANDARD_FIELDS = Set.of(
            "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "AMOUNT", "TURNOVER_RATE"
    );
    private static final Set<String> STANDARD_FUNCTIONS = Set.of(
            "MA", "EMA", "CROSS_UP", "CROSS_DOWN", "PE_TTM", "PB", "PS_TTM",
            "ROE_TTM", "ROA_TTM", "NET_PROFIT_YOY", "VOLATILITY", "STDDEV",
            "RETURN_N", "RSI", "RANK_BY", "PERCENTILE_RANK"
    );

    @Test void standardIndicatorsHaveMetadataSignaturesLoweringAndBoundaryTests() {
        var registry = new RegistryLoader().loadDefault(List.of());
        Map<String, RegistryConfig.FieldDefinition> fields = registry.fields();
        Map<String, RegistryConfig.FunctionDefinition> functions = registry.functions();

        STANDARD_FIELDS.forEach(name -> {
            var field = fields.get(name);
            assertNotNull(field, name + " field must exist");
            assertMetadata(name, field.version(), field.description(), field.signature(), field.boundaryTests());
            assertNotNull(field.sourceSql(), name + " must have SQL source lowering");
        });
        STANDARD_FUNCTIONS.forEach(name -> {
            var function = functions.get(name);
            assertNotNull(function, name + " function must exist");
            assertMetadata(name, function.version(), function.description(), function.signature(), function.boundaryTests());
            assertNotNull(function.loweringKind(), name + " must declare lowering kind");
            if (function.loweringKind() == RegistryConfig.LoweringKind.COLUMN
                    || function.loweringKind() == RegistryConfig.LoweringKind.TEMPLATE) {
                assertNotNull(function.sqlTemplate(), name + " must provide SQL template");
            }
        });
        assertTrue(STANDARD_FIELDS.size() + STANDARD_FUNCTIONS.size() >= 20);
        assertTrue(STANDARD_FIELDS.size() + STANDARD_FUNCTIONS.size() <= 30);
    }

    @Test void compilesFirstStandardIndicatorPackAndEmitsVersions() {
        var artifact = compiler().compile("""
                SCREEN ON 2026-08-07
                WHERE OPEN > 1
                  AND HIGH >= LOW
                  AND CLOSE > MA(CLOSE, 20)
                  AND CLOSE > MA(CLOSE, 26)
                  AND VOLUME > 0
                  AND AMOUNT > 1000000
                  AND TURNOVER_RATE > 1%
                  AND CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
                  AND CROSS_DOWN(MA(CLOSE, 10), MA(CLOSE, 30))
                  AND PE_TTM() > 0
                  AND PB() > 0
                  AND PS_TTM() > 0
                  AND ROE_TTM() >= 15%
                  AND ROA_TTM() > 5%
                  AND NET_PROFIT_YOY() > 0
                  AND VOLATILITY(CLOSE, 20) > 0
                  AND STDDEV(RETURN_N(CLOSE, 5), 20) > 0
                  AND RSI(CLOSE, 14) > 50
                  AND RANK_BY(TURNOVER_RATE) <= 100
                  AND PERCENTILE_RANK(TURNOVER_RATE) >= 0.8
                ORDER BY PERCENTILE_RANK(TURNOVER_RATE) DESC
                LIMIT 50
                """);

        assertTrue(artifact.sql().contains("STDDEV_SAMP("));
        assertTrue(artifact.sql().contains("DENSE_RANK() OVER (PARTITION BY trade_date"));
        assertTrue(artifact.sql().contains("PERCENT_RANK() OVER (PARTITION BY trade_date"));
        assertTrue(artifact.sql().contains("f.visible_from <= q.trade_date"));
        assertTrue(artifact.sql().contains("q.trade_date < f.visible_to"));
        assertTrue(artifact.requiredLookbackTradingDays() >= 31);

        Map<String, String> versions = artifact.indicatorVersions().stream()
                .collect(Collectors.toMap(CompilationArtifact.IndicatorVersion::name,
                        CompilationArtifact.IndicatorVersion::version, (left, right) -> left));
        STANDARD_FIELDS.forEach(name -> assertEquals("std@1.0.0", versions.get(name), name));
        STANDARD_FUNCTIONS.stream().filter(name -> !name.equals("EMA"))
                .forEach(name -> assertEquals("std@1.0.0", versions.get(name), name));
    }

    @Test void boundaryCasesRejectInvalidStandardIndicatorUsage() {
        assertEquals("WINDOW_LITERAL", assertThrows(CompileException.class,
                () -> compiler().compile("SCREEN ON 2026-08-07 WHERE MA(CLOSE, TURNOVER_RATE) > 1 LIMIT 5")).code());
        assertEquals("WINDOW_RANGE", assertThrows(CompileException.class,
                () -> compiler().compile("SCREEN ON 2026-08-07 WHERE VOLATILITY(CLOSE, 5001) > 1 LIMIT 5")).code());
        assertEquals("NUMERIC_TYPE", assertThrows(CompileException.class,
                () -> compiler().compile("SCREEN ON 2026-08-07 WHERE CROSS_UP(MARKET, CLOSE) LIMIT 5")).code());
        assertEquals("FUNCTION_ARITY", assertThrows(CompileException.class,
                () -> compiler().compile("SCREEN ON 2026-08-07 WHERE RANK_BY(CLOSE, OPEN) > 1 LIMIT 5")).code());
    }

    @Test void baseFieldCrossSignalsScanThePreviousTradingDay() {
        var crossUp = compiler().compile(
                "SCREEN ON 2026-08-07 WHERE CROSS_UP(CLOSE, OPEN) LIMIT 5");
        var crossDown = compiler().compile(
                "SCREEN ON 2026-08-07 WHERE CROSS_DOWN(CLOSE, OPEN) LIMIT 5");

        assertCrossScan(crossUp, 1, 2);
        assertCrossScan(crossDown, 1, 2);
        assertTrue(crossUp.sql().contains("LAG(`close`) OVER (PARTITION BY symbol ORDER BY trade_date)"));
        assertTrue(crossDown.sql().contains("LAG(`open`) OVER (PARTITION BY symbol ORDER BY trade_date)"));
        assertTrue(crossUp.sql().contains("`close` > `open` AND `prev_close` <= `prev_open`"));
        assertTrue(crossDown.sql().contains("`close` < `open` AND `prev_close` >= `prev_open`"));
    }

    @Test void windowCrossSignalsScanOneMoreTradingDayThanTheLargestWindow() {
        var crossUp = compiler().compile(
                "SCREEN ON 2026-08-07 WHERE CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20)) LIMIT 5");
        var crossDown = compiler().compile(
                "SCREEN ON 2026-08-07 WHERE CROSS_DOWN(MA(CLOSE, 10), MA(CLOSE, 30)) LIMIT 5");

        assertCrossScan(crossUp, 21, 22);
        assertCrossScan(crossDown, 31, 32);
        assertTrue(crossUp.sql().contains("FROM metrics\n)"));
        assertTrue(crossDown.sql().contains("FROM metrics\n)"));
        assertTrue(crossUp.sql().contains("LAG(`ma_close_20`) OVER (PARTITION BY symbol ORDER BY trade_date)"));
        assertTrue(crossDown.sql().contains("LAG(`ma_close_30`) OVER (PARTITION BY symbol ORDER BY trade_date)"));
    }

    @Test void emaUsesRecursiveReferenceSemanticsAndNeverDegradesToMovingAverage() {
        assertEquals(List.of(10.0, 11.0, 12.5, 12.75),
                referenceEma(List.of(10.0, 12.0, 14.0, 13.0), 3));

        CompileException error = assertThrows(CompileException.class,
                () -> compiler().compile("SCREEN ON 2026-08-07 WHERE EMA(CLOSE, 20) > 10 LIMIT 5"));
        assertEquals("EMA_LOWERING_UNAVAILABLE", error.code());
        assertTrue(error.getMessage().contains("recursive semantics"));
        assertTrue(error.getMessage().contains("refusing to lower it as MA"));
    }

    @Test void rsiSeparatesLagAndAverageWindowsAndMatchesKnownSequence() {
        var artifact = compiler().compile(
                "SCREEN ON 2026-08-07 WHERE RSI(CLOSE, 3) > 50 LIMIT 5");

        String sql = artifact.sql();
        assertEquals(4, artifact.requiredLookbackTradingDays());
        assertTrue(sql.indexOf("changes AS (") < sql.indexOf("metrics AS ("));
        assertTrue(sql.contains("`close` - LAG(`close`) OVER (PARTITION BY symbol ORDER BY trade_date) AS `change_close`"));
        assertTrue(sql.contains("AVG(GREATEST(`change_close`, 0)) OVER"));
        assertTrue(sql.contains("AVG(ABS(LEAST(`change_close`, 0))) OVER"));
        assertFalse(sql.contains("AVG(GREATEST((`close` - LAG("));
        assertEquals(75.0, referenceRsi(List.of(10.0, 11.0, 10.0, 12.0), 3), 0.000001);
    }

    private static DslCompiler compiler() {
        return new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    }

    private static void assertCrossScan(CompilationArtifact artifact, int lookback, int calendarLimit) {
        assertEquals(lookback, artifact.requiredLookbackTradingDays());
        assertTrue(artifact.sql().contains("q.trade_date BETWEEN ("));
        assertTrue(artifact.sql().contains("ORDER BY cal_date DESC LIMIT " + calendarLimit));
        assertTrue(artifact.sql().contains("WHERE trade_date = ?"),
                "target-date filtering must remain in the final layer");
        assertFalse(artifact.sql().contains("FROM market.dwd_quote_daily q\n  WHERE q.trade_date = ?"),
                "base scan must not be truncated to the target date");
    }

    private static List<Double> referenceEma(List<Double> values, int window) {
        double alpha = 2.0 / (window + 1.0);
        List<Double> result = new ArrayList<>();
        double previous = values.getFirst();
        result.add(previous);
        for (int index = 1; index < values.size(); index++) {
            previous = alpha * values.get(index) + (1.0 - alpha) * previous;
            result.add(previous);
        }
        return result;
    }

    private static double referenceRsi(List<Double> values, int window) {
        double gains = 0.0;
        double losses = 0.0;
        for (int index = values.size() - window; index < values.size(); index++) {
            double change = values.get(index) - values.get(index - 1);
            gains += Math.max(change, 0.0);
            losses += Math.max(-change, 0.0);
        }
        double averageGain = gains / window;
        double averageLoss = losses / window;
        return averageLoss == 0.0 ? 100.0 : 100.0 - 100.0 / (1.0 + averageGain / averageLoss);
    }

    private static void assertMetadata(String name, String version, String description, String signature,
                                       List<String> boundaryTests) {
        assertNotNull(version, name + " must have version");
        assertFalse(version.isBlank(), name + " must have version");
        assertNotNull(description, name + " must have description");
        assertFalse(description.isBlank(), name + " must have description");
        assertNotNull(signature, name + " must have type signature");
        assertFalse(signature.isBlank(), name + " must have type signature");
        assertFalse(boundaryTests.isEmpty(), name + " must have boundary tests");
    }
}
