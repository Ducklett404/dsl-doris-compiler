package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.*;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.math.BigDecimal;
import java.nio.file.*;
import java.time.LocalDate;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ReviewRegressionTest {
    private final StockSlotSqlCompiler slot = new StockSlotSqlCompiler();
    private static String indicator(String metric, String date) {
        return "indicator('', '', '" + metric + "', '" + date + "', '', '', '')";
    }
    @Test void featureCoverageAndSnapshotMismatchFallBack() {
        String current = indicator("60日均线", "2026-04-14") + " > 1";
        assertTrue(slot.compile(current).sql().contains("stock_daily_features_v2"));
        for (String date : List.of("2026-04-13", "2026-04-15"))
            assertFalse(slot.compile(indicator("60日均线", date) + " > 1").sql().contains("stock_daily_features"));
        assertFalse(slot.compileForSnapshot(current, "other-validated-snapshot").sql().contains("stock_daily_features"));
        assertTrue(slot.compileForSnapshot(current, "stock-20060104-20260414-v1").sql().contains("stock_daily_features_v2"));
    }
    @Test void betweenBindingsFollowSqlOccurrenceOrderInBothPaths() {
        for (String metric : List.of("收盘价", "5日均线")) {
            var a = slot.compile("(" + indicator(metric,"2026-04-14") + " + 1) between '[2,4]'");
            assertEquals(a.bindings().size(), a.sql().chars().filter(c -> c == '?').count());
            assertEquals(List.of(new BigDecimal("1"),new BigDecimal("2"),new BigDecimal("1"),new BigDecimal("4")),
                    a.bindings().subList(a.bindings().size()-4,a.bindings().size()));
        }
    }
    @Test void nullChecksRetainFieldAndWindowDependencies() {
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        assertTrue(compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE IS NULL LIMIT 5").sql().contains("AS `close`"));
        for (String nullCheck : List.of("IS NULL", "IS NOT NULL")) {
            var a = compiler.compile("SCREEN ON 2026-08-07 WHERE MA(CLOSE, 5) " + nullCheck + " LIMIT 5");
            assertTrue(a.sql().contains("close_sum"));
            assertFalse(a.sql().contains("`null`"));
        }
    }
    @Test void countClausesCannotDisappearAndBooleanCountsAreLowered() {
        String arithmetic = "indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') + 1 > 2";
        assertCode("EXECUTION_COUNT_SHAPE", arithmetic);
        String rank = "rank('', '', '收盘价', 'desc', '2026-04-14', '', '', 'CONS>=3日') <= 1";
        assertCode("EXECUTION_COUNT_RANK",rank);
        var a = slot.compile("record_high('', '', '收盘价', '3日', '2026-04-14', '', '', 'CONS>=3日')");
        assertTrue(a.sql().contains("counted AS"));
        assertTrue(a.sql().contains("WHERE `c1`"));
    }
    @Test void invalidTypesAndNullLiteralsHaveStableDiagnostics() {
        assertCode("NULL_LITERAL_UNSUPPORTED",indicator("收盘价","2026-04-14") + " = null");
        assertCode("COMPARISON_TYPE",indicator("收盘价","2026-04-14") + " > 'abc'");
        assertCode("COMPARISON_TYPE","true > false");
        assertCode("COMPARISON_TYPE","'a' ~= 'b'");
        assertCode("COMPARISON_TYPE","'a' between '[1,3]'");
        assertFalse(slot.compile(indicator("换手率","2026-04-14")+" > 1%").sql().isBlank());
    }
    @Test void industryMissingValuesAreNullGuarded() {
        for (String fn : List.of("belong_industry", "industry_max"))
            assertTrue(slot.compile(fn+"('', '', '收盘价', '2026-04-14', '') > 1").sql().contains("CASE WHEN hyBlkRefName IS NULL THEN NULL"));
    }
    @Test void repeatedAndReorderedTemplateArgumentsKeepTheirBindings(@TempDir Path temp) throws Exception {
        var root = JsonSupport.MAPPER.readTree(Path.of("src/main/resources/registry.json").toFile());
        var function = JsonSupport.MAPPER.readTree("""
                {"name":"REORDER","minArgs":2,"maxArgs":2,
                 "returnType":"NUMBER","loweringKind":"TEMPLATE","sqlTemplate":"({1}+{0}+{1})","requiredFields":[]}
                """);
        ((com.fasterxml.jackson.databind.node.ArrayNode)root.get("functions")).add(function);
        Path registry = temp.resolve("registry.json");
        JsonSupport.MAPPER.writeValue(registry.toFile(), root);
        var compiler = new DslCompiler(new RegistryLoader().load(registry,List.of()));
        var a = compiler.compile("SCREEN ON 2026-08-07 WHERE REORDER(2,3)>0 LIMIT 5");
        assertEquals(List.of(new BigDecimal("3"),new BigDecimal("2"),new BigDecimal("3"),new BigDecimal("0")),
                a.bindings().subList(a.bindings().size()-4,a.bindings().size()));
        assertEquals(a.bindings().size(),a.sql().chars().filter(c -> c=='?').count());
    }
    @Test void exportGeneratedQueriesForIndependentResultDifferential() throws Exception {
        var queries = new LinkedHashMap<String,Object>();
        for (String date : List.of("2026-04-13","2026-04-14")) {
            String source=indicator("60日均线",date)+" > 1";
            queries.put("ma_"+date+"_optimized",slot.compile(source));
            queries.put("ma_"+date+"_reference",slot.compile(source,StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE));
        }
        queries.put("between_simple",slot.compile("("+indicator("收盘价","2026-04-14")+"+1) between '[2,4]'"));
        queries.put("between_advanced",slot.compile("("+indicator("5日均线","2026-04-14")+"+1) between '[2,4]'"));
        queries.put("industry",slot.compile("belong_industry('', '', '收盘价', '2026-04-14', '') > 1"));
        queries.put("industry_max",slot.compile("industry_max('', '', '收盘价', '2026-04-14', '') > 1"));
        queries.put("count_boolean",slot.compile("record_high('', '', '收盘价', '3日', '2026-04-14', '', '', 'CONS>=3日')"));
        queries.put("rsi",slot.compile(indicator("RSI(3)","2026-04-14")+" > 50"));
        queries.put("screen_null",new DslCompiler(new RegistryLoader().loadDefault(List.of()))
                .compile("SCREEN ON 2026-08-07 WHERE CLOSE IS NULL LIMIT 5"));
        JsonSupport.MAPPER.writeValue(Path.of("target/review-regression-queries.json").toFile(),queries);
    }
    private void assertCode(String code,String source) {
        assertEquals(code,assertThrows(CompileException.class,()->slot.compile(source)).code());
    }
}
