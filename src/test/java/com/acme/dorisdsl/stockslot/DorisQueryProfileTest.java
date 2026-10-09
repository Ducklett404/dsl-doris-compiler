package com.acme.dorisdsl.stockslot;

import org.junit.jupiter.api.Test;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.sql.*;
import java.util.*;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.*;

final class DorisQueryProfileTest {
    private static final String ID = "1234567890abcdef-1234567890abcdef";
    private static final List<String> HEADERS = List.of("Profile ID", "Task State", "Total", "User");

    @Test void executorCapturesMainIdAfterResultCloseBeforeMainStatementClose() throws Exception {
        try (var driver = new ProfileDriver();
             var executor = new DorisQueryExecutor(driver.url, "reader", "unused",
                     new StockSlotRegistryLoader().loadDefault(),
                     new DorisExecutionPolicy(10, 10000, 20, 128L << 20, 500, true))) {
            var result = executor.execute("indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1",
                    "test-snapshot", 10, 20);
            assertTrue(result.queryProfile().available());
            assertEquals(ID, result.queryProfile().queryId());
            assertEquals("OK", result.queryProfile().taskState());
            assertEquals("7ms", result.queryProfile().total());
            assertEquals(List.of("result-close", "id-query", "main-close", "profile-query"), driver.events);
            assertEquals(21, driver.idMaxRows);
            assertEquals(10, driver.idTimeout);
        }
    }

    @Test void idCapturePreservesLimitAndClosesItsResources() throws Exception {
        try (var driver = new ProfileDriver()) {
            assertEquals(ID, DorisQueryExecutor.lastQueryId(driver.connection(), 3, 8));
            assertEquals(8, driver.idMaxRows);
            assertEquals(3, driver.idTimeout);
            assertTrue(driver.idResultClosed);
            assertTrue(driver.idStatementClosed);
        }
    }

    @Test void idFailureStillClosesStatement() throws Exception {
        try (var driver = new ProfileDriver()) {
            driver.idFailure = true;
            assertThrows(SQLException.class, () -> DorisQueryExecutor.lastQueryId(driver.connection(), 3, 8));
            assertTrue(driver.idStatementClosed);
        }
    }

    @Test void profileMatchesExactIdAndPopulatesVerifiedHeaders() throws Exception {
        try (var driver = new ProfileDriver()) {
            driver.profiles = List.of(List.of("ffffffffffffffff-ffffffffffffffff", "OK", "1ms", "other"),
                    List.of(ID.toUpperCase(Locale.ROOT), "OK", "7ms", "reader"));
            var profile = DorisQueryExecutor.profileSummary(driver.connection(), ID, 4);
            assertTrue(profile.available());
            assertEquals("reader", profile.user());
            assertEquals(4, driver.profileTimeout);
            assertTrue(driver.profileResultClosed);
            assertTrue(driver.profileStatementClosed);
        }
    }

    @Test void unknownLayoutDoesNotClaimAvailable() throws Exception {
        try (var driver = new ProfileDriver()) {
            driver.headers = List.of("Query ID", "State", "Elapsed", "Account");
            var profile = DorisQueryExecutor.profileSummary(driver.connection(), ID, 4);
            assertFalse(profile.available());
            assertTrue(profile.note().contains("Unsupported"));
        }
    }

    @Test void incompleteKnownLayoutDoesNotClaimAvailable() throws Exception {
        try (var driver = new ProfileDriver()) {
            driver.profiles = List.of(Arrays.asList(ID, "OK", null, "reader"));
            var profile = DorisQueryExecutor.profileSummary(driver.connection(), ID, 4);
            assertFalse(profile.available());
            assertTrue(profile.note().contains("Incomplete"));
        }
    }

    @Test void invalidIdDoesNotExecuteSql() throws Exception {
        try (var driver = new ProfileDriver()) {
            assertFalse(DorisQueryExecutor.profileSummary(driver.connection(), "'; DROP TABLE t", 4).available());
            assertEquals(0, driver.profileQueries);
        }
    }

    @Test void absentProfileRemainsExplicitlyUnavailable() throws Exception {
        try (var driver = new ProfileDriver()) {
            driver.profiles = List.of();
            var profile = DorisQueryExecutor.profileSummary(driver.connection(), ID, 4);
            assertFalse(profile.available());
            assertEquals(ID, profile.queryId());
            assertTrue(profile.note().contains("asynchronous"));
        }
    }

    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler));
    }

    private static final class ProfileDriver implements Driver, AutoCloseable {
        final String url = "jdbc:profile-test:" + UUID.randomUUID();
        final List<String> events = new ArrayList<>();
        List<String> headers = HEADERS;
        List<List<String>> profiles = List.of(List.of(ID, "OK", "7ms", "reader"));
        boolean mainStarted, mainResultClosed, mainClosed, idFailure;
        boolean idResultClosed, idStatementClosed, profileResultClosed, profileStatementClosed;
        int idMaxRows, idTimeout, profileTimeout, profileQueries;

        ProfileDriver() throws SQLException { DriverManager.registerDriver(this); }

        Connection connection() {
            return proxy(Connection.class, (object, method, args) -> switch (method.getName()) {
                case "close", "setAutoCommit" -> null;
                case "createStatement" -> statement();
                case "prepareStatement" -> prepared((String) args[0]);
                default -> throw new UnsupportedOperationException(method.getName());
            });
        }

        Statement statement() {
            var values = new int[2];
            var kind = new String[]{""};
            return proxy(Statement.class, (object, method, args) -> switch (method.getName()) {
                case "setMaxRows" -> { values[0] = (int) args[0]; yield null; }
                case "setQueryTimeout" -> { values[1] = (int) args[0]; yield null; }
                case "execute" -> true;
                case "close" -> {
                    if (kind[0].equals("id")) idStatementClosed = true;
                    if (kind[0].equals("profile")) profileStatementClosed = true;
                    yield null;
                }
                case "executeQuery" -> {
                    String sql = (String) args[0];
                    if (sql.equals("SHOW GRANTS")) yield result(List.of("grants"), List.of(List.of("SELECT_PRIV")), () -> {});
                    if (sql.equals("SELECT LAST_QUERY_ID()")) {
                        kind[0] = "id"; idMaxRows = values[0]; idTimeout = values[1];
                        if (mainStarted) { assertTrue(mainResultClosed); assertFalse(mainClosed); events.add("id-query"); }
                        if (idFailure) throw new SQLException("ID read failed");
                        yield result(List.of("id"), List.of(List.of(ID)), () -> idResultClosed = true);
                    }
                    if (sql.equals("SHOW QUERY PROFILE")) {
                        kind[0] = "profile"; profileQueries++; profileTimeout = values[1];
                        if (mainStarted) { assertTrue(mainClosed); events.add("profile-query"); }
                        yield result(headers, profiles, () -> profileResultClosed = true);
                    }
                    throw new UnsupportedOperationException(sql);
                }
                default -> throw new UnsupportedOperationException(method.getName());
            });
        }

        PreparedStatement prepared(String sql) {
            boolean main = !sql.startsWith("SELECT snapshot_id") && !sql.startsWith("EXPLAIN ");
            return proxy(PreparedStatement.class, (object, method, args) -> switch (method.getName()) {
                case "setQueryTimeout", "setMaxRows", "setString", "setDate", "setBigDecimal", "setObject", "setInt", "setLong", "setBoolean" -> null;
                case "close" -> { if (main) { mainClosed = true; events.add("main-close"); } yield null; }
                case "executeQuery" -> {
                    if (sql.startsWith("SELECT snapshot_id"))
                        yield result(List.of("snapshot_id", "contract_version", "manifest_sha256"),
                                List.of(List.of("test-snapshot", "v1", "hash")), () -> {});
                    if (sql.startsWith("EXPLAIN "))
                        yield result(List.of("plan"), List.of(List.of("cardinality=4")), () -> {});
                    mainStarted = true;
                    yield result(List.of("mktcode", "tgtcode"), List.of(List.of("1", "000001")),
                            () -> { mainResultClosed = true; events.add("result-close"); });
                }
                default -> throw new UnsupportedOperationException(method.getName());
            });
        }

        ResultSet result(List<String> columns, List<List<String>> rows, Runnable close) {
            var current = new int[]{-1};
            return proxy(ResultSet.class, (object, method, args) -> switch (method.getName()) {
                case "close" -> { close.run(); yield null; }
                case "next" -> ++current[0] < rows.size();
                case "getString" -> rows.get(current[0]).get((int) args[0] - 1);
                case "getMetaData" -> proxy(ResultSetMetaData.class, (metadata, property, index) -> switch (property.getName()) {
                    case "getColumnCount" -> columns.size();
                    case "getColumnLabel" -> columns.get((int) index[0] - 1);
                    default -> throw new UnsupportedOperationException(property.getName());
                });
                default -> throw new UnsupportedOperationException(method.getName());
            });
        }

        @Override public Connection connect(String candidate, Properties properties) { return acceptsURL(candidate) ? connection() : null; }
        @Override public boolean acceptsURL(String candidate) { return url.equals(candidate); }
        @Override public DriverPropertyInfo[] getPropertyInfo(String url, Properties info) { return new DriverPropertyInfo[0]; }
        @Override public int getMajorVersion() { return 1; }
        @Override public int getMinorVersion() { return 0; }
        @Override public boolean jdbcCompliant() { return false; }
        @Override public Logger getParentLogger() { return Logger.getGlobal(); }
        @Override public void close() throws SQLException { DriverManager.deregisterDriver(this); }
    }
}
