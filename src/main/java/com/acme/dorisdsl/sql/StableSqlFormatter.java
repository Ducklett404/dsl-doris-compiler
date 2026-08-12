package com.acme.dorisdsl.sql;

import java.util.Arrays;
import java.util.stream.Collectors;

public final class StableSqlFormatter {
    private StableSqlFormatter() {}

    public static String format(String sql) {
        if (sql == null) throw new IllegalArgumentException("SQL cannot be null");
        String normalized = sql.replace("\r\n", "\n").replace('\r', '\n');
        String formatted = Arrays.stream(normalized.split("\n", -1))
                .map(String::stripTrailing)
                .collect(Collectors.joining("\n"))
                .stripTrailing();
        return formatted + "\n";
    }
}
