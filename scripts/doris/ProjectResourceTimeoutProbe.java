import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import java.lang.reflect.*;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.logging.Logger;

/** Test-only delayed transport: actual JDBC timeout followed by the same executor's real query. */
class ProjectResourceTimeoutProbe {
    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--self-check")) {
            System.out.println("{\"status\":\"COMPILE_ONLY\",\"nativeRuntime\":\"NOT_RUN\"}");
            return;
        }
        if (args.length == 1 && args[0].equals("--driver-self-check")) {
            verifyDriverVisibility();
            return;
        }
        if (args.length != 5) throw new IllegalArgumentException("Expected JDBC URL, user, registry, certificate and DSL file");
        var registry = new StockSlotRegistryLoader().load(Path.of(args[2]));
        var validation = ProjectDataValidation.load(Path.of(args[3]), registry);
        String dsl = Files.readString(Path.of(args[4]));
        try (var driver = new SlowOnceDriver(args[0]);
             var executor = new DorisQueryExecutor(driver.url, args[1], System.getenv("DSL_PROJECT_PASSWORD"), registry,
                 new DorisExecutionPolicy(10,100000000,10000,2147483648L,10000,true), validation)) {
            DorisExecutionException failure = null;
            try { executor.execute(dsl, validation.certificate().snapshotId(), 1, 10000); }
            catch (DorisExecutionException error) { failure = error; }
            if (failure == null || failure.category() != DorisExecutionException.Category.TIMEOUT || !driver.reached.get())
                throw new AssertionError("Expected actual JDBC slow-control timeout after executor admission");
            var recovery = executor.execute(dsl, validation.certificate().snapshotId(), 10, 10000);
            System.out.println(JsonSupport.MAPPER.writeValueAsString(Map.of(
                "status", "PASS", "controlQuery", "SELECT SLEEP(4)", "jdbcTimeoutSeconds", 1,
                "actualSlowQueryReached", driver.reached.get(), "timeoutCategory", failure.category().name(),
                "recovery", recovery)));
        }
    }

    /** Registration and loader checks only: deliberately never opens a JDBC connection. */
    private static void verifyDriverVisibility() throws Exception {
        try (var driver = new SlowOnceDriver("jdbc:project-resource-unused:self-check")) {
            boolean executorClassLoaderVisible;
            try {
                executorClassLoaderVisible = Class.forName(SlowOnceDriver.class.getName(), false,
                    DorisQueryExecutor.class.getClassLoader()) == SlowOnceDriver.class;
            } catch (ClassNotFoundException error) {
                executorClassLoaderVisible = false;
            }
            boolean driverManagerVisible;
            try {
                driverManagerVisible = DriverManager.getDriver(driver.url) == driver;
            } catch (SQLException error) {
                driverManagerVisible = false;
            }
            boolean passed = executorClassLoaderVisible && driverManagerVisible;
            System.out.println(JsonSupport.MAPPER.writeValueAsString(Map.of(
                "status", passed ? "PASS" : "FAIL",
                "executorClassLoaderVisible", executorClassLoaderVisible,
                "driverManagerVisible", driverManagerVisible,
                "driverClassLoader", SlowOnceDriver.class.getClassLoader().getClass().getName(),
                "executorClassLoader", DorisQueryExecutor.class.getClassLoader().getClass().getName(),
                "nativeRuntime", "NOT_RUN")));
            if (!passed) throw new AssertionError("Timeout control driver is not visible to the executor class loader");
        }
    }

    private static final class SlowOnceDriver implements Driver, AutoCloseable {
        final String url = "jdbc:project-resource-control:" + UUID.randomUUID();
        final String delegate;
        final AtomicBoolean once = new AtomicBoolean(true), reached = new AtomicBoolean(false);
        SlowOnceDriver(String delegate) throws SQLException {
            this.delegate = delegate; DriverManager.registerDriver(this);
        }
        public Connection connect(String candidate, Properties properties) throws SQLException {
            if (!acceptsURL(candidate)) return null;
            Connection connection = DriverManager.getConnection(delegate, properties);
            return (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(), new Class<?>[]{Connection.class},
                (object, method, args) -> {
                    Object result = invoke(method, connection, args);
                    if (method.getName().equals("prepareStatement") && args[0] instanceof String sql && sql.startsWith("WITH ")) {
                        PreparedStatement statement = (PreparedStatement) result;
                        AtomicInteger timeout = new AtomicInteger(10);
                        return Proxy.newProxyInstance(PreparedStatement.class.getClassLoader(), new Class<?>[]{PreparedStatement.class},
                            (proxy, operation, values) -> {
                                if (operation.getName().equals("setQueryTimeout")) timeout.set((int) values[0]);
                                if (operation.getName().equals("executeQuery") && once.compareAndSet(true, false)) {
                                    reached.set(true);
                                    try (var control = connection.createStatement()) {
                                        control.setQueryTimeout(timeout.get());
                                        try (var rows = control.executeQuery("SELECT SLEEP(4)")) {
                                            if (rows.next()) throw new SQLException("Slow control query completed instead of timing out");
                                        }
                                    }
                                }
                                return invoke(operation, statement, values);
                            });
                    }
                    return result;
                });
        }
        private static Object invoke(Method method, Object target, Object[] args) throws Throwable {
            try { return method.invoke(target, args); }
            catch (InvocationTargetException error) { throw error.getCause(); }
        }
        public boolean acceptsURL(String candidate) { return url.equals(candidate); }
        public DriverPropertyInfo[] getPropertyInfo(String url, Properties info) { return new DriverPropertyInfo[0]; }
        public int getMajorVersion() { return 1; }
        public int getMinorVersion() { return 0; }
        public boolean jdbcCompliant() { return false; }
        public Logger getParentLogger() { return Logger.getGlobal(); }
        public void close() throws SQLException { DriverManager.deregisterDriver(this); }
    }
}
