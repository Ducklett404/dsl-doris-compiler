package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.util.JsonSupport;
import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.Map;
import java.util.Set;

/** Explicit, immutable publication of a complete snapshot/date feature build.
 * This catalog selects SQL access paths; it does not validate a source snapshot.
 */
public record HistoricalExtremaFeatureCatalog(
        String formatVersion, String snapshotId, String manifestSha256,
        String registryFingerprint, String qualifiedTable,
        Map<LocalDate, Long> completeDates, Map<String, MetricColumns> metrics) {
    public record MetricColumns(String sourceExpression, String currentField, String minField, String maxField) {
        public MetricColumns {
            if (sourceExpression == null || sourceExpression.isBlank()) throw new IllegalArgumentException("Missing source expression");
            for (String field : new String[]{currentField, minField, maxField})
                if (field == null || !field.matches("[A-Za-z_][A-Za-z0-9_]*"))
                    throw new IllegalArgumentException("Unsafe historical feature field");
            if (Set.of(currentField, minField, maxField).size() != 3)
                throw new IllegalArgumentException("Historical feature fields must be distinct");
        }
    }

    public HistoricalExtremaFeatureCatalog {
        if (!"history-extrema-v1".equals(formatVersion)
                || snapshotId == null || !snapshotId.matches("[A-Za-z0-9_.-]{1,128}")
                || manifestSha256 == null || !manifestSha256.matches("[0-9a-f]{64}")
                || registryFingerprint == null || !registryFingerprint.matches("[0-9a-f]{64}")
                || qualifiedTable == null || !qualifiedTable.matches("[A-Za-z_][A-Za-z0-9_]*\\.[A-Za-z_][A-Za-z0-9_]*"))
            throw new IllegalArgumentException("Invalid historical feature catalog identity");
        completeDates = Map.copyOf(completeDates);
        metrics = Map.copyOf(metrics);
        if (completeDates.isEmpty() || completeDates.values().stream().anyMatch(n -> n < 0) || metrics.isEmpty())
            throw new IllegalArgumentException("Historical feature publication must include complete dates and metrics");
        if (metrics.values().stream().map(MetricColumns::sourceExpression).distinct().count() != metrics.size())
            throw new IllegalArgumentException("Ambiguous historical feature expressions");
    }

    public static HistoricalExtremaFeatureCatalog load(Path path) throws IOException {
        return JsonSupport.MAPPER.readValue(path.toFile(), HistoricalExtremaFeatureCatalog.class);
    }

    boolean matches(StockSlotRegistry registry, String snapshot, String manifest, LocalDate date) {
        return snapshotId.equals(snapshot) && manifestSha256.equals(manifest)
                && registryFingerprint.equals(registry.fingerprint()) && completeDates.containsKey(date);
    }

    MetricColumns columns(String expression) {
        return metrics.values().stream().filter(m -> m.sourceExpression().equals(expression)).findFirst().orElse(null);
    }
}
