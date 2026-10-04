import com.acme.dorisdsl.stockslot.StockSlotSqlArtifact;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import com.acme.dorisdsl.util.JsonSupport;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.sql.*;
import java.time.*;
import java.util.*;

/** Standalone diagnostic script. Does not register snapshots or invoke the acceptance executor. */
public class DorisPerformanceDiagnostic {
    record Execution(double millis, List<List<String>> rows) {}
    static final List<String> FORBIDDEN = List.of("ADMIN_PRIV", "NODE_PRIV", "GRANT_PRIV",
        "LOAD_PRIV", "ALTER_PRIV", "CREATE_PRIV", "DROP_PRIV");

    public static void main(String[] args) throws Exception {
        Path matrixPath = Path.of(args[0]), output = Path.of(args[1]);
        int iterations = Integer.parseInt(args[2]);
        if (iterations < 1) throw new IllegalArgumentException("iterations must be positive");
        Files.createDirectories(output);
        var matrix = JsonSupport.MAPPER.readTree(matrixPath.toFile());
        var compiler = new StockSlotSqlCompiler();
        var results = new ArrayList<Map<String, Object>>();
        var report = new LinkedHashMap<String, Object>();
        report.put("purpose", "OFFICIAL_DATA_HOT_PERFORMANCE_DIAGNOSTIC");
        report.put("acceptanceEligible", false);
        report.put("cacheMode", "HOT_SQL_RESULT_CACHE_DISABLED");
        report.put("timingScope", "JDBC prepare, execute and complete fetch; excludes compilation, EXPLAIN and process startup");
        report.put("snapshotId", matrix.path("snapshotId").asText());
        report.put("matrixVersion", matrix.path("matrixVersion").asText());
        report.put("iterationsPerPath", iterations);
        report.put("results", results);
        try (Connection connection = DriverManager.getConnection(System.getenv("DORIS_DIAGNOSTIC_URL"),
                System.getenv("DORIS_DIAGNOSTIC_USER"), System.getenv("DORIS_DIAGNOSTIC_PASSWORD"))) {
            try (var statement = connection.createStatement(); var grants = statement.executeQuery("SHOW GRANTS")) {
                boolean select = false;
                while (grants.next()) for (int i = 1; i <= grants.getMetaData().getColumnCount(); i++) {
                    String value = Objects.toString(grants.getString(i), "").toUpperCase(Locale.ROOT);
                    if (FORBIDDEN.stream().anyMatch(value::contains)) throw new SecurityException("Diagnostic account has write/admin privileges");
                    select |= value.contains("SELECT_PRIV");
                }
                if (!select) throw new SecurityException("SELECT-only account required");
            }
            try (var statement = connection.createStatement()) {
                for (String sql : List.of("SET enable_sql_cache=false", "SET enable_query_cache=false",
                        "SET query_timeout=60", "SET exec_mem_limit=2147483648")) statement.execute(sql);
                try (var rows = statement.executeQuery("SELECT COUNT(*) FROM newzl.data_snapshot_registry")) {
                    rows.next(); int count = rows.getInt(1);
                    report.put("registeredSnapshotsBefore", count);
                    if (count != 0) throw new IllegalStateException("Expected the unregistered diagnostic snapshot");
                }
            }
            for (var item : matrix.path("cases")) {
                String id = item.path("id").asText(), dsl = item.path("dsl").asText();
                var result = new LinkedHashMap<String, Object>();
                result.put("id", id); result.put("category", item.path("category").asText()); result.put("dsl", dsl);
                results.add(result);
                var samples = new ArrayList<Map<String, Object>>(); result.put("samples", samples);
                System.out.println("Starting " + id); System.out.flush();
                try {
                    var baseline = compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
                    var optimized = compiler.compileForSnapshot(dsl, matrix.path("snapshotId").asText());
                    Path folder = output.resolve(id); Files.createDirectories(folder);
                    artifact(folder, "baseline", baseline); artifact(folder, "optimized", optimized);
                    explain(connection, baseline, folder.resolve("baseline-explain.txt"));
                    explain(connection, optimized, folder.resolve("optimized-explain.txt"));
                    var expected = execute(connection, baseline).rows();
                    if (!expected.equals(execute(connection, optimized).rows())) throw new IllegalStateException("Warm-up results differ");
                    Files.writeString(folder.resolve("result-rows.json"), JsonSupport.MAPPER.writeValueAsString(expected) + "\n");
                    var baselineTimes = new ArrayList<Double>(); var optimizedTimes = new ArrayList<Double>();
                    for (int i = 0; i < iterations; i++) {
                        Execution b, o;
                        if (i % 2 == 0) { b = execute(connection, baseline); o = execute(connection, optimized); }
                        else { o = execute(connection, optimized); b = execute(connection, baseline); }
                        if (!expected.equals(b.rows()) || !expected.equals(o.rows()))
                            throw new IllegalStateException("Result/order mismatch at iteration " + (i + 1));
                        baselineTimes.add(b.millis()); optimizedTimes.add(o.millis());
                        samples.add(Map.of("iteration", i + 1, "order", i % 2 == 0 ? "baseline-first" : "optimized-first",
                            "baselineMillis", b.millis(), "optimizedMillis", o.millis(), "resultEqual", true));
                        if ((i + 1) % 5 == 0) { System.out.println(id + " " + (i + 1) + "/" + iterations); System.out.flush(); }
                    }
                    boolean same = baseline.sql().equals(optimized.sql()) && baseline.bindings().equals(optimized.bindings());
                    var bstats = stats(baselineTimes); var ostats = stats(optimizedTimes);
                    result.put("status", "PASS"); result.put("resultEqual", true); result.put("rows", expected.size());
                    result.put("resultSha256", sha(JsonSupport.MAPPER.writeValueAsBytes(expected)));
                    result.put("baseline", bstats); result.put("optimized", ostats); result.put("sameSql", same);
                    result.put("p95Ratio", bstats.get("p95Millis") / ostats.get("p95Millis"));
                    result.put("speedupInterpretation", same ? "IDENTICAL_SQL_NO_OPTIMIZATION_CLAIM" : "DIAGNOSTIC_ONLY");
                    System.out.printf(Locale.ROOT, "%s PASS rows=%d P95=%.3f/%.3fms ratio=%.3f%n", id, expected.size(),
                        bstats.get("p95Millis"), ostats.get("p95Millis"), bstats.get("p95Millis") / ostats.get("p95Millis"));
                } catch (Exception error) {
                    result.put("status", "FAIL"); result.put("error", error.getClass().getSimpleName() + ": " + error.getMessage());
                    System.out.println(id + " FAIL " + result.get("error"));
                }
                write(output, report);
            }
            try (var statement = connection.createStatement(); var rows = statement.executeQuery("SELECT COUNT(*) FROM newzl.data_snapshot_registry")) {
                rows.next(); report.put("registeredSnapshotsAfter", rows.getInt(1));
            }
        }
        report.put("completedAtUtc", Instant.now().toString());
        report.put("passed", results.stream().filter(r -> "PASS".equals(r.get("status"))).count());
        report.put("total", results.size()); write(output, report);
        if (results.stream().anyMatch(r -> !"PASS".equals(r.get("status")))) System.exit(1);
    }

    static Execution execute(Connection connection, StockSlotSqlArtifact artifact) throws Exception {
        long start = System.nanoTime(); var rows = new ArrayList<List<String>>();
        try (var statement = connection.prepareStatement(artifact.sql())) {
            statement.setQueryTimeout(60); bind(statement, artifact.bindings());
            try (var result = statement.executeQuery()) {
                while (result.next()) {
                    var row = new ArrayList<String>();
                    for (int i = 1; i <= result.getMetaData().getColumnCount(); i++) row.add(result.getString(i));
                    rows.add(row);
                }
            }
        }
        return new Execution((System.nanoTime() - start) / 1_000_000.0, rows);
    }
    static void bind(PreparedStatement statement, List<Object> bindings) throws Exception {
        for (int i = 0; i < bindings.size(); i++) {
            Object value = bindings.get(i);
            if (value instanceof LocalDate date) statement.setDate(i + 1, java.sql.Date.valueOf(date));
            else if (value instanceof BigDecimal number) statement.setBigDecimal(i + 1, number);
            else statement.setObject(i + 1, value);
        }
    }
    static void explain(Connection connection, StockSlotSqlArtifact artifact, Path path) throws Exception {
        var lines = new ArrayList<String>();
        try (var statement = connection.prepareStatement("EXPLAIN " + artifact.sql())) {
            bind(statement, artifact.bindings());
            try (var rows = statement.executeQuery()) { while (rows.next()) lines.add(rows.getString(1)); }
        }
        Files.write(path, lines, StandardCharsets.UTF_8);
    }
    static void artifact(Path folder, String name, StockSlotSqlArtifact artifact) throws Exception {
        Files.writeString(folder.resolve(name + ".sql"), artifact.sql() + "\n");
        Files.writeString(folder.resolve(name + "-bindings.json"), JsonSupport.MAPPER.writeValueAsString(artifact.bindings()) + "\n");
    }
    static Map<String, Double> stats(List<Double> samples) {
        var sorted = samples.stream().sorted().toList(); int size = sorted.size();
        return Map.of("p50Millis", sorted.get((int)Math.ceil(size * .5) - 1),
            "p95Millis", sorted.get((int)Math.ceil(size * .95) - 1), "minMillis", sorted.getFirst(), "maxMillis", sorted.getLast());
    }
    static String sha(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    static void write(Path output, Map<String, Object> report) throws Exception {
        Files.writeString(output.resolve("jdbc-results.json"), JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(report) + "\n");
    }
}
