package com.acme.dorisdsl;
import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;
import java.time.LocalDate;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class RollingFeatureTest {
    private final StockSlotRegistry registry=new StockSlotRegistryLoader().loadDefault();
    private static final String ID="rolling-test",HASH="c".repeat(64);
    private String ma(int n){return "indicator('沪', '', '"+n+"日均线', '2026-04-14', '', '', '')";}
    private RollingAverageFeatureCatalog catalog(String fingerprint){return new RollingAverageFeatureCatalog(
        "rolling-average-v1",ID,HASH,fingerprint,"isolated.averages",registry.expression(registry.indicator("收盘价")),
        Map.of(LocalDate.parse("2026-04-14"),10L),Map.of(20,"ma20",60,"ma60",120,"ma120",250,"ma250"));}
    private StockSlotSqlCompiler compiler(){return new StockSlotSqlCompiler(registry,16,null,catalog(registry.fingerprint()));}
    private boolean feature(StockSlotSqlArtifact a){return a.logicalPlan().stream().anyMatch(n->n.kind().equals("RollingFeatureScan"));}
    @Test void multiWindowFeaturesKeepStrictContractsAndCorrectIdentity(){
        var dsl=ma(20)+">1 and "+ma(120)+">1 and "+ma(250)+">1";var c=compiler();
        var a=c.compileForSnapshot(dsl,ID,HASH);assertTrue(feature(a));assertFalse(a.sql().contains(" OVER "));
        assertTrue(a.sql().contains("h.`ma20`"));assertTrue(a.sql().contains("h.`ma120`"));assertTrue(a.sql().contains("h.`ma250`"));
        assertEquals(c.compile(dsl,StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).windowContracts(),a.windowContracts());
        assertEquals(ID,a.bindings().get(0));assertEquals(HASH,a.bindings().get(1));
    }
    @Test void cacheAndUnpublishedContextsFallBack(){
        var c=compiler();var dsl=ma(60)+">1";assertTrue(feature(c.compileForSnapshot(dsl,ID,HASH)));
        assertFalse(feature(c.compileForSnapshot(dsl,"other",HASH)));assertFalse(feature(c.compileForSnapshot(dsl,ID,"d".repeat(64))));
        assertFalse(feature(c.compileForSnapshot(dsl,ID)));assertFalse(feature(c.compile(dsl)));
        assertFalse(feature(c.compileForSnapshot(dsl.replace("2026-04-14","2026-04-13"),ID,HASH)));
        assertTrue(feature(c.compileForSnapshot(dsl,ID,HASH)));
    }
    @Test void unsupportedWindowCountsRawAndRsiUseCompleteWindows(){
        for(var dsl:new String[]{ma(5)+">1",ma(20).replace("'', '', '')","'', '', 'CONS>=2日')")+">1",
            ma(60)+">indicator('沪', '', '收盘价', '2026-04-14', '', '', '')",
            ma(60)+">indicator('沪', '', 'RSI(14)', '2026-04-14', '', '', '')"}){
            var a=compiler().compileForSnapshot(dsl,ID,HASH);assertFalse(feature(a));assertTrue(a.sql().contains("v_hsj_stock_hq_basic"));
        }
    }
    @Test void staleRegistryFallsBack(){
        var c=new StockSlotSqlCompiler(registry,16,null,catalog("d".repeat(64)));
        assertFalse(feature(c.compileForSnapshot(ma(20)+">1",ID,HASH)));
    }
    @Test void finiteExtremaMixWithAveragesAndKeepWindowContracts(){
        var x=catalog(registry.fingerprint());var range=new RollingAverageFeatureCatalog.RangeColumns("b.highPrice",250,"high_current","high_min250","high_max250");
        var enhanced=new RollingAverageFeatureCatalog(x.formatVersion(),x.snapshotId(),x.manifestSha256(),x.registryFingerprint(),
            x.qualifiedTable(),x.sourceExpression(),x.completeDates(),x.windowFields(),Map.of("high250",range));
        var c=new StockSlotSqlCompiler(registry,16,null,enhanced);
        var dsl=ma(20)+">1 and record_high('沪', '', '最高价', '250日', '2026-04-14', '', '', '') = True";
        var a=c.compileForSnapshot(dsl,ID,HASH);assertTrue(feature(a));assertTrue(a.sql().contains("h.`high_current` = h.`high_max250`"));
        assertEquals(c.compile(dsl,StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).windowContracts(),a.windowContracts());
        assertFalse(feature(c.compileForSnapshot(dsl.replace("250日","120日"),ID,HASH)));
    }
    @Test void differentAverageSourceCannotReuseCloseFeature(){
        var x=catalog(registry.fingerprint());var bad=new RollingAverageFeatureCatalog(x.formatVersion(),ID,HASH,x.registryFingerprint(),
            x.qualifiedTable(),"b.openPrice",x.completeDates(),x.windowFields());
        assertFalse(feature(new StockSlotSqlCompiler(registry,16,null,bad).compileForSnapshot(ma(20)+">1",ID,HASH)));
    }
    @Test void legacyMa60MixingNoLongerRejectsValidDsl(){
        var c=new StockSlotSqlCompiler();var dsl=ma(60)+">"+ma(20);
        var a=c.compileForSnapshot(dsl,"stock-20060104-20260414-v1");
        assertEquals(c.compile(dsl,StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE).sql(),a.sql());
        assertFalse(a.sql().contains("stock_daily_features_v2"));
    }
    @Test void safeCatalogRoundTripAndIdentifierValidation()throws Exception{
        var x=catalog(registry.fingerprint());assertEquals(x,JsonSupport.MAPPER.readValue(JsonSupport.MAPPER.writeValueAsBytes(x),RollingAverageFeatureCatalog.class));
        assertThrows(IllegalArgumentException.class,()->new RollingAverageFeatureCatalog("rolling-average-v1",ID,HASH,
            registry.fingerprint(),"isolated.averages", "b.closePrice",x.completeDates(),Map.of(20,"x`; DROP TABLE x")));
    }
}
