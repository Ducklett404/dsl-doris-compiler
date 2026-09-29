package com.acme.dorisdsl;

import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.catalog.CatalogSnapshotLoader;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class FeatureDailyLoweringTest {
    private static final String HIGH_FREQUENCY_DSL = """
            SCREEN ON 2026-08-07
            WHERE MA(CLOSE, 5) > MA(CLOSE, 20) AND ROE_TTM() > 0.1
            ADJUST FORWARD
            LIMIT 20
            """;

    @Test void highFrequencyIndicatorsPreferFeatureDailyAndBindVersions() {
        var artifact = compiler(new CatalogSnapshotLoader().loadDefault()).compile(HIGH_FREQUENCY_DSL);

        assertEquals("FEATURE_DAILY", artifact.logicalPlan().accessPath().selected());
        assertTrue(artifact.sql().contains("market.dws_quote_feature_daily"));
        assertTrue(artifact.sql().contains("`ma_close_5` AS `ma_close_5"));
        assertTrue(artifact.sql().contains("`ma_close_20` AS `ma_close_20"));
        assertTrue(artifact.sql().contains("`roe_ttm` AS `roe_ttm"));
        assertTrue(artifact.sql().contains("feature_version = ?"));
        assertTrue(artifact.sql().contains("adjustment_version = ?"));
        assertTrue(artifact.sql().contains("source_snapshot = ?"));
        assertTrue(artifact.bindings().contains("feature-v17"));
        assertTrue(artifact.bindings().contains("qfq-v3"));
        assertTrue(artifact.bindings().contains("quote-financial-2026-08-12.1"));
    }

    @Test void staleFeatureVersionFallsBackToDetailTable() {
        var current = new CatalogSnapshotLoader().loadDefault();
        var staleFeature = new CatalogSnapshot.FeatureMetadata(current.feature().version(),
                current.feature().adjustmentVersion(), current.feature().sourceSnapshot(),
                LocalDate.parse("2026-08-06"), current.feature().refreshedAt(), current.feature().indicatorColumns());
        var stale = new CatalogSnapshot("stale-feature-v1", current.capturedAt(), current.tables(),
                current.tableMetadata(), current.prefixDaily(), staleFeature, current.doris());

        var artifact = compiler(stale).compile(HIGH_FREQUENCY_DSL);

        assertEquals("DETAIL_TABLE", artifact.logicalPlan().accessPath().selected());
        assertTrue(artifact.logicalPlan().accessPath().reason().contains("mandatory fallback"));
        assertTrue(artifact.sql().contains("market.dwd_quote_daily"));
        assertFalse(artifact.sql().contains("market.dws_quote_feature_daily"));
    }

    @Test void exposesVolatilityColumnMappingInSnapshot() {
        var feature = new CatalogSnapshotLoader().loadDefault().feature();
        assertEquals("volatility_20", feature.indicatorColumns().get("VOLATILITY(CLOSE,20)"));
    }

    private DslCompiler compiler(CatalogSnapshot snapshot) {
        return new DslCompiler(new RegistryLoader().loadDefault(List.of()), snapshot);
    }
}
