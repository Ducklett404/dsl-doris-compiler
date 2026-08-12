package com.acme.dorisdsl.registry;

import com.acme.dorisdsl.ast.Ast;

import java.util.List;

public record RegistryConfig(
        Datasets datasets,
        List<FieldDefinition> fields,
        List<FunctionDefinition> functions
) {
    public RegistryConfig {
        fields = fields == null ? List.of() : List.copyOf(fields);
        functions = functions == null ? List.of() : List.copyOf(functions);
    }

    public record Datasets(String quoteTable, String financialTable, String calendarTable, String featureTable) {}
    public record FieldDefinition(String name, Ast.DataType type, String sourceSql, String version,
                                  String description, String signature, List<String> boundaryTests) {
        public FieldDefinition {
            boundaryTests = boundaryTests == null ? List.of() : List.copyOf(boundaryTests);
        }
    }
    public record FunctionDefinition(
            String name,
            int minArgs,
            int maxArgs,
            Ast.DataType returnType,
            LoweringKind loweringKind,
            String sqlTemplate,
            String featureColumn,
            FinancialMetadata financialMetadata,
            Integer lookbackArg,
            List<String> requiredFields,
            String version,
            String description,
            String signature,
            List<String> boundaryTests
    ) {
        public FunctionDefinition {
            requiredFields = requiredFields == null ? List.of() : List.copyOf(requiredFields);
            boundaryTests = boundaryTests == null ? List.of() : List.copyOf(boundaryTests);
        }
    }

    public record FinancialMetadata(String visibleFromColumn, String visibleToColumn, String reportPeriodColumn) {}

    public enum LoweringKind {
        COLUMN, WINDOW_AVG, WINDOW_EMA, WINDOW_STDDEV, RETURN_N, RSI,
        CROSS_UP, CROSS_DOWN, RANK_BY, PERCENTILE_RANK, TEMPLATE
    }
}
