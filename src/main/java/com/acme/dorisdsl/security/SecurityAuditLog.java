package com.acme.dorisdsl.security;

import java.util.ArrayList;
import java.util.List;

public final class SecurityAuditLog {
    private final int maximumEntries;
    private final List<SecurityAudit> entries = new ArrayList<>();

    public SecurityAuditLog(int maximumEntries) {
        if (maximumEntries < 1) throw new IllegalArgumentException("maximumEntries must be positive");
        this.maximumEntries = maximumEntries;
    }

    public synchronized void append(SecurityAudit audit) {
        entries.add(audit);
        if (entries.size() > maximumEntries) entries.removeFirst();
    }

    public synchronized List<SecurityAudit> snapshot() { return List.copyOf(entries); }
}
