package com.acme.dorisdsl.registry;

import com.acme.dorisdsl.ast.Ast;

import java.util.List;

public record RegistryConfig(
        String id,
        String version,
        String signature,
        String minCompilerVersion,
        String maxCompilerVersion,
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
            String id,
            String version,
            Signature signature,
            int minArgs,
            int maxArgs,
            Ast.DataType returnType,
            List<String> requiredFields,
            WindowSpecMetadata windowSpec,
            AdjustmentRequirement adjustmentRequirement,
            NullPolicy nullPolicy,
            LoweringKind loweringKind,
            String sqlTemplate,
            String irBuilder,
            String featureColumn,
            FinancialMetadata financialMetadata,
            Integer lookbackArg,
            Capabilities capabilities,
            List<TestVector> tests,
            String description,
            List<String> boundaryTests
    ) {
        public FunctionDefinition {
            requiredFields = requiredFields == null ? List.of() : List.copyOf(requiredFields);
            tests = tests == null ? List.of() : List.copyOf(tests);
            boundaryTests = boundaryTests == null ? List.of() : List.copyOf(boundaryTests);
            int signatureMin = signature == null ? minArgs : signature.minArgs();
            int signatureMax = signature == null ? maxArgs : signature.maxArgs();
            minArgs = signatureMin;
            maxArgs = signatureMax;
        }
    }

    public record FinancialMetadata(String visibleFromColumn, String visibleToColumn, String reportPeriodColumn) {}
    public record Signature(List<Argument> arguments, Ast.DataType returnType) {
        public Signature { arguments = arguments == null ? List.of() : List.copyOf(arguments); }
        int minArgs() { return (int) arguments.stream().filter(argument -> argument.defaultValue() == null).count(); }
        int maxArgs() { return arguments.size(); }
    }
    public record Argument(String name, Ast.DataType type, Object defaultValue) {}
    public record WindowSpecMetadata(int lengthArg, String unit, List<String> partitionKeys, List<String> orderKeys,
                                     NullPolicy nullPolicy, boolean requireFullWindow) {
        public WindowSpecMetadata {
            partitionKeys = partitionKeys == null ? List.of("symbol") : List.copyOf(partitionKeys);
            orderKeys = orderKeys == null ? List.of("trade_date") : List.copyOf(orderKeys);
        }
    }
    public record Capabilities(String minDorisVersion, List<String> requiredTables, List<String> requiredFunctions) {
        public Capabilities {
            requiredTables = requiredTables == null ? List.of() : List.copyOf(requiredTables);
            requiredFunctions = requiredFunctions == null ? List.of() : List.copyOf(requiredFunctions);
        }
    }
    public record TestVector(String dsl, String expectedSqlContains) {}

    public enum AdjustmentRequirement { NONE, FORWARD, BACKWARD, ANY }
    public enum NullPolicy { STRICT_FULL_WINDOW, ALLOW_PARTIAL_WINDOW }
    public enum LoweringKind {
        COLUMN, WINDOW_AVG, WINDOW_EMA, WINDOW_STDDEV, RETURN_N, RSI,
        CROSS_UP, CROSS_DOWN, RANK_BY, PERCENTILE_RANK, TEMPLATE
    }
}
