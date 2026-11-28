import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import com.acme.dorisdsl.util.JsonSupport;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/** Serial JDBC replay. Keep failed attempts and fully fetch each result before stopping its clock. */
public class LookupProbe {
    public static void main(String[] args) throws Exception {
        var json = JsonSupport.MAPPER;
        var compiler = new StockSlotSqlCompiler();
        try (var db = DriverManager.getConnection(System.getenv("DORIS_DIAGNOSTIC_URL"),
                     System.getenv("DORIS_DIAGNOSTIC_USER"), System.getenv("DORIS_DIAGNOSTIC_PASSWORD"));
             var session = db.createStatement()) {
            for (var sql : List.of("SET enable_sql_cache=false", "SET enable_query_cache=false",
                    "SET query_timeout=60", "SET exec_mem_limit=2147483648")) session.execute(sql);
            for (var item : json.readTree(Path.of(args[0]).toFile())) {
                var out = new LinkedHashMap<String,Object>();
                var id = item.path("id").asText();
                long start = System.nanoTime();
                try {
                    var plan = compiler.compile(item.path("dsl").asText(), StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
                    out.put("sql", plan.sql());
                    out.put("bindings", plan.bindings());
                    start = System.nanoTime();
                    try (var statement = db.prepareStatement(plan.sql())) {
                        statement.setQueryTimeout(60);
                        DorisPerformanceDiagnostic.bind(statement, plan.bindings());
                        try (var rs = statement.executeQuery()) {
                            var meta = rs.getMetaData();
                            var columns = new ArrayList<String>();
                            for (int i=1; i<=meta.getColumnCount(); i++) columns.add(meta.getColumnLabel(i));
                            out.put("columns", columns);
                            var rows = new ArrayList<List<String>>();
                            while (rs.next()) {
                                var row = new ArrayList<String>();
                                for (int i=1; i<=columns.size(); i++) row.add(rs.getString(i));
                                rows.add(row);
                            }
                            out.put("rows", rows);
                        }
                    }
                } catch (Exception error) {
                    out.put("error", error.toString());
                }
                out.put("ms", (System.nanoTime()-start)/1e6);
                try (var stream = new java.util.zip.GZIPOutputStream(Files.newOutputStream(
                        Path.of(args[1]).resolve(id+".json.gz")))) {
                    json.writeValue(stream, out);
                }
            }
        }
    }
}
