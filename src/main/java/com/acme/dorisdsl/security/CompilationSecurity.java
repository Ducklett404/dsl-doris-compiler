package com.acme.dorisdsl.security;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.plan.LogicalPlan;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.temporal.TemporalAccessor;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

public final class CompilationSecurity {
    private static final Pattern FORBIDDEN_DSL = Pattern.compile(
            "(?is)(;|--|/\\*|\\*/|\\b(select|with|insert|update|delete|drop|alter|create|grant|revoke|call)\\b)");
    private final SecurityPolicy policy;

    public CompilationSecurity(SecurityPolicy policy) { this.policy = policy; }

    public void validateDsl(String dsl) {
        var match = FORBIDDEN_DSL.matcher(dsl);
        if (match.find()) {
            throw new CompileException("DSL_UNSAFE_TOKEN",
                    "Arbitrary SQL, comments, subqueries, and semicolons are not allowed: " + match.group(), 1, match.start() + 1);
        }
    }

    public SecurityAudit auditAndEnforce(String sql, List<Object> bindings,
                                         LogicalPlan logicalPlan, int lookback) {
        long scanBytes;
        try {
            scanBytes = Math.multiplyExact(Math.multiplyExact(Math.max(1, lookback + 1L),
                    policy.estimatedRowsPerTradingDay()), policy.estimatedBytesPerRow());
        } catch (ArithmeticException exception) {
            throw new CompileException("SCAN_LIMIT_EXCEEDED", "Estimated scan size overflowed", 1, 1);
        }
        double planCost = logicalPlan.accessPath().candidates().stream()
                .filter(candidate -> candidate.path().equals(logicalPlan.accessPath().selected()))
                .mapToDouble(LogicalPlan.Candidate::cost).findFirst().orElse(Double.POSITIVE_INFINITY);
        if (scanBytes > policy.maximumEstimatedScanBytes()) {
            throw new CompileException("SCAN_LIMIT_EXCEEDED",
                    "Estimated scan " + scanBytes + " bytes exceeds limit " + policy.maximumEstimatedScanBytes(), 1, 1);
        }
        if (planCost > policy.maximumPlanCost()) {
            throw new CompileException("COST_LIMIT_EXCEEDED",
                    "Estimated plan cost " + planCost + " exceeds limit " + policy.maximumPlanCost(), 1, 1);
        }
        return new SecurityAudit(hash(sql), scanBytes, planCost,
                bindings.stream().map(this::redact).toList());
    }

    private String redact(Object value) {
        if (value == null) return "<null>";
        if (value instanceof Number) return "<number>";
        if (value instanceof TemporalAccessor) return "<date>";
        if (value instanceof Boolean) return "<boolean>";
        return "<" + value.getClass().getSimpleName().toLowerCase(Locale.ROOT) + ":redacted>";
    }

    private String hash(String sql) {
        try {
            return "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(sql.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }
}
