package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.util.JsonSupport;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.*;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Reproducible full-scan-reference versus optimized matrix benchmark. */
public final class DorisBenchmarkMatrixRunner {
    public enum CacheMode { PROCESS_COLD, HOT }
    private final String jdbcUrl;
    private final String user;
    private final String password;
    private final StockSlotSqlCompiler compiler;

    public DorisBenchmarkMatrixRunner(String jdbcUrl, String user, String password, StockSlotRegistry registry) {
        this.jdbcUrl = Objects.requireNonNull(jdbcUrl);
        this.user = Objects.requireNonNull(user);
        this.password = Objects.requireNonNull(password);
        this.compiler = new StockSlotSqlCompiler(Objects.requireNonNull(registry));
    }

    public DorisBenchmarkMatrixReport run(DorisBenchmarkMatrixDefinition definition, int iterations,
                                           Path evidenceRoot, String coldRestartContainer) throws Exception {
        if (iterations < 30) throw new IllegalArgumentException("Matrix benchmark requires at least 30 iterations");
        if (coldRestartContainer == null || !coldRestartContainer.matches("[A-Za-z0-9_.-]+"))
            throw new IllegalArgumentException("A safe Docker container name is required for process-cold measurements");
        if (definition.cases().isEmpty()) throw new IllegalArgumentException("Benchmark matrix is empty");
        Files.createDirectories(evidenceRoot);
        try (var connection = open(CacheMode.HOT)) { requireSnapshot(connection, definition.snapshotId()); }

        List<DorisBenchmarkMatrixReport.CaseResult> results = new ArrayList<>();
        for (var item : definition.cases()) {
            var baseline = compiler.compile(item.dsl(), StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE);
            var optimized = compiler.compile(item.dsl(), StockSlotSqlCompiler.AccessPathMode.OPTIMIZED);
            for (var mode : CacheMode.values()) results.add(runCase(definition.snapshotId(), item, baseline,
                    optimized, mode, iterations, evidenceRoot, coldRestartContainer));
        }
        return new DorisBenchmarkMatrixReport(definition.matrixVersion(), definition.snapshotId(),
                DslCompiler.VERSION, iterations,
                "PROCESS_COLD restarts the single-node Doris container before every measured SQL; "
                        + "this clears FE/BE process caches but does not claim to clear the host OS page cache",
                results);
    }

    private DorisBenchmarkMatrixReport.CaseResult runCase(String snapshotId,
            DorisBenchmarkMatrixDefinition.CaseDefinition item, StockSlotSqlArtifact baseline,
            StockSlotSqlArtifact optimized, CacheMode mode, int iterations, Path root, String container) throws Exception {
        Path evidence = root.resolve(item.id()).resolve(mode.name().toLowerCase(Locale.ROOT));
        Files.createDirectories(evidence);
        Files.writeString(evidence.resolve("query.dsl"), item.dsl() + "\n", StandardCharsets.UTF_8);
        writeArtifact(evidence.resolve("baseline"), baseline);
        writeArtifact(evidence.resolve("optimized"), optimized);

        List<Double> baselineTimes = new ArrayList<>();
        List<Double> optimizedTimes = new ArrayList<>();
        List<Map<String, Object>> samples = new ArrayList<>();
        List<List<String>> expectedRows = null;

        if (mode == CacheMode.HOT) {
            try (var connection = open(mode)) {
                requireSnapshot(connection, snapshotId);
                writeExplain(connection, baseline, evidence.resolve("baseline-explain.txt"));
                writeExplain(connection, optimized, evidence.resolve("optimized-explain.txt"));
                execute(connection, baseline); execute(connection, optimized);
                for (int i = 0; i < iterations; i++) {
                    boolean reverse = (i & 1) == 1;
                    var first = execute(connection, reverse ? optimized : baseline);
                    var second = execute(connection, reverse ? baseline : optimized);
                    var b = reverse ? second : first; var o = reverse ? first : second;
                    expectedRows = compare(item.id(), expectedRows, b.rows(), o.rows());
                    baselineTimes.add(b.millis()); optimizedTimes.add(o.millis());
                    samples.add(sample(i + 1, b, o));
                }
            }
        } else {
            boolean explainsWritten = false;
            for (int i = 0; i < iterations; i++) {
                restart(container);
                Execution b;
                try (var connection = awaitConnection(mode)) {
                    requireSnapshot(connection, snapshotId);
                    if (!explainsWritten) writeExplain(connection, baseline, evidence.resolve("baseline-explain.txt"));
                    b = execute(connection, baseline);
                }
                restart(container);
                Execution o;
                try (var connection = awaitConnection(mode)) {
                    requireSnapshot(connection, snapshotId);
                    if (!explainsWritten) writeExplain(connection, optimized, evidence.resolve("optimized-explain.txt"));
                    o = execute(connection, optimized);
                }
                explainsWritten = true;
                expectedRows = compare(item.id(), expectedRows, b.rows(), o.rows());
                baselineTimes.add(b.millis()); optimizedTimes.add(o.millis());
                samples.add(sample(i + 1, b, o));
            }
        }
        Files.writeString(evidence.resolve("samples.json"),
                JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(samples) + "\n", StandardCharsets.UTF_8);
        var baseStats = stats(baselineTimes);
        var optStats = stats(optimizedTimes);
        double speed50 = baseStats.p50Millis() / optStats.p50Millis();
        double speed95 = baseStats.p95Millis() / optStats.p95Millis();
        return new DorisBenchmarkMatrixReport.CaseResult(item.id(), item.category(), mode.name(), true,
                expectedRows == null ? 0 : expectedRows.size(), baseStats, optStats, speed50, speed95,
                recommend(item.category(), speed95, baseline.sql().equals(optimized.sql())),
                fingerprint(baseline.sql()), fingerprint(optimized.sql()), root.relativize(evidence).toString());
    }

    private Connection open(CacheMode mode) throws SQLException {
        var connection = DriverManager.getConnection(jdbcUrl, user, password);
        try (var statement = connection.createStatement()) {
            statement.execute("SET enable_sql_cache=false");
            statement.execute("SET enable_query_cache=false");
            statement.execute("SET enable_profile=true");
            statement.execute("SET query_timeout=120");
            statement.execute("SET exec_mem_limit=2147483648");
        }
        verifyReadOnly(connection);
        return connection;
    }

    private Connection awaitConnection(CacheMode mode) throws Exception {
        SQLException last = null;
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(180);
        while (System.nanoTime() < deadline) {
            try {
                var connection = open(mode);
                try (var statement = connection.createStatement();
                     var result = statement.executeQuery("SELECT 1 FROM newzl.stock_daily_features_v2 LIMIT 1")) {
                    if (!result.next()) throw new SQLException("Doris BE readiness probe returned no row");
                }
                return connection;
            }
            catch (SQLException e) { last = e; Thread.sleep(1_000); }
        }
        throw new SQLException("Doris did not become ready after process-cold restart", last);
    }

    private void verifyReadOnly(Connection connection) throws SQLException {
        var grants = new StringBuilder();
        try (var statement = connection.createStatement(); var result = statement.executeQuery("SHOW GRANTS")) {
            while (result.next()) for (int i = 1; i <= result.getMetaData().getColumnCount(); i++)
                grants.append(' ').append(result.getString(i));
        }
        String value = grants.toString().toUpperCase(Locale.ROOT);
        if (!value.contains("SELECT_PRIV")) throw new SQLException("Benchmark account lacks SELECT_PRIV");
        for (String privilege : List.of("ADMIN_PRIV", "NODE_PRIV", "GRANT_PRIV", "LOAD_PRIV", "ALTER_PRIV", "CREATE_PRIV", "DROP_PRIV"))
            if (value.contains(privilege)) throw new SQLException("Benchmark account is not read-only: " + privilege);
    }

    private void restart(String container) throws Exception {
        var process = new ProcessBuilder("docker", "restart", container).redirectErrorStream(true).start();
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        if (!process.waitFor(180, TimeUnit.SECONDS) || process.exitValue() != 0)
            throw new IllegalStateException("Cold-cache Docker restart failed: " + output.strip());
    }

    private void requireSnapshot(Connection connection, String snapshot) throws SQLException {
        try (var statement = connection.prepareStatement("SELECT COUNT(*) FROM newzl.data_snapshot_registry "
                + "WHERE snapshot_id=? AND status='VALIDATED'")) {
            statement.setString(1, snapshot);
            try (var result = statement.executeQuery()) {
                if (!result.next() || result.getLong(1) != 1)
                    throw new IllegalStateException("Snapshot is not uniquely VALIDATED: " + snapshot);
            }
        }
    }

    private Execution execute(Connection connection, StockSlotSqlArtifact artifact) throws SQLException {
        long start = System.nanoTime();
        List<List<String>> rows = new ArrayList<>();
        try (var statement = connection.prepareStatement(artifact.sql())) {
            statement.setQueryTimeout(120); bind(statement, artifact.bindings());
            try (var result = statement.executeQuery()) {
                int count = result.getMetaData().getColumnCount();
                while (result.next()) {
                    List<String> row = new ArrayList<>(count);
                    for (int i = 1; i <= count; i++) row.add(result.getString(i));
                    rows.add(row);
                }
            }
        }
        double millis = (System.nanoTime() - start) / 1_000_000.0;
        String queryId = null;
        try (var statement = connection.createStatement(); var result = statement.executeQuery("SELECT LAST_QUERY_ID()")) {
            if (result.next()) queryId = result.getString(1);
        }
        return new Execution(millis, rows, queryId, profile(connection, queryId));
    }

    private Map<String, String> profile(Connection connection, String queryId) {
        Map<String, String> profile = new LinkedHashMap<>();
        profile.put("queryId", queryId);
        if (queryId == null) { profile.put("available", "false"); return profile; }
        for (int attempt = 0; attempt < 5; attempt++) {
            try (var statement = connection.createStatement(); var result = statement.executeQuery("SHOW QUERY PROFILE")) {
                var metadata = result.getMetaData();
                while (result.next()) {
                    if (!queryId.equalsIgnoreCase(column(result, metadata, "Profile ID"))) continue;
                    profile.put("available", "true");
                    for (String name : List.of("Task State", "Total", "User", "Start Time", "End Time"))
                        profile.put(name, column(result, metadata, name));
                    return profile;
                }
                Thread.sleep(100);
            } catch (SQLException e) {
                profile.put("error", e.getSQLState() + ":" + e.getErrorCode());
                break;
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                profile.put("error", "interrupted");
                break;
            }
        }
        profile.putIfAbsent("available", "false");
        return profile;
    }

    private void writeExplain(Connection connection, StockSlotSqlArtifact artifact, Path file) throws Exception {
        var lines = new ArrayList<String>();
        try (var statement = connection.prepareStatement("EXPLAIN " + artifact.sql())) {
            bind(statement, artifact.bindings());
            try (var result = statement.executeQuery()) {
                int count = result.getMetaData().getColumnCount();
                while (result.next()) {
                    var line = new StringJoiner(" | ");
                    for (int i = 1; i <= count; i++) line.add(String.valueOf(result.getString(i)));
                    lines.add(line.toString());
                }
            }
        }
        Files.write(file, lines, StandardCharsets.UTF_8);
    }

    private void writeArtifact(Path prefix, StockSlotSqlArtifact artifact) throws Exception {
        Files.writeString(Path.of(prefix + ".sql"), artifact.sql() + "\n", StandardCharsets.UTF_8);
        Files.writeString(Path.of(prefix + "-bindings.json"),
                JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(artifact.bindings()) + "\n",
                StandardCharsets.UTF_8);
    }

    private static List<List<String>> compare(String id, List<List<String>> expected,
                                               List<List<String>> baseline, List<List<String>> optimized) {
        if (!baseline.equals(optimized)) throw new IllegalStateException(id + ": optimized result differs from full-scan reference");
        if (expected != null && !expected.equals(baseline)) throw new IllegalStateException(id + ": result changed between iterations");
        return baseline;
    }

    static DorisBenchmarkMatrixReport.Stats stats(List<Double> input) {
        if (input.isEmpty()) throw new IllegalArgumentException("No samples");
        var values = input.stream().sorted().toList();
        return new DorisBenchmarkMatrixReport.Stats(percentile(values, .50), percentile(values, .95),
                values.getFirst(), values.getLast());
    }

    private static double percentile(List<Double> values, double p) {
        return values.get(Math.min(values.size() - 1, (int) Math.ceil(values.size() * p) - 1));
    }

    private static String recommend(String category, double speedup, boolean sameSql) {
        if (sameSql) return switch (category) {
            case "WINDOW" -> "优先建设窗口特征表/增量物化";
            case "CROSS_TABLE" -> "评估同粒度宽表或异步物化视图";
            case "RANK" -> "评估按日预排序特征";
            default -> "先检查分区裁剪、索引和谓词下推";
        };
        if (speedup < 1) return "优化回退：禁止上线并检查计划";
        if (speedup < 2) return "收益不足：保留参考路径并检查 Profile";
        return "候选有效：进入正确率回归和并发压测";
    }

    private static Map<String, Object> sample(int iteration, Execution baseline, Execution optimized) {
        return Map.of("iteration", iteration, "baselineMillis", baseline.millis(),
                "optimizedMillis", optimized.millis(), "baselineProfile", baseline.profile(),
                "optimizedProfile", optimized.profile());
    }

    private static String column(ResultSet result, ResultSetMetaData metadata, String wanted) throws SQLException {
        for (int i = 1; i <= metadata.getColumnCount(); i++)
            if (wanted.equalsIgnoreCase(metadata.getColumnLabel(i))) return result.getString(i);
        return null;
    }

    private static void bind(PreparedStatement statement, List<Object> bindings) throws SQLException {
        for (int i = 0; i < bindings.size(); i++) {
            Object value = bindings.get(i); int index = i + 1;
            if (value instanceof LocalDate date) statement.setDate(index, java.sql.Date.valueOf(date));
            else if (value instanceof BigDecimal number) statement.setBigDecimal(index, number);
            else if (value instanceof Integer number) statement.setInt(index, number);
            else if (value instanceof Long number) statement.setLong(index, number);
            else statement.setObject(index, value);
        }
    }

    private static String fingerprint(String sql) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(sql.replaceAll("\\s+", " ").trim()
                .getBytes(StandardCharsets.UTF_8));
        return "sha256:" + HexFormat.of().formatHex(hash);
    }

    private record Execution(double millis, List<List<String>> rows, String queryId, Map<String, String> profile) {}
}
