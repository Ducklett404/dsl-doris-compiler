package com.acme.dorisdsl.catalog;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

public record CatalogSnapshot(
        String version,
        Instant capturedAt,
        TableMappings tables,
        Map<String, TableMetadata> tableMetadata,
        PrefixDailyMetadata prefixDaily,
        FeatureMetadata feature,
        DorisCapabilities doris
) {
    public CatalogSnapshot {
        if (version == null || version.isBlank()) throw new IllegalArgumentException("Catalog version is required");
        if (capturedAt == null || tables == null || prefixDaily == null || feature == null || doris == null)
            throw new IllegalArgumentException("Catalog snapshot is incomplete");
        tableMetadata = tableMetadata == null ? Map.of() : Map.copyOf(tableMetadata);
    }

    public record TableMappings(String detailTable, String financialPitTable, String calendarTable,
                                String featureTable, String prefixSumTable) {}

    public record TableMetadata(long estimatedRows, int estimatedRowBytes, PartitionRange partitionRange,
                                BucketInfo bucketInfo, List<String> indexes, List<String> materializedViews) {
        public TableMetadata {
            indexes = indexes == null ? List.of() : List.copyOf(indexes);
            materializedViews = materializedViews == null ? List.of() : List.copyOf(materializedViews);
        }
    }

    public record PartitionRange(LocalDate from, LocalDate to) {}
    public record BucketInfo(List<String> keys, int count) {
        public BucketInfo { keys = keys == null ? List.of() : List.copyOf(keys); }
    }
    public record PrefixDailyMetadata(String tradingDaySequenceColumn,
                                      Map<String, PrefixColumns> fields,
                                      GapPolicy suspensionGapPolicy,
                                      InsufficientWindowPolicy insufficientWindowPolicy) {
        public PrefixDailyMetadata { fields = fields == null ? Map.of() : Map.copyOf(fields); }
    }
    public record PrefixColumns(String cumulativeValueColumn, String cumulativeCountColumn) {}
    public enum GapPolicy { COUNT_VALID_OBSERVATIONS }
    public enum InsufficientWindowPolicy { STRICT_NULL, ALLOW_PARTIAL }
    public record FeatureMetadata(String version, String adjustmentVersion, String sourceSnapshot,
                                  LocalDate sourceSnapshotAsOf, Instant refreshedAt,
                                  Map<String, String> indicatorColumns) {
        public FeatureMetadata {
            if (version == null || version.isBlank() || adjustmentVersion == null || adjustmentVersion.isBlank()
                    || sourceSnapshot == null || sourceSnapshot.isBlank() || sourceSnapshotAsOf == null || refreshedAt == null)
                throw new IllegalArgumentException("Feature metadata is incomplete");
            indicatorColumns = indicatorColumns == null ? Map.of() : Map.copyOf(indicatorColumns);
        }
    }
    public record DorisCapabilities(String version, Map<String, Boolean> matrix) {
        public DorisCapabilities { matrix = matrix == null ? Map.of() : Map.copyOf(matrix); }
        public boolean supports(String name) { return Boolean.TRUE.equals(matrix.get(name)); }
    }
}
