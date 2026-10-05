package com.acme.dorisdsl.stockslot;

import java.nio.charset.StandardCharsets;
import java.sql.*;

/** Read-only source identity: view SQL hash plus ordered column names, types and nullability. */
public final class ProjectSourceDefinition {
    private ProjectSourceDefinition() {}

    public static String fingerprint(Connection connection, String qualified, String kind, int timeout) throws SQLException {
        if (!qualified.matches("[A-Za-z_][A-Za-z0-9_]*\\.[A-Za-z_][A-Za-z0-9_]*")
                || !(kind.equals("VIEW") || kind.equals("TABLE"))) throw new IllegalArgumentException("Invalid source identity");
        String[] names = qualified.split("\\.");
        String definition = "";
        try (var statement = metadata(connection, "SELECT TABLE_TYPE FROM information_schema.tables", names, timeout);
             var rows = statement.executeQuery()) {
            if (!rows.next() || !kind.equals(rows.getString(1).equals("VIEW") ? "VIEW" : "TABLE") || rows.next())
                throw new SQLException("Source kind unavailable or changed");
        }
        if (kind.equals("VIEW")) {
            try (var statement = metadata(connection, "SELECT SHA2(VIEW_DEFINITION,256) FROM information_schema.views", names, timeout);
                 var rows = statement.executeQuery()) {
                if (!rows.next()) throw new SQLException("View definition unavailable to read-only account");
                definition = rows.getString(1);
                if (definition == null || !definition.matches("[0-9a-f]{64}") || rows.next())
                    throw new SQLException("View definition identity unavailable");
            }
        }
        var text = new StringBuilder("project-source-definition-v1\n").append(kind).append('\n').append(definition).append('\n');
        int count = 0;
        try (var statement = metadata(connection, "SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION FROM information_schema.columns", names, timeout, " ORDER BY ORDINAL_POSITION");
             var rows = statement.executeQuery()) {
            while (rows.next()) {
                for (int i=1;i<=4;i++) {
                    String value=rows.getString(i);
                    if (value==null || value.contains("\t") || value.contains("\n") || value.contains("\r"))
                        throw new SQLException("Unexpected source column metadata");
                    if (i>1) text.append('\t');
                    text.append(value);
                }
                text.append('\n');count++;
            }
        }
        if (count==0) throw new SQLException("Source column metadata unavailable");
        return ProjectDataValidation.sha(text.toString().getBytes(StandardCharsets.UTF_8));
    }

    private static PreparedStatement metadata(Connection connection, String select, String[] names, int timeout) throws SQLException {
        return metadata(connection, select, names, timeout, "");
    }
    private static PreparedStatement metadata(Connection connection, String select, String[] names, int timeout, String suffix) throws SQLException {
        var statement = connection.prepareStatement(select + " WHERE TABLE_SCHEMA=? AND TABLE_NAME=?" + suffix);
        statement.setQueryTimeout(timeout);statement.setString(1,names[0]);statement.setString(2,names[1]);
        return statement;
    }
}
