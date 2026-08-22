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
    public record FieldDefinition(String name, Ast.DataType type, String sourceSql) {}
    public record FunctionDefinition(
            String name,
            int minArgs,
            int maxArgs,
            Ast.DataType returnType,
            LoweringKind loweringKind,
            String sqlTemplate,
            String featureColumn,
            Integer lookbackArg,
            List<String> requiredFields
    ) {
        public FunctionDefinition {
            requiredFields = requiredFields == null ? List.of() : List.copyOf(requiredFields);
        }
    }

    public enum LoweringKind { COLUMN, WINDOW_AVG, CROSS_UP, RANK_BY, TEMPLATE }
}
