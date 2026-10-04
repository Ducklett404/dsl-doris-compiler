package com.acme.dorisdsl.stockslot;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.nio.file.Path;
import java.sql.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Logger;
import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

final class DorisControlledExecutionIntegrationTest {
    private static final String DSL="indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1";
    private String url,user,password,snapshot;
    private StockSlotRegistry registry;

    @BeforeEach void environment() {
        url=System.getenv("DORIS_JDBC_URL");
        String path=System.getenv("DORIS_FIXTURE_REGISTRY");
        assumeTrue(url!=null && path!=null,"Run scripts/doris/run_wsl_integration.py for the isolated synthetic fixture");
        user=System.getenv("DORIS_JDBC_USER");password=System.getenv("DORIS_JDBC_PASSWORD");
        snapshot=System.getenv("DORIS_FIXTURE_SNAPSHOT_ID");
        registry=new StockSlotRegistryLoader().load(Path.of(path));
    }

    private DorisQueryExecutor open(DorisExecutionPolicy policy) throws SQLException {
        return new DorisQueryExecutor(url,user,password,registry,policy);
    }
    private DorisExecutionPolicy policy(int timeout,long scan,int rows,int queue) {
        return new DorisExecutionPolicy(timeout,scan,rows,128L<<20,queue,true);
    }
    private void assertComplete(DorisExecutionArtifact artifact) {
        assertEquals(Set.of(List.of("1","000001"),List.of("1","000002"),List.of("1","000003"),List.of("1","000004")),
                new HashSet<>(artifact.rows()));
        assertFalse(artifact.truncated());
        assertEquals(snapshot,artifact.dataVersion().snapshotId());
        assertTrue(artifact.sqlFingerprint().startsWith("sha256:"));
        assertTrue(artifact.limits().estimatedScanRows()>0);
    }

    @Test void executesRealPreparedSelectOnTheValidatedSyntheticDataset() throws Exception {
        try(var executor=open(policy(10,10000,100,500))) {
            assertComplete(executor.execute(DSL,snapshot,10,100));
        }
    }

    @Test void returnCapIsEnforcedAndResultResourcesRemainUsable() throws Exception {
        try(var executor=open(policy(10,10000,2,500))) {
            for(int i=0;i<2;i++) {
                var result=executor.execute(DSL,snapshot,10,100);
                assertEquals(2,result.rows().size());assertTrue(result.truncated());
                assertEquals(2,result.limits().maxReturnRows());
            }
            executor.ping();
        }
    }

    @Test void unvalidatedAndInjectedSnapshotIdsAreRejectedThenAnotherThreadCanExecute() throws Exception {
        try(var executor=open(policy(10,10000,100,80));var workers=Executors.newSingleThreadExecutor()) {
            for(String invalid:List.of("fixture-pending","' OR 1=1 --")) {
                var error=assertThrows(DorisExecutionException.class,()->executor.execute(DSL,invalid,10,100));
                assertEquals(DorisExecutionException.Category.DATA_UNAVAILABLE,error.category());
            }
            assertComplete(workers.submit(()->executor.execute(DSL,snapshot,10,100)).get(10,TimeUnit.SECONDS));
        }
    }

    @Test void scanLimitRejectsBeforeExecutionAndReleasesTheQueueSlot() throws Exception {
        try(var executor=open(policy(10,1,100,80));var workers=Executors.newSingleThreadExecutor()) {
            var error=assertThrows(DorisExecutionException.class,()->executor.execute(DSL,snapshot,10,100));
            assertEquals(DorisExecutionException.Category.SECURITY_LIMIT,error.category());
            assertTrue(error.getMessage().contains("Estimated scan rows"));
            var followup=workers.submit(()->assertThrows(DorisExecutionException.class,
                    ()->executor.execute(DSL,snapshot,10,100))).get(10,TimeUnit.SECONDS);
            assertEquals(DorisExecutionException.Category.SECURITY_LIMIT,followup.category());
        }
    }

    @Test void accountsWithWritePrivilegeCannotInitializeTheExecutor() {
        var error=assertThrows(DorisExecutionException.class,()->new DorisQueryExecutor(url,
                System.getenv("DORIS_WRITER_USER"),System.getenv("DORIS_WRITER_PASSWORD"),registry,
                policy(10,10000,100,500)));
        assertEquals(DorisExecutionException.Category.SECURITY_LIMIT,error.category());
        assertTrue(error.getMessage().contains("LOAD_PRIV"));
    }

    @Test void queuedRequestTimesOutWhileFirstRequestHoldsTheSlotAndBothRecover() throws Exception {
        // Pause the test transport after admission; actual SELECTs still use real Doris.
        try(var driver=new DelayedDriver(url,false);var executor=new DorisQueryExecutor(driver.url,user,password,
                registry,policy(10,10000,100,80));var workers=Executors.newFixedThreadPool(2)) {
            var first=workers.submit(()->executor.execute(DSL,snapshot,10,100));
            try {
                assertTrue(driver.entered.await(10,TimeUnit.SECONDS));
                var queued=workers.submit(()->assertThrows(DorisExecutionException.class,
                        ()->executor.execute(DSL,snapshot,10,100))).get(5,TimeUnit.SECONDS);
                assertEquals(DorisExecutionException.Category.TIMEOUT,queued.category());
                assertTrue(queued.getMessage().contains("queue wait"));
            } finally {driver.release.countDown();}
            assertComplete(first.get(10,TimeUnit.SECONDS));
            assertComplete(workers.submit(()->executor.execute(DSL,snapshot,10,100)).get(10,TimeUnit.SECONDS));
        }
    }

    @Test void realDatabaseTimeoutMapsToTimeoutAndTheNextRequestRecovers() throws Exception {
        // A test-only transport runs a slow read-only control query once, using the actual JDBC timeout.
        try(var driver=new DelayedDriver(url,true);var executor=new DorisQueryExecutor(driver.url,user,password,
                registry,policy(1,10000,100,80));var workers=Executors.newSingleThreadExecutor()) {
            var error=assertThrows(DorisExecutionException.class,()->executor.execute(DSL,snapshot,1,100));
            assertEquals(DorisExecutionException.Category.TIMEOUT,error.category());
            assertComplete(workers.submit(()->executor.execute(DSL,snapshot,1,100)).get(10,TimeUnit.SECONDS));
        }
    }

    private static final class DelayedDriver implements Driver,AutoCloseable {
        final String url="jdbc:executor-control-test:"+UUID.randomUUID();
        final String delegateUrl;
        final boolean databaseTimeout;
        final AtomicBoolean once=new AtomicBoolean(true);
        final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        DelayedDriver(String delegateUrl,boolean databaseTimeout) throws SQLException {
            this.delegateUrl=delegateUrl;this.databaseTimeout=databaseTimeout;DriverManager.registerDriver(this);
        }
        @Override public Connection connect(String candidate,Properties properties) throws SQLException {
            if(!acceptsURL(candidate))return null;
            Connection connection=DriverManager.getConnection(delegateUrl,properties);
            return (Connection)Proxy.newProxyInstance(Connection.class.getClassLoader(),new Class<?>[]{Connection.class},
                (object,method,args)-> {
                    Object result=invoke(method,connection,args);
                    if(method.getName().equals("prepareStatement") && args[0] instanceof String sql && sql.startsWith("WITH ")) {
                        PreparedStatement statement=(PreparedStatement)result;
                        AtomicInteger timeout=new AtomicInteger(10);
                        return Proxy.newProxyInstance(PreparedStatement.class.getClassLoader(),new Class<?>[]{PreparedStatement.class},
                            (proxy,operation,values)-> {
                                if(operation.getName().equals("setQueryTimeout"))timeout.set((int)values[0]);
                                if(operation.getName().equals("executeQuery") && once.compareAndSet(true,false)) {
                                    entered.countDown();
                                    if(databaseTimeout) {
                                        try(var slow=connection.createStatement()) {
                                            slow.setQueryTimeout(timeout.get());
                                            try(var rows=slow.executeQuery("SELECT SLEEP(4)")) {
                                                if(rows.next())throw new SQLException("Slow control query unexpectedly completed");
                                            }
                                        }
                                    } else if(!release.await(10,TimeUnit.SECONDS))throw new SQLTimeoutException("Test transport wait expired");
                                }
                                return invoke(operation,statement,values);
                            });
                    }
                    return result;
                });
        }
        private static Object invoke(java.lang.reflect.Method method,Object target,Object[] args) throws Throwable {
            try{return method.invoke(target,args);}catch(InvocationTargetException error){throw error.getCause();}
        }
        @Override public boolean acceptsURL(String candidate){return url.equals(candidate);}
        @Override public DriverPropertyInfo[] getPropertyInfo(String url,Properties info){return new DriverPropertyInfo[0];}
        @Override public int getMajorVersion(){return 1;}
        @Override public int getMinorVersion(){return 0;}
        @Override public boolean jdbcCompliant(){return false;}
        @Override public Logger getParentLogger(){return Logger.getGlobal();}
        @Override public void close() throws SQLException {release.countDown();DriverManager.deregisterDriver(this);}
    }
}
