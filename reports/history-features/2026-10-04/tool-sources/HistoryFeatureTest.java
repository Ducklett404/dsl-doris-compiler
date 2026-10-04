package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import java.time.LocalDate;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class HistoryFeatureTest {
    private final StockSlotRegistry registry = new StockSlotRegistryLoader().loadDefault();
    private static final String SNAPSHOT="test-snapshot", MANIFEST="a".repeat(64);
    private static final String DSL="record_high('沪', '', '收盘价', '历史', '2026-04-14', '', '', '') = True";
    private HistoricalExtremaFeatureCatalog catalog(String fingerprint, String table) {
        return new HistoricalExtremaFeatureCatalog("history-extrema-v1", SNAPSHOT, MANIFEST, fingerprint, table,
            Map.of(LocalDate.parse("2026-04-14"), 100L), Map.of("close", new HistoricalExtremaFeatureCatalog.MetricColumns(
                registry.expression(registry.indicator("收盘价")), "close_current", "close_min", "close_max")));
    }
    private StockSlotSqlCompiler compiler() { return new StockSlotSqlCompiler(registry, 16, catalog(registry.fingerprint(), "isolated.extrema")); }
    private boolean feature(StockSlotSqlArtifact artifact) { return artifact.logicalPlan().stream().anyMatch(n -> n.kind().equals("HistoricalFeatureScan")); }

    @Test void exactIdentityUsesBoundFeaturesAndPreservesWindowContracts() {
        var compiler=compiler();var actual=compiler.compileForSnapshot(DSL,SNAPSHOT,MANIFEST);
        assertTrue(feature(actual));assertTrue(actual.sql().contains("h.`close_current` = h.`close_max`"));
        assertFalse(actual.sql().contains("OVER ("));assertTrue(actual.sql().contains("h.mktcode=1"));
        assertEquals(compiler.compile(DSL,StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).windowContracts(),actual.windowContracts());
        assertEquals(SNAPSHOT,actual.bindings().get(0));assertEquals(MANIFEST,actual.bindings().get(1));
        assertEquals(registry.fingerprint(),actual.bindings().get(2));
    }
    @Test void cacheSeparatesSnapshotManifestAndUnboundCompilation() {
        var compiler=compiler();assertTrue(feature(compiler.compileForSnapshot(DSL,SNAPSHOT,MANIFEST)));
        assertFalse(feature(compiler.compileForSnapshot(DSL,"different",MANIFEST)));
        assertFalse(feature(compiler.compileForSnapshot(DSL,SNAPSHOT,"b".repeat(64))));
        assertFalse(feature(compiler.compileForSnapshot(DSL,SNAPSHOT)));
        assertFalse(feature(compiler.compile(DSL)));
        assertTrue(feature(compiler.compileForSnapshot(DSL,SNAPSHOT,MANIFEST)));
        assertFalse(feature(compiler.compile(DSL,StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE)));
    }
    @Test void staleRegistryAndUnbuiltDateFallBack() {
        var stale=new StockSlotSqlCompiler(registry,16,catalog("b".repeat(64),"isolated.extrema"));
        assertFalse(feature(stale.compileForSnapshot(DSL,SNAPSHOT,MANIFEST)));
        assertFalse(feature(compiler().compileForSnapshot(DSL.replace("2026-04-14","2026-04-13"),SNAPSHOT,MANIFEST)));
    }
    @ParameterizedTest @ValueSource(strings={
        "record_high('', '', '最高价', '历史', '2026-04-14', '', '', '') = True",
        "record_high('', '', '收盘价', '3日', '2026-04-14', '', '', '') = True",
        "record_high('', '', '收盘价', '历史', '2026-04-14', '', '', 'CONS>=2日') = True",
        "record_high('', '', '收盘价', '历史', '2026-04-14', '', '', '') = True and indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1"
    }) void unavailableMetricFinitePeriodCountsAndMixedCallsFallBack(String dsl) {
        assertFalse(feature(compiler().compileForSnapshot(dsl,SNAPSHOT,MANIFEST)));
    }
    @Test void lowAndScopeUseCorrectColumnsAndBindings() {
        var result=compiler().compileForSnapshot(DSL.replace("record_high","record_low").replace("'沪', ''","'沪', '行业A|行业B'"),SNAPSHOT,MANIFEST);
        assertTrue(feature(result));assertTrue(result.sql().contains("h.`close_current` = h.`close_min`"));
        assertTrue(result.sql().contains("c.hyBlkRefName IN (?,?)"));
        assertEquals("行业A",result.bindings().get(4));assertEquals("行业B",result.bindings().get(5));
    }
    @Test void catalogRoundTripsAndRejectsUnsafeIdentifiers() throws Exception {
        var catalog=catalog(registry.fingerprint(),"isolated.extrema");
        assertEquals(catalog,JsonSupport.MAPPER.readValue(JsonSupport.MAPPER.writeValueAsBytes(catalog),HistoricalExtremaFeatureCatalog.class));
        assertThrows(IllegalArgumentException.class,()->catalog(registry.fingerprint(),"isolated.extrema; DROP DATABASE newzl"));
        assertThrows(IllegalArgumentException.class,()->new HistoricalExtremaFeatureCatalog.MetricColumns("b.closePrice","x`","min","max"));
    }
    @Test void registryFingerprintIsDeterministic() {
        assertEquals(registry.fingerprint(),new StockSlotRegistryLoader().loadDefault().fingerprint());
    }
}
