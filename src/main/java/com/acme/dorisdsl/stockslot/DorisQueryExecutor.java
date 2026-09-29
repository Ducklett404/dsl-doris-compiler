package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.DslCompiler;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.*;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;
import java.util.regex.Pattern;

/** Controlled execution of parameterized SELECT statements emitted by {@link StockSlotSqlCompiler}. */
public final class DorisQueryExecutor implements AutoCloseable {
    public static final int MAX_TIMEOUT_SECONDS = 10;
    private static final Pattern EXPLAIN_ROWS = Pattern.compile(
            "(?i)(?:cardinality|rowcount|rows|estimated rows)\\s*[:=]\\s*([0-9][0-9,]*)");
    private static final List<String> WRITE_PRIVILEGES = List.of(
            "ADMIN_PRIV", "NODE_PRIV", "GRANT_PRIV", "LOAD_PRIV", "ALTER_PRIV", "CREATE_PRIV", "DROP_PRIV");

    private final StockSlotSqlCompiler compiler;
    private final Connection connection;
    private final DorisExecutionPolicy policy;
    private final ReentrantLock executionSlot = new ReentrantLock(true);
    private final String fullScanBaselineSql;

    public DorisQueryExecutor(String jdbcUrl, String user, String password, StockSlotRegistry registry) throws SQLException {
        this(jdbcUrl, user, password, registry, DorisExecutionPolicy.localBenchmarkDefaults());
    }

    public DorisQueryExecutor(String jdbcUrl, String user, String password, StockSlotRegistry registry,
                              DorisExecutionPolicy policy) throws SQLException {
        Objects.requireNonNull(jdbcUrl, "jdbcUrl");
        Objects.requireNonNull(user, "user");
        Objects.requireNonNull(password, "password");
        Objects.requireNonNull(registry, "registry");
        this.policy = Objects.requireNonNull(policy, "policy");
        this.compiler = new StockSlotSqlCompiler(registry);
        var basic = registry.table("basic");
        var feature = registry.table("features");
        String close = registry.column("basic", "closePrice");
        String featureDate = "(SELECT MAX(" + registry.field("features", "tradeDate") + ") FROM "
                + feature.qualifiedName() + ")";
        this.fullScanBaselineSql = "WITH observed AS (SELECT "
                + registry.column("basic", "marketCode") + " AS mktcode,"
                + registry.column("basic", "securityCode") + " AS tgtcode,"
                + registry.column("basic", "tradeDate") + " AS bizdate," + close + " AS close_price FROM "
                + basic.qualifiedName() + " " + basic.alias() + " WHERE " + close + " IS NOT NULL AND "
                + registry.column("basic", "marketCode") + "=1 AND "
                + registry.column("basic", "tradeDate") + " <= " + featureDate + "), windowed AS (SELECT observed.*, "
                + "CASE WHEN COUNT(close_price) OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)=60 "
                + "THEN AVG(close_price) OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) ELSE NULL END AS ma60 "
                + "FROM observed) SELECT mktcode,tgtcode FROM windowed WHERE bizdate=" + featureDate
                + " AND ma60>1 ORDER BY mktcode,tgtcode LIMIT 100";
        this.connection = DriverManager.getConnection(jdbcUrl, user, password);
        this.connection.setAutoCommit(true);
        configureSession();
        if (policy.requireReadOnlyAccount()) verifyReadOnlyAccount();
    }

    private void configureSession() throws SQLException {
        try (var statement = connection.createStatement()) {
            statement.execute("SET enable_sql_cache=false");
            statement.execute("SET enable_profile=true");
            statement.execute("SET query_timeout=" + policy.queryTimeoutSeconds());
            statement.execute("SET exec_mem_limit=" + policy.maxExecutionMemoryBytes());
        }
    }

    private void verifyReadOnlyAccount() throws SQLException {
        var grants = new StringBuilder();
        try (var statement = connection.createStatement(); var result = statement.executeQuery("SHOW GRANTS")) {
            while (result.next()) for (int i = 1; i <= result.getMetaData().getColumnCount(); i++)
                grants.append(' ').append(result.getString(i));
        }
        String normalized = grants.toString().toUpperCase(Locale.ROOT);
        if (!normalized.contains("SELECT_PRIV"))
            throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT,
                    "Doris execution account has no explicit SELECT_PRIV grant");
        for (String privilege : WRITE_PRIVILEGES) if (normalized.contains(privilege))
            throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT,
                    "Doris execution account is not read-only (contains " + privilege + ")");
    }

    public DorisExecutionArtifact execute(String dsl, int timeoutSeconds, int maxRows) {
        return execute(dsl, "stock-20060104-20260414-v1", timeoutSeconds, maxRows);
    }

    public DorisExecutionArtifact execute(String dsl, String snapshotId, int timeoutSeconds, int requestedMaxRows) {
        long totalStart = System.nanoTime();
        if (timeoutSeconds < 1 || timeoutSeconds > policy.queryTimeoutSeconds())
            throw new IllegalArgumentException("timeoutSeconds must be 1.." + policy.queryTimeoutSeconds());
        int maxRows = requestedMaxRows <= 0 ? policy.maxReturnRows() : Math.min(requestedMaxRows, policy.maxReturnRows());

        long compileStart = System.nanoTime();
        StockSlotSqlArtifact artifact = compiler.compile(dsl);
        double compileMillis = millis(System.nanoTime() - compileStart);
        validateGeneratedSelect(artifact.sql());

        long queueStart = System.nanoTime();
        boolean locked;
        try {
            locked = executionSlot.tryLock(policy.maxQueueWaitMillis(), TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new DorisExecutionException(DorisExecutionException.Category.TIMEOUT, "Interrupted while waiting for execution slot", e);
        }
        double queueMillis = millis(System.nanoTime() - queueStart);
        if (!locked) throw new DorisExecutionException(DorisExecutionException.Category.TIMEOUT,
                "Execution queue wait exceeded " + policy.maxQueueWaitMillis() + " ms");

        try {
            var snapshot = requireValidatedSnapshot(snapshotId);
            long explainStart = System.nanoTime();
            var explained = explain(artifact);
            double explainMillis = millis(System.nanoTime() - explainStart);
            if (explained.estimatedRows() < 0)
                throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT,
                        "Doris EXPLAIN did not expose a scan-row estimate; refusing uncontrolled execution");
            if (explained.estimatedRows() > policy.maxEstimatedScanRows())
                throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT,
                        "Estimated scan rows " + explained.estimatedRows() + " exceed limit " + policy.maxEstimatedScanRows());

            List<String> columns = new ArrayList<>();
            List<List<String>> rows = new ArrayList<>();
            boolean truncated = false;
            long executeStart = System.nanoTime();
            double executionMillis;
            double returnMillis;
            try (PreparedStatement statement = connection.prepareStatement(artifact.sql())) {
                statement.setQueryTimeout(timeoutSeconds);
                statement.setMaxRows(maxRows + 1);
                bind(statement, artifact.bindings());
                try (ResultSet result = statement.executeQuery()) {
                    executionMillis = millis(System.nanoTime() - executeStart);
                    long returnStart = System.nanoTime();
                    ResultSetMetaData metadata = result.getMetaData();
                    for (int i = 1; i <= metadata.getColumnCount(); i++) columns.add(metadata.getColumnLabel(i));
                    while (result.next()) {
                        if (rows.size() >= maxRows) { truncated = true; break; }
                        List<String> row = new ArrayList<>(metadata.getColumnCount());
                        for (int i = 1; i <= metadata.getColumnCount(); i++) row.add(result.getString(i));
                        rows.add(row);
                    }
                    returnMillis = millis(System.nanoTime() - returnStart);
                }
            }
            String queryId = lastQueryId();
            var profile = profileSummary(queryId);
            double totalMillis = millis(System.nanoTime() - totalStart);
            return new DorisExecutionArtifact(artifact, columns, rows, truncated,
                    new DorisExecutionArtifact.Timings(compileMillis, queueMillis, explainMillis,
                            executionMillis, returnMillis, totalMillis),
                    new DorisExecutionArtifact.Limits(timeoutSeconds, policy.maxEstimatedScanRows(),
                            explained.estimatedRows(), maxRows, policy.maxExecutionMemoryBytes()),
                    fingerprint(artifact.sql()), snapshot, DslCompiler.VERSION, explained.lines(), profile);
        } catch (SQLTimeoutException e) {
            throw new DorisExecutionException(DorisExecutionException.Category.TIMEOUT, "Doris query timed out", e);
        } catch (SQLException e) {
            if (isTimeout(e)) throw new DorisExecutionException(DorisExecutionException.Category.TIMEOUT, "Doris query timed out", e);
            throw new DorisExecutionException(DorisExecutionException.Category.DORIS_ERROR,
                    "Doris rejected controlled query; code " + e.getErrorCode()
                            + " (SQLState " + e.getSQLState() + ")", e);
        } finally {
            executionSlot.unlock();
        }
    }

    private Explained explain(StockSlotSqlArtifact artifact) throws SQLException {
        List<String> lines = new ArrayList<>();
        try (PreparedStatement statement = connection.prepareStatement("EXPLAIN " + artifact.sql())) {
            statement.setQueryTimeout(policy.queryTimeoutSeconds());
            bind(statement, artifact.bindings());
            try (ResultSet result = statement.executeQuery()) {
                var metadata = result.getMetaData();
                while (result.next() && lines.size() < 200) {
                    var line = new StringBuilder();
                    for (int i = 1; i <= metadata.getColumnCount(); i++) {
                        if (i > 1) line.append(" | ");
                        line.append(result.getString(i));
                    }
                    String value = line.length() > 2_000 ? line.substring(0, 2_000) : line.toString();
                    lines.add(value);
                }
            }
        }
        return new Explained(parseEstimatedRows(lines), lines);
    }

    public void ping() throws SQLException {
        try (var statement = connection.createStatement(); var result = statement.executeQuery("SELECT 1")) {
            if (!result.next() || result.getInt(1) != 1) throw new SQLException("Doris ping returned an unexpected result");
        }
    }

    public DorisExecutionArtifact.SnapshotVersion requireValidatedSnapshot(String snapshotId) throws SQLException {
        if (snapshotId == null || snapshotId.isBlank()) throw new IllegalArgumentException("snapshotId is required");
        String sql = "SELECT snapshot_id,contract_version,manifest_sha256 FROM newzl.data_snapshot_registry "
                + "WHERE snapshot_id=? AND status='VALIDATED'";
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, snapshotId);
            try (ResultSet result = statement.executeQuery()) {
                if (!result.next()) throw new DorisExecutionException(DorisExecutionException.Category.DATA_UNAVAILABLE,
                        "Required VALIDATED Doris snapshot is not registered: " + snapshotId);
                var version = new DorisExecutionArtifact.SnapshotVersion(result.getString(1), result.getString(2), result.getString(3));
                if (result.next()) throw new DorisExecutionException(DorisExecutionException.Category.DATA_UNAVAILABLE,
                        "Snapshot registry is ambiguous: " + snapshotId);
                return version;
            }
        }
    }

    /** Fixed, read-only baseline that scans the complete 19-year semantic quote view. */
    public BaselineMeasurement measureFullScanBaseline(int timeoutSeconds) throws SQLException {
        if (timeoutSeconds < 1 || timeoutSeconds > 120)
            throw new IllegalArgumentException("baseline timeoutSeconds must be 1..120");
        long start = System.nanoTime();
        List<List<String>> rows = new ArrayList<>();
        try (var statement = connection.createStatement()) {
            statement.setQueryTimeout(timeoutSeconds);
            try (var result = statement.executeQuery(fullScanBaselineSql)) {
                if (!result.next()) throw new SQLException("Full-scan baseline returned no row");
                do { rows.add(List.of(result.getString(1), result.getString(2))); } while (result.next());
            }
        }
        return new BaselineMeasurement(millis(System.nanoTime() - start), rows);
    }

    public record BaselineMeasurement(double millis, List<List<String>> rows) {
        public BaselineMeasurement { rows = rows.stream().map(List::copyOf).toList(); }
    }

    private String lastQueryId() throws SQLException {
        try (var statement = connection.createStatement(); var result = statement.executeQuery("SELECT LAST_QUERY_ID()")) {
            return result.next() ? result.getString(1) : null;
        }
    }

    private DorisExecutionArtifact.QueryProfileSummary profileSummary(String queryId) {
        if (queryId == null || !queryId.matches("[0-9a-fA-F-]{16,80}"))
            return unavailableProfile(queryId, "LAST_QUERY_ID unavailable");
        try (var statement = connection.createStatement(); var result = statement.executeQuery("SHOW QUERY PROFILE")) {
            var metadata = result.getMetaData();
            while (result.next()) {
                String id = column(result, metadata, "Profile ID");
                if (!queryId.equalsIgnoreCase(id)) continue;
                return new DorisExecutionArtifact.QueryProfileSummary(true, queryId,
                        column(result, metadata, "Task State"), column(result, metadata, "Total"),
                        column(result, metadata, "User"), "Doris SHOW QUERY PROFILE summary");
            }
            return unavailableProfile(queryId, "Profile is asynchronous or not retained");
        } catch (SQLException e) {
            return unavailableProfile(queryId, "Profile unavailable: " + safeMessage(e));
        }
    }

    private static String column(ResultSet result, ResultSetMetaData metadata, String wanted) throws SQLException {
        for (int i = 1; i <= metadata.getColumnCount(); i++)
            if (wanted.equalsIgnoreCase(metadata.getColumnLabel(i))) return result.getString(i);
        return null;
    }

    private static DorisExecutionArtifact.QueryProfileSummary unavailableProfile(String id, String note) {
        return new DorisExecutionArtifact.QueryProfileSummary(false, id, null, null, null, note);
    }

    private void bind(PreparedStatement statement, List<Object> bindings) throws SQLException {
        for (int i = 0; i < bindings.size(); i++) {
            Object value = bindings.get(i);
            int index = i + 1;
            if (value instanceof LocalDate date) statement.setDate(index, java.sql.Date.valueOf(date));
            else if (value instanceof BigDecimal decimal) statement.setBigDecimal(index, decimal);
            else if (value instanceof Integer integer) statement.setInt(index, integer);
            else if (value instanceof Long number) statement.setLong(index, number);
            else if (value instanceof Boolean bool) statement.setBoolean(index, bool);
            else statement.setObject(index, value);
        }
    }

    private static void validateGeneratedSelect(String sql) {
        String normalized = sql.stripLeading().toUpperCase(Locale.ROOT);
        String withoutFinalTerminator = sql.stripTrailing().replaceFirst(";$", "");
        if (!(normalized.startsWith("SELECT ") || normalized.startsWith("WITH "))
                || withoutFinalTerminator.contains(";") || normalized.contains("--") || normalized.contains("/*"))
            throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT,
                    "Only one compiler-generated SELECT is executable");
    }

    private static String fingerprint(String sql) {
        try {
            String normalized = sql.replaceAll("\\s+", " ").trim();
            return "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(normalized.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private static boolean isTimeout(SQLException e) {
        String state = e.getSQLState();
        String message = e.getMessage() == null ? "" : e.getMessage().toLowerCase(Locale.ROOT);
        return (state != null && state.startsWith("HYT")) || message.contains("timeout") || message.contains("timed out");
    }

    private static String safeMessage(SQLException e) {
        String message = e.getMessage();
        return message == null ? "unspecified database failure" : message.replaceAll("[\\r\\n]+", " ");
    }

    static long parseEstimatedRows(List<String> lines) {
        long estimate = -1;
        for (String line : lines) {
            var matcher = EXPLAIN_ROWS.matcher(line);
            while (matcher.find()) estimate = Math.max(estimate,
                    Long.parseLong(matcher.group(1).replace(",", "")));
        }
        return estimate;
    }

    private static double millis(long nanos) { return nanos / 1_000_000.0; }
    private record Explained(long estimatedRows, List<String> lines) {}

    @Override public void close() throws SQLException { connection.close(); }
}
