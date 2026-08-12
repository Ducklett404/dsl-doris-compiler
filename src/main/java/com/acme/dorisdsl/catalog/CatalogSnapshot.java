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
        FeatureMetadata feature,
        DorisCapabilities doris
) {
    public CatalogSnapshot {
        if (version == null || version.isBlank()) throw new IllegalArgumentException("Catalog version is required");
        if (capturedAt == null || tables == null || feature == null || doris == null)
            throw new IllegalArgumentException("Catalog snapshot is incomplete");
        tableMetadata = tableMetadata == null ? Map.of() : Map.copyOf(tableMetadata);
    }

    public record TableMappings(String detailTable, String financialPitTable, String calendarTable,
                                String featureTable, String prefixSumTable) {}

    public record TableMetadata(PartitionRange partitionRange, long estimatedRows, BucketInfo bucketInfo,
                                List<String> indexes, List<String> materializedViews) {
        public TableMetadata {
            indexes = indexes == null ? List.of() : List.copyOf(indexes);
            materializedViews = materializedViews == null ? List.of() : List.copyOf(materializedViews);
        }
    }

    public record PartitionRange(LocalDate from, LocalDate to) {}

    public record BucketInfo(List<String> keys, int count) {
        public BucketInfo { keys = keys == null ? List.of() : List.copyOf(keys); }
    }

    public record FeatureMetadata(String version, Instant refreshedAt) {}

    public record DorisCapabilities(String version, Map<String, Boolean> matrix) {
        public DorisCapabilities { matrix = matrix == null ? Map.of() : Map.copyOf(matrix); }
        public boolean supports(String capability) { return Boolean.TRUE.equals(matrix.get(capability)); }
    }
}
