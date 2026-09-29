package com.acme.dorisdsl.security;

import java.util.Locale;
import java.util.Set;

public record ReadOnlyExecutionAccount(String username, Set<String> privileges) {
    private static final Set<String> ALLOWED = Set.of("SELECT", "SHOW", "EXPLAIN");

    public ReadOnlyExecutionAccount {
        if (username == null || username.isBlank()) throw new IllegalArgumentException("Execution username is required");
        privileges = privileges == null ? Set.of() : privileges.stream()
                .map(value -> value.toUpperCase(Locale.ROOT)).collect(java.util.stream.Collectors.toUnmodifiableSet());
        if (!privileges.contains("SELECT") || !ALLOWED.containsAll(privileges)) {
            throw new IllegalArgumentException("Execution account must be read-only with SELECT and optional SHOW/EXPLAIN only");
        }
    }
}
