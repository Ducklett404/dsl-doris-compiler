package com.acme.dorisdsl.executor.doris;

import java.sql.SQLException;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class ExplainService {
    private static final Pattern PARTITIONS = Pattern.compile("(?i)partitions?\\s*[=:]\\s*(\\d+)\\s*/\\s*(\\d+)");
    private static final Pattern TABLETS = Pattern.compile("(?i)tablets?\\s*[=:]\\s*(\\d+)\\s*/\\s*(\\d+)");
    private final DorisQueryExecutor executor;

    public ExplainService(DorisQueryExecutor executor) { this.executor = executor; }

    public ExplainEvidence explain(String sql, List<?> bindings) throws SQLException {
        String raw = String.join("\n", executor.explain(sql, bindings));
        Ratio partitions = ratio(PARTITIONS, raw);
        Ratio tablets = ratio(TABLETS, raw);
        String lower = raw.toLowerCase(Locale.ROOT);
        boolean featureTableHit = lower.contains("dws_quote_feature_daily");
        boolean materializedViewHit = lower.contains("materialized view") || lower.contains("mv_");
        boolean indexHit = lower.contains("index") || lower.contains("tablets=") || lower.contains("tablets:");
        return new ExplainEvidence(raw, partitions.used(), partitions.total(),
                partitions.pruned(), tablets.used(), tablets.total(), tablets.pruned(),
                materializedViewHit, indexHit, featureTableHit);
    }

    private static Ratio ratio(Pattern pattern, String value) {
        Matcher matcher = pattern.matcher(value);
        if (!matcher.find()) return new Ratio(-1, -1);
        return new Ratio(Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
    }

    private record Ratio(int used, int total) { boolean pruned() { return used >= 0 && total > 0 && used < total; } }

    public record ExplainEvidence(String rawPlan, int scannedPartitions, int totalPartitions,
                                  boolean partitionPruned, int scannedTablets, int totalTablets,
                                  boolean bucketOrTabletPruned, boolean materializedViewHit,
                                  boolean indexHit, boolean featureTableHit) {}
}
