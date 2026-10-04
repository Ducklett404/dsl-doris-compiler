package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.util.JsonSupport;
import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.Map;

/** Complete strict observed-row averages, explicitly bound to an immutable source. */
public record RollingAverageFeatureCatalog(String formatVersion, String snapshotId, String manifestSha256,
        String registryFingerprint, String qualifiedTable, String sourceExpression,
        Map<LocalDate, Long> completeDates, Map<Integer, String> windowFields,
        Map<String,RangeColumns> rangeFields) {
    public record RangeColumns(String sourceExpression,int period,String currentField,String minField,String maxField) {
        public RangeColumns {
            if(sourceExpression==null || sourceExpression.isBlank() || period<1 || period>5000)
                throw new IllegalArgumentException("Invalid range feature source or period");
            new HistoricalExtremaFeatureCatalog.MetricColumns(sourceExpression,currentField,minField,maxField);
        }
    }
    public RollingAverageFeatureCatalog(String formatVersion,String snapshotId,String manifestSha256,String registryFingerprint,
            String qualifiedTable,String sourceExpression,Map<LocalDate,Long> completeDates,Map<Integer,String> windowFields) {
        this(formatVersion,snapshotId,manifestSha256,registryFingerprint,qualifiedTable,sourceExpression,completeDates,windowFields,Map.of());
    }
    public RollingAverageFeatureCatalog {
        if (!"rolling-average-v1".equals(formatVersion)
                || snapshotId==null || !snapshotId.matches("[A-Za-z0-9_.-]{1,128}")
                || manifestSha256==null || !manifestSha256.matches("[0-9a-f]{64}")
                || registryFingerprint==null || !registryFingerprint.matches("[0-9a-f]{64}")
                || qualifiedTable==null || !qualifiedTable.matches("[A-Za-z_][A-Za-z0-9_]*\\.[A-Za-z_][A-Za-z0-9_]*")
                || sourceExpression==null || sourceExpression.isBlank())
            throw new IllegalArgumentException("Invalid rolling feature identity");
        completeDates=Map.copyOf(completeDates);windowFields=Map.copyOf(windowFields);
        rangeFields=rangeFields==null?Map.of():Map.copyOf(rangeFields);
        if(rangeFields.values().stream().map(r->r.sourceExpression()+":"+r.period()).distinct().count()!=rangeFields.size())
            throw new IllegalArgumentException("Ambiguous range feature mappings");
        if (completeDates.isEmpty() || completeDates.values().stream().anyMatch(n->n<0) || windowFields.isEmpty()
                || windowFields.entrySet().stream().anyMatch(e->e.getKey()<1 || e.getKey()>5000
                    || !e.getValue().matches("[A-Za-z_][A-Za-z0-9_]*"))
                || windowFields.values().stream().distinct().count()!=windowFields.size())
            throw new IllegalArgumentException("Invalid rolling feature coverage or columns");
    }
    public static RollingAverageFeatureCatalog load(Path path) throws IOException {
        return JsonSupport.MAPPER.readValue(path.toFile(),RollingAverageFeatureCatalog.class);
    }
    boolean matches(StockSlotRegistry registry,String snapshot,String manifest,LocalDate date) {
        return snapshotId.equals(snapshot) && manifestSha256.equals(manifest)
                && registryFingerprint.equals(registry.fingerprint()) && completeDates.containsKey(date);
    }
    RangeColumns range(String expression,int period) {
        return rangeFields.values().stream().filter(r->r.period()==period && r.sourceExpression().equals(expression)).findFirst().orElse(null);
    }
}
