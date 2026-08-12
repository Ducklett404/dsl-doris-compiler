package com.acme.dorisdsl.executor.doris;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

public final class JdbcDorisQueryExecutor implements DorisQueryExecutor {
    @FunctionalInterface
    public interface ConnectionFactory { Connection open() throws SQLException; }

    private final ConnectionFactory connections;

    public JdbcDorisQueryExecutor(ConnectionFactory connections) { this.connections = connections; }

    @Override public List<String> explain(String sql, List<?> bindings) throws SQLException {
        try (Connection connection = connections.open();
             PreparedStatement statement = connection.prepareStatement("EXPLAIN " + stripTerminator(sql))) {
            bind(statement, bindings);
            try (ResultSet rows = statement.executeQuery()) {
                List<String> plan = new ArrayList<>();
                while (rows.next()) plan.add(rows.getString(1));
                return List.copyOf(plan);
            }
        }
    }

    @Override public QueryExecution executeProfiled(String sql, List<?> bindings) throws SQLException {
        try (Connection connection = connections.open()) {
            try (Statement setup = connection.createStatement()) { setup.execute("SET enable_profile=true"); }
            long started = System.nanoTime();
            try (PreparedStatement statement = connection.prepareStatement(stripTerminator(sql))) {
                bind(statement, bindings);
                boolean hasRows = statement.execute();
                if (hasRows) try (ResultSet rows = statement.getResultSet()) { while (rows.next()) { } }
            }
            long elapsed = System.nanoTime() - started;
            try (Statement statement = connection.createStatement();
                 ResultSet row = statement.executeQuery("SELECT LAST_QUERY_ID()")) {
                if (!row.next()) throw new SQLException("Doris did not return LAST_QUERY_ID()");
                return new QueryExecution(row.getString(1), elapsed);
            }
        }
    }

    private static void bind(PreparedStatement statement, List<?> bindings) throws SQLException {
        for (int i = 0; i < bindings.size(); i++) {
            Object value = bindings.get(i);
            if (value instanceof LocalDate date) statement.setObject(i + 1, date);
            else statement.setObject(i + 1, value);
        }
    }

    private static String stripTerminator(String sql) {
        String value = sql.strip();
        return value.endsWith(";") ? value.substring(0, value.length() - 1) : value;
    }
}
