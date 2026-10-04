package com.acme.dorisdsl.stockslot;

import org.junit.jupiter.api.Test;
import java.lang.reflect.Proxy;
import java.sql.*;
import java.util.Properties;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.logging.Logger;
import static org.junit.jupiter.api.Assertions.*;

final class DorisConnectionLifecycleTest {
    @Test void snapshotRegistrationFollowsTheConfiguredDatasetNamespace() {
        assertEquals("newzl.data_snapshot_registry",DorisQueryExecutor.snapshotRegistryTable("newzl.v_quotes"));
        assertEquals("isolated_fixture.data_snapshot_registry",DorisQueryExecutor.snapshotRegistryTable("isolated_fixture.v_quotes"));
        assertEquals("data_snapshot_registry",DorisQueryExecutor.snapshotRegistryTable("v_quotes"));
    }

    @Test void connectionClosesWhenReadOnlyVerificationRejectsTheAccount() throws Exception {
        try(var driver=new TestDriver(false)) {
            var error=assertThrows(DorisExecutionException.class,()->driver.open());
            assertEquals(DorisExecutionException.Category.SECURITY_LIMIT,error.category());
            assertTrue(driver.closed.get());
        }
    }

    @Test void connectionClosesWhenSessionConfigurationFails() throws Exception {
        try(var driver=new TestDriver(true)) {
            assertThrows(SQLException.class,()->driver.open());
            assertTrue(driver.closed.get());
        }
    }

    private static <T> T proxy(Class<T> type,java.lang.reflect.InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(),new Class<?>[]{type},handler));
    }

    private static final class TestDriver implements Driver,AutoCloseable {
        final AtomicBoolean closed=new AtomicBoolean();
        final boolean failConfiguration;
        final String url="jdbc:lifecycle-test:"+java.util.UUID.randomUUID();
        TestDriver(boolean failConfiguration) throws SQLException {
            this.failConfiguration=failConfiguration;
            DriverManager.registerDriver(this);
        }
        DorisQueryExecutor open() throws SQLException {
            return new DorisQueryExecutor(url,"test","test",new StockSlotRegistryLoader().loadDefault(),
                    DorisExecutionPolicy.controlledDefaults());
        }
        @Override public Connection connect(String candidate,Properties properties) {
            if(!acceptsURL(candidate))return null;
            return proxy(Connection.class,(object,method,args)->switch(method.getName()) {
                case "close" -> {closed.set(true);yield null;}
                case "setAutoCommit" -> null;
                case "createStatement" -> proxy(Statement.class,(statement,operation,values)->switch(operation.getName()) {
                    case "close" -> null;
                    case "execute" -> {
                        if(failConfiguration)throw new SQLException("session configuration failed");
                        yield true;
                    }
                    case "executeQuery" -> {
                        var first=new AtomicBoolean(true);
                        yield proxy(ResultSet.class,(result,read,arguments)->switch(read.getName()) {
                            case "close" -> null;
                            case "next" -> first.getAndSet(false);
                            case "getString" -> "SELECT_PRIV LOAD_PRIV";
                            case "getMetaData" -> proxy(ResultSetMetaData.class,(metadata,property,index)->1);
                            default -> throw new UnsupportedOperationException(read.getName());
                        });
                    }
                    default -> throw new UnsupportedOperationException(operation.getName());
                });
                default -> throw new UnsupportedOperationException(method.getName());
            });
        }
        @Override public boolean acceptsURL(String candidate) {return url.equals(candidate);}
        @Override public DriverPropertyInfo[] getPropertyInfo(String url,Properties info) {return new DriverPropertyInfo[0];}
        @Override public int getMajorVersion(){return 1;}
        @Override public int getMinorVersion(){return 0;}
        @Override public boolean jdbcCompliant(){return false;}
        @Override public Logger getParentLogger(){return Logger.getGlobal();}
        @Override public void close() throws SQLException {DriverManager.deregisterDriver(this);}
    }
}
