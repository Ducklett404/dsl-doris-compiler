package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.catalog.CatalogSnapshotLoader;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class PrefixDailyLoweringTest {
    private final DslCompiler compiler = prefixCompiler();

    @Test void lowersMovingAverageToTwoPointPrefixDifference() {
        var artifact = compiler.compile("SCREEN ON 2026-08-07 WHERE MA(CLOSE, 20) > 10 LIMIT 5");

        assertEquals("PREFIX_DAILY", artifact.logicalPlan().accessPath().selected());
        assertTrue(artifact.sql().contains("market.dws_quote_prefix_daily"));
        assertTrue(artifact.sql().contains("trading_day_seq = t.trading_day_seq - 20"));
        assertTrue(artifact.sql().contains("cur.close_sum - COALESCE(prev_ma_close_20.close_sum, 0)"));
        assertTrue(artifact.sql().contains("cur.close_count - COALESCE(prev_ma_close_20.close_count, 0)"));
        assertTrue(artifact.sql().contains("THEN (cur.close_sum"));
        assertTrue(artifact.sql().contains("ELSE NULL END"), "insufficient windows must be NULL");
        assertFalse(artifact.sql().contains("AVG("));
    }

    @Test void prefixDifferenceMatchesDetailWindowWithoutGap() {
        List<Double> tradingDayValues = List.of(10.0, 12.0, 14.0, 16.0);
        int window = 3;
        double detail = tradingDayValues.subList(1, 4).stream().mapToDouble(Double::doubleValue).average().orElseThrow();
        double currentSum = tradingDayValues.stream().mapToDouble(Double::doubleValue).sum();
        double previousSum = tradingDayValues.get(0);
        long currentCount = tradingDayValues.size();
        long previousCount = 1;
        Double prefix = strictPrefixAverage(currentSum, previousSum, currentCount, previousCount, window);

        assertEquals(detail, prefix);
        assertEquals(14.0, prefix);
    }

    @Test void suspensionGapReturnsNullInBothPaths() {
        Double detail = strictDetailAverage(List.of(nullValue(), 14.0, 16.0), 3);
        Double prefix = strictPrefixAverage(40.0, 10.0, 3, 1, 3);

        assertNull(detail);
        assertNull(prefix);
    }

    @Test void insufficientWindowReturnsNull() {
        assertNull(strictPrefixAverage(22.0, 0.0, 2, 0, 3));
    }

    private static Double strictPrefixAverage(double currentSum, double previousSum,
                                              long currentCount, long previousCount, int window) {
        long observations = currentCount - previousCount;
        return observations == window ? (currentSum - previousSum) / window : null;
    }

    private static Double strictDetailAverage(List<Double> values, int window) {
        long observations = values.stream().filter(value -> !Double.isNaN(value)).count();
        return observations == window
                ? values.stream().mapToDouble(Double::doubleValue).average().orElseThrow() : null;
    }

    private static Double nullValue() { return Double.NaN; }

    private static DslCompiler prefixCompiler() {
        var snapshot = new CatalogSnapshotLoader().loadDefault();
        var feature = new CatalogSnapshot.FeatureMetadata(snapshot.feature().version(),
                snapshot.feature().adjustmentVersion(), snapshot.feature().sourceSnapshot(),
                snapshot.feature().sourceSnapshotAsOf(), snapshot.feature().refreshedAt(), java.util.Map.of());
        var prefixSnapshot = new CatalogSnapshot(snapshot.version(), snapshot.capturedAt(), snapshot.tables(),
                snapshot.tableMetadata(), snapshot.prefixDaily(), feature, snapshot.doris());
        return new DslCompiler(new RegistryLoader().loadDefault(List.of()), prefixSnapshot);
    }
}
