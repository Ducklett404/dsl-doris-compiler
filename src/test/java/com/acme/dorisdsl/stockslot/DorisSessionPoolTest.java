package com.acme.dorisdsl.stockslot;

import org.junit.jupiter.api.Test;

import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class DorisSessionPoolTest {
    @Test void twoIndependentSessionsAreExclusiveAndReturnedAfterAnError() throws Exception {
        var opens = new AtomicInteger();
        var closes = new AtomicInteger();
        try (var pool = new DorisSessionPool(2, 50, () -> {
            opens.incrementAndGet();
            return connection(closes, false);
        }); var first = pool.acquire()) {
            var second = pool.acquire();
            assertEquals(2, opens.get());
            assertNotSame(first.connection(), second.connection());
            assertQueueTimeout(pool, 50);
            assertThrows(SQLException.class, () -> {
                try (second) { throw new SQLException("simulated statement failure"); }
            });
            try (var next = pool.acquire()) {
                assertSame(second.connection(), next.connection());
                second.close();
                assertQueueTimeout(pool, 50);
            }
            assertEquals(0, closes.get());
        }
        assertEquals(2, closes.get());
    }

    @Test void waiterResumesOnReleaseAndCanUseOnlyTheReturnedSession() throws Exception {
        try (var pool = new DorisSessionPool(2, 2_000, () -> connection(new AtomicInteger(), false));
             var tasks = Executors.newVirtualThreadPerTaskExecutor();
             var first = pool.acquire(); var second = pool.acquire()) {
            var started = new CountDownLatch(1);
            var waiting = tasks.submit(() -> {
                started.countDown();
                try (var acquired = pool.acquire()) { return acquired.connection(); }
            });
            assertTrue(started.await(2, TimeUnit.SECONDS));
            assertFalse(waiting.isDone());
            first.close();
            assertSame(first.connection(), waiting.get(2, TimeUnit.SECONDS));
            assertNotSame(second.connection(), waiting.get());
        }
    }

    @Test void interruptionOfAWaitingRequestPreservesInterruptAndCapacity() throws Exception {
        try (var pool = new DorisSessionPool(1, 2_000, () -> connection(new AtomicInteger(), false));
             var first = pool.acquire();
             var tasks = Executors.newVirtualThreadPerTaskExecutor()) {
            var status = tasks.submit(() -> {
                Thread.currentThread().interrupt();
                var failure = assertThrows(DorisExecutionException.class, pool::acquire);
                assertEquals(DorisExecutionException.Category.TIMEOUT, failure.category());
                return Thread.currentThread().isInterrupted();
            });
            assertTrue(status.get(2, TimeUnit.SECONDS));
            first.close();
            try (var next = pool.acquire()) { assertSame(first.connection(), next.connection()); }
        }
    }

    @Test void shutdownRejectsWaitersAndDrainsActiveLeasesBeforeClosingJdbc() throws Exception {
        var closes = new AtomicInteger();
        try (var pool = new DorisSessionPool(2, 5_000, () -> connection(closes, false));
             var tasks = Executors.newVirtualThreadPerTaskExecutor();
             var first = pool.acquire(); var second = pool.acquire()) {
            var waiting = tasks.submit(() -> assertThrows(DorisExecutionException.class, pool::acquire));
            var shutdown = tasks.submit(() -> { pool.close(); return null; });
            assertEquals(DorisExecutionException.Category.DATA_UNAVAILABLE, waiting.get(2, TimeUnit.SECONDS).category());
            assertFalse(shutdown.isDone());
            assertEquals(0, closes.get());
            first.close();
            assertFalse(shutdown.isDone());
            second.close();
            shutdown.get(2, TimeUnit.SECONDS);
            assertEquals(2, closes.get());
            assertEquals(DorisExecutionException.Category.DATA_UNAVAILABLE,
                    assertThrows(DorisExecutionException.class, pool::acquire).category());
        }
        assertEquals(2, closes.get());
    }

    @Test void partialStartupClosesEachPreviouslyConfiguredConnection() {
        var connections = new AtomicInteger();
        var closes = new AtomicInteger();
        var failure = assertThrows(SQLException.class, () -> new DorisSessionPool(3, 50, () -> {
            int id = connections.incrementAndGet();
            if (id == 3) throw new SQLException("third session rejected");
            return connection(closes, id == 1);
        }));
        assertEquals("third session rejected", failure.getMessage());
        assertEquals(1, failure.getSuppressed().length);
        assertEquals(2, closes.get());
    }

    @Test void shutdownAttemptsAllClosesAndRetainsSecondaryErrors() throws Exception {
        var closes = new AtomicInteger();
        var pool = new DorisSessionPool(3, 50, () -> connection(closes, true));
        var failure = assertThrows(SQLException.class, pool::close);
        assertEquals(2, failure.getSuppressed().length);
        assertEquals(3, closes.get());
        pool.close();
        assertEquals(3, closes.get());
    }

    @Test void invalidCapacityFailsBeforeOpeningAnySessions() {
        for (int count : new int[] {0, 33}) {
            assertThrows(IllegalArgumentException.class, () -> new DorisSessionPool(count, 50,
                    () -> { throw new AssertionError("unexpected session"); }));
        }
    }

    private static void assertQueueTimeout(DorisSessionPool pool, int limit) {
        long start = System.nanoTime();
        var failure = assertThrows(DorisExecutionException.class, pool::acquire);
        assertEquals(DorisExecutionException.Category.TIMEOUT, failure.category());
        assertEquals("Execution queue wait exceeded " + limit + " ms", failure.getMessage());
        assertTrue(System.nanoTime() - start >= TimeUnit.MILLISECONDS.toNanos(limit));
    }

    private static Connection connection(AtomicInteger closes, boolean rejectClose) {
        return (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(), new Class<?>[]{Connection.class},
                (self, method, args) -> {
                    if (!method.getName().equals("close")) throw new UnsupportedOperationException(method.getName());
                    closes.incrementAndGet();
                    if (rejectClose) throw new SQLException("close failed");
                    return null;
                });
    }
}
