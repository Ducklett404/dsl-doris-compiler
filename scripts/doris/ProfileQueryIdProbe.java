package com.acme.dorisdsl.stockslot;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.sql.*;
import java.util.*;

/** Small, read-only Connector/J diagnostic. Credentials arrive only on stdin. */
class ProfileQueryIdProbe {
    private static final String MAIN = "SELECT mktcode,tgtcode FROM newzl.hsj_stock_code_info ORDER BY mktcode,tgtcode LIMIT 3";

    public static void main(String[] args) throws Exception {
        var input = new BufferedReader(new InputStreamReader(System.in));
        String url = input.readLine(), user = input.readLine(), password = input.readLine();
        try (var connection = DriverManager.getConnection(url, user, password)) {
            try (var setup = connection.createStatement()) {
                setup.execute("SET enable_profile=true");
                setup.execute("SET query_timeout=10");
                setup.execute("SET exec_mem_limit=2147483648");
                setup.execute("SET parallel_pipeline_task_num=4");
            }
            String oldId, fixedId;
            List<List<String>> oldRows = new ArrayList<>(), fixedRows = new ArrayList<>();
            try (var main = connection.prepareStatement(MAIN)) {
                main.setQueryTimeout(10); main.setMaxRows(4);
                try (var rows = main.executeQuery()) {
                    while (rows.next()) oldRows.add(List.of(rows.getString(1), rows.getString(2)));
                }
            }
            try (var id = connection.createStatement(); var rows = id.executeQuery("SELECT LAST_QUERY_ID()")) {
                oldId = rows.next() ? rows.getString(1) : null;
            }
            try (var main = connection.prepareStatement(MAIN)) {
                main.setQueryTimeout(10); main.setMaxRows(4);
                try (var rows = main.executeQuery()) {
                    while (rows.next()) fixedRows.add(List.of(rows.getString(1), rows.getString(2)));
                }
                fixedId = DorisQueryExecutor.lastQueryId(connection, 10, 4);
            }
            boolean oldMatched = false, fixedMatched = false;
            List<String> headers = new ArrayList<>();
            String state = null, total = null, owner = null;
            try (var profiles = connection.createStatement()) {
                profiles.setQueryTimeout(10);
                try (var rows = profiles.executeQuery("SHOW QUERY PROFILE")) {
                    var metadata = rows.getMetaData();
                    for (int i = 1; i <= metadata.getColumnCount(); i++) headers.add(metadata.getColumnLabel(i));
                    while (rows.next()) {
                        String id = rows.getString("Profile ID");
                        if (Objects.equals(id, oldId)) oldMatched = MAIN.equals(rows.getString("Sql Statement"));
                        if (Objects.equals(id, fixedId)) {
                            fixedMatched = MAIN.equals(rows.getString("Sql Statement"));
                            state = rows.getString("Task State"); total = rows.getString("Total"); owner = rows.getString("User");
                        }
                    }
                }
            }
            var summary = DorisQueryExecutor.profileSummary(connection, fixedId, 10);
            boolean pass = !oldMatched && fixedMatched && oldRows.equals(fixedRows) && fixedRows.size() == 3
                    && state != null && total != null && user.equals(owner)
                    && summary.available() && fixedId.equals(summary.queryId())
                    && state.equals(summary.taskState()) && total.equals(summary.total()) && owner.equals(summary.user());
            System.out.println("status=" + (pass ? "PASS" : "FAIL"));
            System.out.println("connector=" + connection.getMetaData().getDriverVersion());
            System.out.println("oldId=" + oldId + "; mainProfileMatched=" + oldMatched);
            System.out.println("fixedId=" + fixedId + "; mainProfileMatched=" + fixedMatched);
            System.out.println("identicalRows=" + oldRows.equals(fixedRows) + "; rowCount=" + fixedRows.size());
            System.out.println("headers=" + String.join("|", headers));
            System.out.println("taskState=" + state + "; total=" + total + "; ownerMatchesReadOnlyAccount=" + user.equals(owner));
            System.out.println("productionProfileHelperAvailable=" + summary.available());
            if (!pass) System.exit(1);
        }
    }
}
