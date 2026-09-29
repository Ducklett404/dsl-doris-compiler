package com.acme.dorisdsl.executor.doris;

import java.sql.SQLException;
import java.util.List;

public interface DorisQueryExecutor {
    List<String> explain(String sql, List<?> bindings) throws SQLException;
    QueryExecution executeProfiled(String sql, List<?> bindings) throws SQLException;

    record QueryExecution(String queryId, long clientElapsedNanos) {}
}
