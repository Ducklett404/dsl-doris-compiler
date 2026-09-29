package com.acme.dorisdsl.stockslot;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/** JSON contract for the executable stock-slot-v1 catalog. */
public record StockSlotRegistryConfig(
        String registryVersion,
        Map<String, TableDefinition> tables,
        Map<String, Integer> markets,
        List<String> recognizedMarkets,
        List<String> aggregations,
        List<IndicatorDefinition> indicators,
        List<IndicatorPatternDefinition> indicatorPatterns,
        List<FunctionDefinition> functions,
        TestVectors testVectors
) {
    public StockSlotRegistryConfig {
        tables = tables == null ? Map.of() : Map.copyOf(tables);
        markets = markets == null ? Map.of() : Map.copyOf(markets);
        recognizedMarkets = recognizedMarkets == null ? List.of() : List.copyOf(recognizedMarkets);
        aggregations = aggregations == null ? List.of() : List.copyOf(aggregations);
        indicators = indicators == null ? List.of() : List.copyOf(indicators);
        indicatorPatterns = indicatorPatterns == null ? List.of() : List.copyOf(indicatorPatterns);
        functions = functions == null ? List.of() : List.copyOf(functions);
    }

    public record TableDefinition(
            String qualifiedName,
            String alias,
            String grain,
            Map<String, String> fields,
            List<String> joinKeys
    ) {
        public TableDefinition {
            fields = fields == null ? Map.of() : Map.copyOf(fields);
            joinKeys = joinKeys == null ? List.of() : List.copyOf(joinKeys);
        }
    }

    public record IndicatorDefinition(
            String name,
            List<String> aliases,
            StockSlotAst.ValueType valueType,
            String unit,
            Scale scale,
            List<String> allowedAggregations,
            Source source,
            String timeGrain,
            int maxLookback,
            String adjustment,
            String nullPolicy,
            List<BigDecimal> sentinelValues,
            Lowering lowering
    ) {
        public IndicatorDefinition {
            aliases = aliases == null ? List.of() : List.copyOf(aliases);
            allowedAggregations = allowedAggregations == null ? List.of() : List.copyOf(allowedAggregations);
            sentinelValues = sentinelValues == null ? List.of() : List.copyOf(sentinelValues);
        }
    }

    public record IndicatorPatternDefinition(
            String name,
            String pattern,
            StockSlotAst.ValueType valueType,
            String unit,
            List<String> allowedAggregations,
            String timeGrain,
            int maxLookback,
            String adjustment,
            String nullPolicy,
            Lowering lowering
    ) {
        public IndicatorPatternDefinition {
            allowedAggregations = allowedAggregations == null ? List.of() : List.copyOf(allowedAggregations);
        }
    }

    public record FunctionDefinition(
            String name,
            List<ParameterDefinition> parameters,
            StockSlotAst.ValueType returnType,
            String returnTypeFromParameter,
            String timeGrain,
            int maxLookback,
            String nullPolicy,
            Lowering lowering
    ) {
        public FunctionDefinition {
            parameters = parameters == null ? List.of() : List.copyOf(parameters);
        }
    }

    public record ParameterDefinition(String name, ParameterType type, boolean allowEmpty) {}
    public enum ParameterType { STRING, SET, INDICATOR, DATE, DIRECTION, AGGREGATION, COUNT_EXPRESSION, PERIOD, SECURITY }

    public record Source(String table, String field, List<String> requiredFields) {
        public Source { requiredFields = requiredFields == null ? List.of() : List.copyOf(requiredFields); }
    }

    public record Scale(BigDecimal multiply, BigDecimal divide) {}

    public record Lowering(LoweringKind kind, String expressionTemplate, Map<String, String> parameters) {
        public Lowering { parameters = parameters == null ? Map.of() : Map.copyOf(parameters); }
    }

    public enum LoweringKind {
        FIELD, WINDOW_AVG, RSI,
        INDICATOR, RANK, QUERY_DATA, RANGE_WINDOW, PAIR_WINDOW, INDUSTRY_AGGREGATE
    }

    public record TestVectors(List<PositiveVector> positive, List<NegativeVector> negative) {
        public TestVectors {
            positive = positive == null ? List.of() : List.copyOf(positive);
            negative = negative == null ? List.of() : List.copyOf(negative);
        }
    }
    public record PositiveVector(String id, String kind, String name, String expected) {}
    public record NegativeVector(String id, String mutation, String expectedCode) {}
}
