package com.acme.dorisdsl;

import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.catalog.CatalogSnapshotLoader;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class CatalogSnapshotTest {
    private static final String DSL = "SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5";

    @Test void loadsCompleteImmutableCatalogSnapshot() {
        var snapshot = new CatalogSnapshotLoader().loadDefault();

        assertEquals("market.dwd_quote_daily", snapshot.tables().detailTable());
        assertEquals("market.dwd_financial_pit", snapshot.tables().financialPitTable());
        assertEquals("market.dim_trade_calendar", snapshot.tables().calendarTable());
        assertEquals("market.dws_quote_feature_daily", snapshot.tables().featureTable());
        assertEquals("market.dws_quote_prefix_sum_daily", snapshot.tables().prefixSumTable());
        assertTrue(snapshot.tableMetadata().get("DETAIL").estimatedRows() > 0);
        assertNotNull(snapshot.tableMetadata().get("DETAIL").partitionRange());
        assertFalse(snapshot.tableMetadata().get("DETAIL").bucketInfo().keys().isEmpty());
        assertFalse(snapshot.tableMetadata().get("DETAIL").indexes().isEmpty());
        assertFalse(snapshot.tableMetadata().get("DETAIL").materializedViews().isEmpty());
        assertFalse(snapshot.feature().version().isBlank());
        assertNotNull(snapshot.feature().refreshedAt());
        assertTrue(snapshot.doris().supports("windowFunctions"));
        assertThrows(UnsupportedOperationException.class,
                () -> snapshot.tableMetadata().put("OTHER", snapshot.tableMetadata().get("DETAIL")));
    }

    @Test void compileReadsCapturedSnapshotOnlyAndCachesByMetadataVersion() {
        var registry = new RegistryLoader().loadDefault(List.of());
        var compiler = new DslCompiler(registry, snapshot("meta-v1", "tenant_v1.quote_daily"));

        var first = compiler.compile(DSL);
        var cached = compiler.compile(DSL);
        var secondVersion = new DslCompiler(registry, snapshot("meta-v2", "tenant_v2.quote_daily")).compile(DSL);

        assertSame(first, cached, "same DSL and metadata version should hit the in-memory cache");
        assertTrue(first.sql().contains("tenant_v1.quote_daily"));
        assertEquals("meta-v1", first.metadataVersion());
        assertEquals("meta-v1", first.cacheKey().metadataVersion());
        assertEquals("meta-v2", secondVersion.metadataVersion());
        assertNotEquals(first.cacheKey(), secondVersion.cacheKey());
        assertTrue(secondVersion.sql().contains("tenant_v2.quote_daily"));
    }

    @Test void snapshotDefensivelyCopiesMetadataCollections() {
        var indexes = new ArrayList<>(List.of("idx_date"));
        var metadata = new LinkedHashMap<String, CatalogSnapshot.TableMetadata>();
        metadata.put("DETAIL", tableMetadata(indexes));
        var snapshot = new CatalogSnapshot("immutable-v1", Instant.parse("2026-08-12T08:00:00Z"), tables("market.detail"),
                metadata, new CatalogSnapshot.FeatureMetadata("f1", Instant.parse("2026-08-12T07:00:00Z")),
                new CatalogSnapshot.DorisCapabilities("3.0.5", Map.of("windowFunctions", true)));

        indexes.add("idx_late_mutation");
        metadata.clear();

        assertEquals(List.of("idx_date"), snapshot.tableMetadata().get("DETAIL").indexes());
        assertEquals(1, snapshot.tableMetadata().size());
    }

    private static CatalogSnapshot snapshot(String version, String detailTable) {
        var detail = tableMetadata(List.of("idx_date"));
        return new CatalogSnapshot(version, Instant.parse("2026-08-12T08:00:00Z"), tables(detailTable),
                Map.of("DETAIL", detail, "FEATURE", detail, "PREFIX_SUM", detail),
                new CatalogSnapshot.FeatureMetadata("feature-v1", Instant.parse("2026-08-12T07:30:00Z")),
                new CatalogSnapshot.DorisCapabilities("3.0.5", Map.of("windowFunctions", true)));
    }

    private static CatalogSnapshot.TableMetadata tableMetadata(List<String> indexes) {
        return new CatalogSnapshot.TableMetadata(
                new CatalogSnapshot.PartitionRange(LocalDate.parse("2020-01-01"), LocalDate.parse("2026-08-11")),
                1000, new CatalogSnapshot.BucketInfo(List.of("symbol"), 8), indexes, List.of());
    }

    private static CatalogSnapshot.TableMappings tables(String detailTable) {
        return new CatalogSnapshot.TableMappings(detailTable, "market.financial", "market.calendar",
                "market.feature", "market.prefix");
    }
}
