package com.acme.dorisdsl.security;

import java.util.List;

public record SecurityAudit(
        String sqlHash,
        long estimatedScanBytes,
        double estimatedPlanCost,
        List<String> redactedBindings
) {
    public SecurityAudit { redactedBindings = List.copyOf(redactedBindings); }
}
