package com.acme.dorisdsl.stockslot;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.ArrayDeque;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.ReentrantLock;

/** A request owns one configured JDBC session, including LAST_QUERY_ID and profile lookup. */
final class DorisSessionPool implements AutoCloseable {
    @FunctionalInterface interface Factory { Connection open() throws SQLException; }

    private final int capacity;
    private final int queueWaitMillis;
    private final ArrayDeque<Connection> idle = new ArrayDeque<>();
    private final ReentrantLock lock = new ReentrantLock(true);
    private final Condition available = lock.newCondition();
    private boolean closed;

    DorisSessionPool(int capacity, int queueWaitMillis, Factory factory) throws SQLException {
        if (capacity < 1 || capacity > 32) throw new IllegalArgumentException("executionSlots must be 1..32");
        this.capacity = capacity;
        this.queueWaitMillis = queueWaitMillis;
        try {
            for (int i = 0; i < capacity; i++) idle.addLast(factory.open());
        } catch (SQLException | RuntimeException | Error error) {
            try { closeIdle(); } catch (SQLException cleanup) { error.addSuppressed(cleanup); }
            throw error;
        }
    }

    Lease acquire() {
        lock.lock();
        try {
            long remaining = TimeUnit.MILLISECONDS.toNanos(queueWaitMillis);
            while (idle.isEmpty() && !closed) {
                if (remaining <= 0) throw new DorisExecutionException(DorisExecutionException.Category.TIMEOUT,
                        "Execution queue wait exceeded " + queueWaitMillis + " ms");
                remaining = available.awaitNanos(remaining);
            }
            if (closed) throw new DorisExecutionException(DorisExecutionException.Category.DATA_UNAVAILABLE,
                    "Doris execution sessions are closed");
            return new Lease(idle.removeFirst());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new DorisExecutionException(DorisExecutionException.Category.TIMEOUT, "Interrupted while waiting for execution slot", e);
        } finally {
            lock.unlock();
        }
    }

    final class Lease implements AutoCloseable {
        private final Connection connection;
        private boolean returned;
        private Lease(Connection connection) { this.connection = connection; }
        Connection connection() { return connection; }

        @Override public void close() {
            lock.lock();
            try {
                if (returned) return;
                returned = true;
                idle.addLast(connection);
                if (closed) available.signalAll(); else available.signal();
            } finally {
                lock.unlock();
            }
        }
    }

    @Override public void close() throws SQLException {
        lock.lock();
        try {
            if (closed) return;
            closed = true;
            available.signalAll();
            while (idle.size() != capacity) available.awaitUninterruptibly();
            closeIdle();
        } finally {
            lock.unlock();
        }
    }

    private void closeIdle() throws SQLException {
        SQLException failure = null;
        while (!idle.isEmpty()) {
            try { idle.removeFirst().close(); }
            catch (SQLException e) {
                if (failure == null) failure = e; else failure.addSuppressed(e);
            }
        }
        if (failure != null) throw failure;
    }
}
