import com.acme.dorisdsl.compiler.*;
import com.acme.dorisdsl.registry.*;
import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import java.util.*;
import java.nio.file.*;

public class ReviewProbe {
  public static void main(String[] args) throws Exception {
    var slot = new StockSlotSqlCompiler();
    var screen = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    var cases = new LinkedHashMap<String,String>();
    cases.put("historical_ma60", "indicator('', '', '60日均线', '2026-04-13', '', '', '') > 1");
    cases.put("frozen_ma60", "indicator('', '', '60日均线', '2026-04-14', '', '', '') > 1");
    cases.put("simple_between_expression", "(indicator('', '', '收盘价', '2026-04-14', '', '', '') + 1) between '[2,4]'");
    cases.put("advanced_between_expression", "(indicator('', '', '5日均线', '2026-04-14', '', '', '') + 1) between '[2,4]'");
    cases.put("missing_industry", "belong_industry('', '', '收盘价', '2026-04-14', '') > 1");
    cases.put("count_arithmetic", "indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') + 1 > 2");
    cases.put("count_boolean", "cross_above('', '', '收盘价', '开盘价', '2026-04-14', '', 'CONS>=3日')");
    cases.put("count_direct", "indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') > 1");
    cases.put("null_literal", "indicator('', '', '收盘价', '2026-04-14', '', '', '') = null");
    cases.put("type_mismatch", "indicator('', '', '收盘价', '2026-04-14', '', '', '') > 'abc'");
    cases.put("minimum_limit", "indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1 limit 5,10");
    cases.put("screen_is_null_field", "SCREEN ON 2026-08-07 WHERE CLOSE IS NULL LIMIT 5");
    cases.put("screen_is_null_window", "SCREEN ON 2026-08-07 WHERE MA(CLOSE, 5) IS NOT NULL LIMIT 5");
    var results = new ArrayList<Map<String,Object>>();
    for (var c : cases.entrySet()) {
      var row = new LinkedHashMap<String,Object>();
      row.put("case",c.getKey()); row.put("dsl",c.getValue());
      try {
        String sql; List<Object> bindings;
        if (c.getKey().startsWith("screen_")) {
          var a = screen.compile(c.getValue()); sql = a.sql(); bindings = a.bindings();
        } else {
          var a = slot.compile(c.getValue()); sql = a.sql(); bindings = a.bindings();
          row.put("plan",a.logicalPlan());
          if (c.getKey().equals("historical_ma60") || c.getKey().equals("frozen_ma60")) {
            var ref = slot.compile(c.getValue(), StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
            row.put("referenceSql",ref.sql());
          }
        }
        row.put("sql",sql); row.put("bindings",bindings);
        row.put("placeholderCount",sql.chars().filter(v -> v == '?').count());
        row.put("bindingCount",bindings.size());
        System.out.println(c.getKey()+": OK placeholders="+row.get("placeholderCount")+" bindings="+bindings.size());
      } catch(Throwable e) {
        row.put("error",e.getClass().getSimpleName()); row.put("message",String.valueOf(e.getMessage()));
        System.out.println(c.getKey()+": "+e.getClass().getSimpleName()+" "+e.getMessage());
      }
      results.add(row);
    }
    Files.writeString(Path.of("target/review-probe.json"),JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(results));
  }
}
