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
    private static final Pattern EXPLAIN_NODE = Pattern.compile(
            "^\\s*(?:\\|[- ]*)?\\d+:([A-Za-z][A-Za-z0-9_-]*)(?:\\(\\d+\\))?\\s*$");
    private static final Pattern EXPLAIN_NODE_CANDIDATE = Pattern.compile(
            "^\\s*[|+\\- ]*\\d");
    private static final Pattern EXPLAIN_LABEL = Pattern.compile("^\\s*[|+\\- ]*([^:\\r\\n]*):");
    private static final Set<String> EMPTY_SOURCE_WRAPPERS = Set.of(
            "VSORT", "VANALYTIC", "VPARTITIONTOPN", "VEXCHANGE", "VMERGING-EXCHANGE");
    private static final Set<String> EMPTY_PLAN_METADATA = Set.of(
            "OUTPUT EXPRS", "PARTITION", "HAS_COLO_PLAN_NODE", "ORDER BY", "PARTITION BY", "ALGORITHM", "OFFSET", "LIMIT",
            "FINAL PROJECTIONS", "FINAL PROJECT OUTPUT TUPLE ID", "INTERMEDIATE PROJECTIONS", "INTERMEDIATE TUPLE ID",
            "DISTRIBUTE EXPR LISTS", "FUNCTIONS", "WINDOW", "PREDICATES", "HAS GLOBAL LIMIT", "PARTITION LIMIT",
            "PARTITION TOPN PHASE", "EXCHANGE ID", "HASH_PARTITIONED", "IS_MERGE");
    private static final List<String> WRITE_PRIVILEGES = List.of(
            "ADMIN_PRIV", "NODE_PRIV", "GRANT_PRIV", "LOAD_PRIV", "ALTER_PRIV", "CREATE_PRIV", "DROP_PRIV");

    private final StockSlotSqlCompiler compiler;
    private final StockSlotRegistry registry;
    private final Connection connection;
    private final DorisExecutionPolicy policy;
    private final ReentrantLock executionSlot = new ReentrantLock(true);
    private final String fullScanBaselineSql;
    private final String snapshotRegistryTable;
    private final ProjectDataValidation projectValidation;

    public DorisQueryExecutor(String jdbcUrl, String user, String password, StockSlotRegistry registry) throws SQLException {
        this(jdbcUrl, user, password, registry, DorisExecutionPolicy.localBenchmarkDefaults());
    }

    public DorisQueryExecutor(String jdbcUrl, String user, String password, StockSlotRegistry registry,
                              DorisExecutionPolicy policy) throws SQLException {
        this(jdbcUrl, user, password, registry, policy, null);
    }

    public DorisQueryExecutor(String jdbcUrl, String user, String password, StockSlotRegistry registry,
                              DorisExecutionPolicy policy, ProjectDataValidation projectValidation) throws SQLException {
        Objects.requireNonNull(jdbcUrl, "jdbcUrl");
        Objects.requireNonNull(user, "user");
        Objects.requireNonNull(password, "password");
        Objects.requireNonNull(registry, "registry");
        this.policy = Objects.requireNonNull(policy, "policy");
        this.projectValidation = projectValidation;
        if (projectValidation != null) projectValidation.validateRegistry(registry);
        this.compiler = new StockSlotSqlCompiler(registry);
        this.registry = registry;
        var basic = registry.table("basic");
        this.snapshotRegistryTable = snapshotRegistryTable(basic.qualifiedName());
        var feature = registry.table("features");
        String close = registry.column("basic", "closePrice");
        String featureDate = "(SELECT MAX(" + registry.field("features", "tradeDate") + ") FROM "
                + feature.qualifiedName() + ")";
        this.fullScanBaselineSql = "WITH observed AS (SELECT "
                + registry.column("basic", "marketCode") + " AS mktcode,"
                + registry.column("basic", "securityCode") + " AS tgtcode,"
                + registry.column("basic", "tradeDate") + " AS bizdate," + close + " AS close_price FROM "
                + basic.qualifiedName() + " " + basic.alias() + " WHERE "
                + registry.column("basic", "marketCode") + "=1 AND "
                + registry.column("basic", "tradeDate") + " <= " + featureDate + "), windowed AS (SELECT observed.*, "
                + "CASE WHEN COUNT(close_price) OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)=60 "
                + "THEN AVG(close_price) OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) ELSE NULL END AS ma60 "
                + "FROM observed) SELECT mktcode,tgtcode FROM windowed WHERE bizdate=" + featureDate
                + " AND ma60>1 ORDER BY mktcode,tgtcode LIMIT 100";
        this.connection = DriverManager.getConnection(jdbcUrl, user, password);
        try {
            this.connection.setAutoCommit(true);
            configureSession();
            if (policy.requireReadOnlyAccount()) verifyReadOnlyAccount();
        } catch (SQLException | RuntimeException | Error failure) {
            try { this.connection.close(); }
            catch (SQLException closeFailure) { failure.addSuppressed(closeFailure); }
            throw failure;
        }
    }

    private void configureSession() throws SQLException {
        try (var statement = connection.createStatement()) {
            statement.execute("SET enable_sql_cache=false");
            statement.execute("SET enable_profile=true");
            // Leave process-memory headroom for diagnostics and allocator
            // retention in the owned four-core runtime. This changes only
            // scheduling, not window semantics or the memory/timeout budgets.
            statement.execute("SET parallel_pipeline_task_num=2");
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
        StockSlotSqlArtifact artifact = projectValidation == null ? compiler.compileForSnapshot(dsl, snapshotId)
                : compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
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
            long validationStart = System.nanoTime();
            var required = projectValidation == null ? Set.<String>of() : projectValidation.requiredSources(artifact);
            var snapshot = projectValidation == null ? requireValidatedSnapshot(snapshotId)
                    : projectValidation.verify(connection, snapshotId, required, timeoutSeconds);
            double sourceValidationMillis = millis(System.nanoTime() - validationStart);
            long explainStart = System.nanoTime();
            var explained = explain(artifact);
            double explainMillis = millis(System.nanoTime() - explainStart);
            if (explained.estimatedRows() < 0)
                throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT,
                        "Doris EXPLAIN did not expose a scan-row estimate; refusing uncontrolled execution");
            if (explained.estimatedRows() > policy.maxEstimatedScanRows())
                throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT,
                        "Estimated scan rows " + explained.estimatedRows() + " exceed limit " + policy.maxEstimatedScanRows());

            var quality = projectValidation == null ? null : assessCoverage(artifact, required, timeoutSeconds,
                    validationStart, sourceValidationMillis, explainMillis);

            List<String> columns = new ArrayList<>();
            List<List<String>> rows = new ArrayList<>();
            boolean truncated = false;
            long executeStart = System.nanoTime();
            double executionMillis;
            double returnMillis;
            String queryId;
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
                // Connector/J applies each SELECT's setMaxRows through a session
                // SET sql_select_limit. A default Statement would reset that
                // limit and overwrite Doris LAST_QUERY_ID before it is read.
                // Keep the same limit while the main statement is still open.
                queryId = lastQueryId(connection, timeoutSeconds, maxRows + 1);
            }
            var profile = profileSummary(connection, queryId, timeoutSeconds);
            double totalMillis = millis(System.nanoTime() - totalStart);
            return new DorisExecutionArtifact(artifact, columns, rows, truncated,
                    new DorisExecutionArtifact.Timings(compileMillis, queueMillis, explainMillis,
                            executionMillis, returnMillis, totalMillis),
                    new DorisExecutionArtifact.Limits(timeoutSeconds, policy.maxEstimatedScanRows(),
                            explained.estimatedRows(), maxRows, policy.maxExecutionMemoryBytes()),
                    fingerprint(artifact.sql()), snapshot, DslCompiler.VERSION, explained.lines(), profile, quality);
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

    private DorisExecutionArtifact.DataQuality assessCoverage(StockSlotSqlArtifact artifact, Set<String> required,
                                                               int timeout, long start, double sourceValidationMillis,
                                                               double mainExplainMillis) throws SQLException {
        var plan = artifact.coveragePlan();
        var coverageArtifact = new StockSlotSqlArtifact(artifact.dslVersion(), artifact.semanticModel(), List.of(), List.of(),
                plan.combinedSql(), plan.bindings(), false);
        validateGeneratedSelect(plan.combinedSql());
        long coverageExplainStart = System.nanoTime();
        var estimate = explain(coverageArtifact);
        double availabilityExplainMillis = millis(System.nanoTime() - coverageExplainStart);
        if (estimate.estimatedRows() < 0 || estimate.estimatedRows() > policy.maxEstimatedScanRows())
            throw new DorisExecutionException(DorisExecutionException.Category.SECURITY_LIMIT, "Availability scan exceeds controlled limits");
        long observed, missing;
        var inputs = new ArrayList<DorisExecutionArtifact.InputAvailability>();
        var samples = new ArrayList<List<String>>();
        long statisticsStart = System.nanoTime();
        try (var statement = connection.prepareStatement(plan.combinedSql())) {
            statement.setQueryTimeout(timeout); statement.setMaxRows(21); bind(statement, plan.bindings());
            try (var rows = statement.executeQuery()) {
                if (!rows.next()) throw new SQLException("Availability query returned no row");
                observed = rows.getLong(1); missing = rows.getLong(2);
                for (int i = 0; i < plan.inputs().size(); i++) {
                    var input = plan.inputs().get(i);
                    inputs.add(new DorisExecutionArtifact.InputAvailability(input.function(), input.indicator(), rows.getLong(i + 3),
                            input.inputId(), input.window(), input.role(), input.requiredObservations()));
                }
                int first = plan.inputs().size() + 3;
                int returned = 0;
                do {
                    if (++returned > 20) throw new SQLException("Availability query exceeded its bounded result");
                    boolean unavailable = false;
                    for (int i = first + 2; i <= rows.getMetaData().getColumnCount(); i++)
                        unavailable |= rows.getInt(i) == 1;
                    if (unavailable) {
                        var row = new ArrayList<String>();
                        for (int i = first; i <= rows.getMetaData().getColumnCount(); i++) row.add(rows.getString(i));
                        samples.add(row);
                    }
                } while (rows.next());
            }
        }
        double missingStatisticsMillis = millis(System.nanoTime() - statisticsStart);
        var limitations = new ArrayList<>(projectValidation.certificate().limitations());
        if (plan.inputs().stream().anyMatch(i -> i.function().endsWith("（窗口输入）")))
            limitations.add("CONS/EXIST 沿用冻结次数规则：NULL 条件不计为命中；完整观察行不足时次数结果为 NULL。另列的窗口输入检查会披露窗口内无法判定的条件，不改变次数计算结果。");
        long detailStart = System.nanoTime();
        var details = sampleDetails(artifact, samples, timeout);
        double sampleDetailsMillis = millis(System.nanoTime() - detailStart);
        limitations.add("可用性在用户条件、THEN 排名及 LIMIT 之前统计；输入为 NULL 不等于条件为假。各项缺失数量可能重叠，不可相加。样本最多 20 只；每个原因最多展示 20 个实际相关日期。每只证券最多检查 10001 条观察记录，每个输入最多 250000 步解释计算。历史不足只报告观察数，不推测缺少哪些交易日；平坦区间及零分母的相关日期不是缺失日期。跨证券查询、超限或检查失败会明确标记解释不完整，SQL 缺失标记保持有效。");
        return new DorisExecutionArtifact.DataQuality("PROJECT_SCOPED", false, projectValidation.certificateSha256(),
                observed == 0 ? "NO_OBSERVATIONS" : missing > 0 || inputs.stream().anyMatch(i -> i.unavailableSecurities() > 0)
                        ? "PARTIAL_INPUTS" : "COMPLETE_QUERY_INPUTS", plan.evaluationDate().toString(), List.copyOf(required),
                observed, missing, inputs, samples, projectValidation.certificate().extensionWithoutBasic(),
                projectValidation.certificate().closeOutsideRange(), limitations, millis(System.nanoTime() - start), details,
                new DorisExecutionArtifact.DiagnosticTimings(sourceValidationMillis, mainExplainMillis,
                        availabilityExplainMillis, missingStatisticsMillis, sampleDetailsMillis));
    }

    private List<StockSlotAvailabilityDiagnostics.SampleDetail> sampleDetails(StockSlotSqlArtifact artifact,
                                                                            List<List<String>> samples, int timeout) {
        if (samples.isEmpty()) return List.of();
        var coverage = artifact.coveragePlan();
        try {
            var fetch = StockSlotAvailabilityDiagnostics.fetchPlan(coverage, registry, samples);
            validateGeneratedSelect(fetch.sql());
            var estimate = explain(new StockSlotSqlArtifact(artifact.dslVersion(), artifact.semanticModel(), List.of(), List.of(),
                    fetch.sql(), fetch.bindings(), false));
            if (estimate.estimatedRows() < 0 || estimate.estimatedRows() > policy.maxEstimatedScanRows())
                return StockSlotAvailabilityDiagnostics.unavailable(coverage, samples, "DETAIL_SCAN_LIMIT");
            var evidence = new ArrayList<List<String>>();
            try (var statement = connection.prepareStatement(fetch.sql())) {
                statement.setQueryTimeout(timeout); statement.setMaxRows(fetch.maxRows() + 1); bind(statement, fetch.bindings());
                try (var rows = statement.executeQuery()) {
                    while (rows.next()) {
                        if (evidence.size() >= fetch.maxRows())
                            return StockSlotAvailabilityDiagnostics.unavailable(coverage, samples, "DETAIL_ROW_LIMIT");
                        var row = new ArrayList<String>();
                        for (int i = 1; i <= rows.getMetaData().getColumnCount(); i++)
                            row.add(Objects.requireNonNullElse(rows.getString(i), "NULL"));
                        evidence.add(row);
                    }
                }
            }
            return StockSlotAvailabilityDiagnostics.explain(coverage, registry, samples, fetch, evidence);
        } catch (SQLException e) {
            return StockSlotAvailabilityDiagnostics.unavailable(coverage, samples, "DETAIL_QUERY_UNAVAILABLE");
        } catch (RuntimeException e) {
            return StockSlotAvailabilityDiagnostics.unavailable(coverage, samples, StockSlotAvailabilityDiagnostics.failureCode(e));
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
        String sql = "SELECT snapshot_id,contract_version,manifest_sha256 FROM " + snapshotRegistryTable + " "
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

    /** Names have already passed the registry loader's identifier validation. */
    static String snapshotRegistryTable(String basicTable) {
        int separator = basicTable.indexOf('.');
        return separator < 0 ? "data_snapshot_registry"
                : basicTable.substring(0, separator) + ".data_snapshot_registry";
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

    static String lastQueryId(Connection connection, int timeoutSeconds, int sessionMaxRows) throws SQLException {
        try (var statement = connection.createStatement()) {
            statement.setQueryTimeout(timeoutSeconds);
            statement.setMaxRows(sessionMaxRows);
            try (var result = statement.executeQuery("SELECT LAST_QUERY_ID()")) {
                return result.next() ? result.getString(1) : null;
            }
        }
    }

    static DorisExecutionArtifact.QueryProfileSummary profileSummary(Connection connection, String queryId, int timeoutSeconds) {
        if (queryId == null || !queryId.matches("[0-9a-fA-F-]{16,80}"))
            return unavailableProfile(queryId, "LAST_QUERY_ID unavailable");
        try (var statement = connection.createStatement()) {
            statement.setQueryTimeout(timeoutSeconds);
            try (var result = statement.executeQuery("SHOW QUERY PROFILE")) {
                var metadata = result.getMetaData();
                // These headers are shared by the verified Doris 3.x/4.x layout.
                // Do not report success for an unknown or incomplete layout.
                for (String wanted : List.of("Profile ID", "Task State", "Total", "User"))
                    if (columnIndex(metadata, wanted) == 0)
                        return unavailableProfile(queryId, "Unsupported SHOW QUERY PROFILE layout");
                int inspected = 0;
                while (result.next() && inspected++ < 1_000) {
                    String id = column(result, metadata, "Profile ID");
                    if (!queryId.equalsIgnoreCase(id)) continue;
                    String state = column(result, metadata, "Task State");
                    String total = column(result, metadata, "Total");
                    String user = column(result, metadata, "User");
                    if (state == null || state.isBlank() || total == null || total.isBlank()
                            || user == null || user.isBlank())
                        return unavailableProfile(queryId, "Incomplete SHOW QUERY PROFILE summary");
                    return new DorisExecutionArtifact.QueryProfileSummary(true, queryId,
                            state, total, user, "Doris SHOW QUERY PROFILE summary");
                }
                return unavailableProfile(queryId, "Profile is asynchronous or not retained");
            }
        } catch (SQLException e) {
            return unavailableProfile(queryId, "Profile unavailable: " + safeMessage(e));
        }
    }

    private static String column(ResultSet result, ResultSetMetaData metadata, String wanted) throws SQLException {
        int index = columnIndex(metadata, wanted);
        return index == 0 ? null : result.getString(index);
    }

    private static int columnIndex(ResultSetMetaData metadata, String wanted) throws SQLException {
        for (int i = 1; i <= metadata.getColumnCount(); i++)
            if (wanted.equalsIgnoreCase(metadata.getColumnLabel(i))) return i;
        return 0;
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
        boolean hasEmptySet = false;
        boolean onlyEmptySourcesAndWrappers = true;
        for (String line : lines) {
            var matcher = EXPLAIN_ROWS.matcher(line);
            while (matcher.find()) estimate = Math.max(estimate,
                    Long.parseLong(matcher.group(1).replace(",", "")));
            var node = EXPLAIN_NODE.matcher(line);
            if (node.matches()) {
                String name = node.group(1).toUpperCase(Locale.ROOT);
                boolean empty = name.equals("VEMPTYSET") || name.equals("EMPTYSET");
                hasEmptySet |= empty;
                onlyEmptySourcesAndWrappers &= empty || EMPTY_SOURCE_WRAPPERS.contains(name);
            } else {
                var label = EXPLAIN_LABEL.matcher(line);
                // Unknown colon headers are suspicious even if the identifier is
                // non-numeric and the operator has no V prefix. Only exact known
                // EXPLAIN attribute labels are metadata, never operator prefixes.
                if (EXPLAIN_NODE_CANDIDATE.matcher(line).find()
                        || (label.find() && !EMPTY_PLAN_METADATA.contains(label.group(1).strip().toUpperCase(Locale.ROOT))))
                    onlyEmptySourcesAndWrappers = false;
            }
        }
        // Doris can retain pure ranking/window/sort/exchange wrappers after replacing
        // every data source with EMPTYSET. These exact unary operators cannot read
        // another source. Do not extend this proof to joins, unions, table functions,
        // unknown names or malformed node headers. Execution and its limits remain
        // unchanged: zero is a scan estimate, not a synthesized empty query result.
        if (estimate < 0 && hasEmptySet && onlyEmptySourcesAndWrappers) return 0;
        return estimate;
    }

    private static double millis(long nanos) { return nanos / 1_000_000.0; }
    private record Explained(long estimatedRows, List<String> lines) {}

    @Override public void close() throws SQLException { connection.close(); }
}
