package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.CompileException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class StockSlotRegistryLoader {
    public static final String DEFAULT_RESOURCE = "/stock-slot-registry-v1.json";
    private static final Pattern IDENTIFIER = Pattern.compile("^[A-Za-z_][A-Za-z0-9_]*$");
    private static final Pattern QUALIFIED_NAME = Pattern.compile("^[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?$");
    private static final Pattern PLACEHOLDER = Pattern.compile("\\{([A-Za-z_][A-Za-z0-9_]*)}");
    private static final Pattern SAFE_DECIMAL = Pattern.compile("^(?:0|[1-9]\\d*)(?:\\.\\d+)?$");
    private static final Set<String> AGGREGATIONS = Set.of("", "MAX", "MIN", "AVG", "SUM");
    private static final Set<String> TIME_GRAINS = Set.of("TRADING_DAY", "CROSS_SECTION");
    private static final Set<String> ADJUSTMENTS = Set.of("NONE", "QFQ", "HFQ", "SOURCE_DEFINED");
    private static final Set<String> NULL_POLICIES = Set.of(
            "PRESERVE", "STRICT_NO_IMPUTATION", "EXCLUDE_NULL_METRIC", "IGNORE_NULL_INPUTS",
            "NULL_IF_TARGET_MISSING", "NULL_IF_INDUSTRY_MISSING");

    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);

    public StockSlotRegistry loadDefault() {
        try (InputStream input = StockSlotRegistryLoader.class.getResourceAsStream(DEFAULT_RESOURCE)) {
            if (input == null) throw invalid("REGISTRY_IO", "Missing " + DEFAULT_RESOURCE);
            return load(input);
        } catch (IOException e) {
            throw invalid("REGISTRY_IO", e.getMessage());
        }
    }

    public StockSlotRegistry load(Path path) {
        try (InputStream input = Files.newInputStream(path)) {
            return load(input);
        } catch (IOException e) {
            throw invalid("REGISTRY_IO", "Cannot read registry: " + e.getMessage());
        }
    }

    public StockSlotRegistry load(InputStream input) {
        try {
            StockSlotRegistryConfig config = mapper.readValue(input, StockSlotRegistryConfig.class);
            validate(config);
            StockSlotRegistry registry = new StockSlotRegistry(config);
            validatePositiveVectors(registry);
            return registry;
        } catch (CompileException e) {
            throw e;
        } catch (JsonProcessingException e) {
            throw invalid("REGISTRY_SCHEMA", e.getOriginalMessage());
        } catch (IOException e) {
            throw invalid("REGISTRY_IO", e.getMessage());
        }
    }

    private void validate(StockSlotRegistryConfig config) {
        require(config.registryVersion() != null && !config.registryVersion().isBlank(), "REGISTRY_INVALID", "registryVersion is required");
        require(!config.tables().isEmpty(), "REGISTRY_INVALID", "tables are required");
        for (var entry : config.tables().entrySet()) {
            String key = entry.getKey();
            var table = entry.getValue();
            identifier(key, "table key");
            require(table != null, "REGISTRY_INVALID", "Null table: " + key);
            require(QUALIFIED_NAME.matcher(table.qualifiedName()).matches(), "REGISTRY_UNSAFE_TABLE", "Unsafe or dynamic table name: " + table.qualifiedName());
            identifier(table.alias(), "table alias");
            require(table.grain() != null && !table.grain().isBlank(), "REGISTRY_INVALID", "Missing grain for table " + key);
            require(!table.fields().isEmpty(), "REGISTRY_INVALID", "Missing fields for table " + key);
            table.fields().forEach((logical, physical) -> { identifier(logical, "logical field"); identifier(physical, "physical field"); });
            for (String joinKey : table.joinKeys())
                require(table.fields().containsKey(joinKey), "REGISTRY_REFERENCE", "Unknown join key " + key + "." + joinKey);
        }
        require(config.tables().containsKey("basic") && config.tables().containsKey("extension") && config.tables().containsKey("code"),
                "REGISTRY_REFERENCE", "tables basic, extension and code are required");
        require(config.markets() != null && !config.markets().isEmpty(), "REGISTRY_INVALID", "markets are required");
        require(config.recognizedMarkets() != null && config.recognizedMarkets().containsAll(config.markets().keySet()),
                "REGISTRY_INVALID", "recognizedMarkets must include every executable market");
        require(config.aggregations() != null && config.aggregations().containsAll(AGGREGATIONS),
                "REGISTRY_INVALID", "aggregations must include the executable aggregation vocabulary");

        Set<String> indicatorNames = new HashSet<>();
        for (var indicator : config.indicators()) {
            require(indicator != null && indicator.name() != null && !indicator.name().isBlank(), "REGISTRY_INVALID", "Indicator name is required");
            unique(indicatorNames, indicator.name(), "indicator");
            for (String alias : indicator.aliases()) unique(indicatorNames, alias, "indicator alias");
            validateIndicatorMetadata(indicator.valueType(), indicator.unit(), indicator.allowedAggregations(),
                    indicator.timeGrain(), indicator.maxLookback(), indicator.adjustment(), indicator.nullPolicy(), indicator.scale());
            require(indicator.source() != null, "REGISTRY_REFERENCE", "Source is required for " + indicator.name());
            var table = config.tables().get(indicator.source().table());
            require(table != null, "REGISTRY_REFERENCE", "Unknown source table for " + indicator.name());
            require(table.fields().containsKey(indicator.source().field()), "REGISTRY_REFERENCE", "Unknown source field for " + indicator.name());
            for (String field : indicator.source().requiredFields())
                require(table.fields().containsKey(field), "REGISTRY_REFERENCE", "Unknown required field " + field + " for " + indicator.name());
            validateIndicatorLowering(indicator.lowering(), indicator.sentinelValues(), indicator.name());
        }

        Set<String> patternNames = new HashSet<>();
        for (var indicator : config.indicatorPatterns()) {
            unique(patternNames, indicator.name(), "indicator pattern");
            try { Pattern.compile(indicator.pattern()); }
            catch (RuntimeException e) { throw invalid("REGISTRY_PATTERN", "Invalid indicator pattern " + indicator.name()); }
            validateIndicatorMetadata(indicator.valueType(), indicator.unit(), indicator.allowedAggregations(),
                    indicator.timeGrain(), indicator.maxLookback(), indicator.adjustment(), indicator.nullPolicy(),
                    new StockSlotRegistryConfig.Scale(BigDecimal.ONE, BigDecimal.ONE));
            require(Set.of(StockSlotRegistryConfig.LoweringKind.WINDOW_AVG, StockSlotRegistryConfig.LoweringKind.RSI)
                    .contains(indicator.lowering().kind()), "REGISTRY_LOWERING", "Invalid pattern lowering for " + indicator.name());
            require(indicator.lowering().expressionTemplate() == null, "REGISTRY_UNSAFE_TEMPLATE", "Pattern lowering cannot contain SQL templates");
            require(indicator.lowering().parameters().containsKey("N"), "REGISTRY_PATTERN", "Pattern " + indicator.name() + " requires named group N");
            require(indicator.pattern().contains("?<N>"), "REGISTRY_PATTERN", "Pattern " + indicator.name() + " must declare named group N");
            Set<String> patternKeys = indicator.lowering().parameters().keySet();
            require((patternKeys.equals(Set.of("N", "baseIndicator"))
                            || patternKeys.equals(Set.of("N", "baseIndicator", "featureWindow", "featureTable", "featureField"))
                            || patternKeys.equals(Set.of("N", "baseIndicator", "featureWindow", "featureTable", "featureField", "featureDate", "featureSnapshotId")))
                            && indicator.lowering().parameters().get("N").equals("capture")
                            && indicatorNames.contains(indicator.lowering().parameters().get("baseIndicator")),
                    "REGISTRY_PATTERN", "Pattern lowering requires N=capture and a registered baseIndicator");
            if (indicator.lowering().parameters().containsKey("featureTable")) {
                String tableKey = indicator.lowering().parameters().get("featureTable");
                var featureTable = config.tables().get(tableKey);
                require(featureTable != null && featureTable.fields().containsKey(indicator.lowering().parameters().get("featureField")),
                        "REGISTRY_REFERENCE", "Unknown performance feature table/field for " + indicator.name());
                require(indicator.lowering().parameters().get("featureWindow").matches("[1-9]\\d*"),
                        "REGISTRY_RANGE", "Invalid featureWindow for " + indicator.name());
                if (patternKeys.contains("featureDate")) {
                    try { java.time.LocalDate.parse(indicator.lowering().parameters().get("featureDate")); }
                    catch (RuntimeException e) { throw invalid("REGISTRY_RANGE", "Invalid featureDate"); }
                    require(indicator.lowering().parameters().get("featureSnapshotId").matches("[A-Za-z0-9_.-]{1,128}"),
                            "REGISTRY_RANGE", "Invalid featureSnapshotId");
                }
            }
        }

        Set<String> functionNames = new HashSet<>();
        for (var function : config.functions()) {
            require(function != null && function.name() != null && !function.name().isBlank(), "REGISTRY_INVALID", "Function name is required");
            unique(functionNames, function.name().toLowerCase(Locale.ROOT), "function");
            identifier(function.name(), "function name");
            require(function.returnType() != null, "REGISTRY_TYPE", "Return type is required for " + function.name());
            require(TIME_GRAINS.contains(function.timeGrain()), "REGISTRY_TYPE", "Invalid time grain for " + function.name());
            require(function.maxLookback() >= 1 && function.maxLookback() <= 5000, "REGISTRY_RANGE", "Invalid maxLookback for " + function.name());
            require(NULL_POLICIES.contains(function.nullPolicy()), "REGISTRY_TYPE", "Invalid null policy for " + function.name());
            require(function.lowering() != null && function.lowering().kind() != null, "REGISTRY_LOWERING", "Lowering is required for " + function.name());
            require(function.lowering().expressionTemplate() == null, "REGISTRY_UNSAFE_TEMPLATE", "Function lowering cannot contain SQL templates");
            Set<String> parameters = new HashSet<>();
            for (var parameter : function.parameters()) {
                identifier(parameter.name(), "parameter");
                unique(parameters, parameter.name(), "parameter");
                require(parameter.type() != null, "REGISTRY_TYPE", "Parameter type is required for " + function.name());
            }
            if (function.returnTypeFromParameter() != null) {
                require(parameters.contains(function.returnTypeFromParameter()), "REGISTRY_REFERENCE", "Unknown returnTypeFromParameter for " + function.name());
                require(function.parameters().stream().anyMatch(p -> p.name().equals(function.returnTypeFromParameter())
                                && p.type() == StockSlotRegistryConfig.ParameterType.INDICATOR),
                        "REGISTRY_TYPE", "returnTypeFromParameter must reference an INDICATOR parameter for " + function.name());
            }
            validateFunctionParameters(function);
            validateFunctionLoweringValues(function, indicatorNames);
        }
        require(config.testVectors() != null && !config.testVectors().positive().isEmpty() && !config.testVectors().negative().isEmpty(),
                "REGISTRY_TEST_VECTOR", "At least one positive and one negative test vector are required");
        for (var vector : config.testVectors().negative())
            require(vector.id() != null && vector.mutation() != null && vector.expectedCode() != null,
                    "REGISTRY_TEST_VECTOR", "Incomplete negative test vector");
    }

    private void validateIndicatorMetadata(StockSlotAst.ValueType type, String unit, List<String> aggregations,
                                           String grain, int maxLookback, String adjustment, String nullPolicy,
                                           StockSlotRegistryConfig.Scale scale) {
        require(type != null, "REGISTRY_TYPE", "Indicator type is required");
        require(unit != null && !unit.isBlank(), "REGISTRY_TYPE", "Indicator unit is required");
        require(aggregations != null && !aggregations.isEmpty() && aggregations.stream().allMatch(AGGREGATIONS::contains),
                "REGISTRY_TYPE", "Invalid or empty allowedAggregations");
        require(TIME_GRAINS.contains(grain), "REGISTRY_TYPE", "Invalid time grain: " + grain);
        require(maxLookback >= 1 && maxLookback <= 5000, "REGISTRY_RANGE", "maxLookback must be 1..5000");
        require(ADJUSTMENTS.contains(adjustment), "REGISTRY_TYPE", "Invalid adjustment: " + adjustment);
        require(NULL_POLICIES.contains(nullPolicy), "REGISTRY_TYPE", "Invalid null policy: " + nullPolicy);
        require(scale != null && scale.multiply() != null && scale.divide() != null
                        && scale.multiply().signum() > 0 && scale.divide().signum() > 0,
                "REGISTRY_SCALE", "Scale multiply/divide must be positive");
    }

    private void validateIndicatorLowering(StockSlotRegistryConfig.Lowering lowering, List<BigDecimal> sentinels, String owner) {
        require(lowering != null && lowering.kind() == StockSlotRegistryConfig.LoweringKind.FIELD,
                "REGISTRY_LOWERING", "Exact indicator must use FIELD lowering: " + owner);
        String template = lowering.expressionTemplate();
        require(template != null, "REGISTRY_TEMPLATE", "Expression template is required for " + owner);
        rejectSql(template, owner);
        Set<String> placeholders = placeholders(template);
        require(Set.of("alias", "field", "sentinel").containsAll(placeholders), "REGISTRY_UNKNOWN_PLACEHOLDER", "Unknown placeholder in " + owner);
        if (template.equals("{alias}.{field}")) require(placeholders.equals(Set.of("alias", "field")), "REGISTRY_TEMPLATE", "Invalid FIELD template");
        else if (template.equals("NULLIF({alias}.{field},{sentinel})")) {
            require(placeholders.equals(Set.of("alias", "field", "sentinel")) && sentinels.size() == 1,
                    "REGISTRY_SENTINEL", "NULLIF lowering requires one sentinel for " + owner);
        } else throw invalid("REGISTRY_UNSAFE_TEMPLATE", "Uncontrolled SQL template for " + owner);
        require(lowering.parameters().isEmpty(), "REGISTRY_UNKNOWN_PARAMETER", "FIELD lowering does not accept template parameters");
    }

    private void validateFunctionParameters(StockSlotRegistryConfig.FunctionDefinition function) {
        Set<String> names = function.parameters().stream().map(StockSlotRegistryConfig.ParameterDefinition::name).collect(java.util.stream.Collectors.toSet());
        List<String> required = switch (function.lowering().kind()) {
            case INDICATOR -> List.of("market", "filter_scope", "indicator_name", "date", "select_type", "agg_func", "count_exp");
            case RANK -> List.of("market", "filter_scope", "indicator_name", "direction", "date", "select_type", "agg_func", "count_exp");
            case QUERY_DATA -> List.of("market", "keywords", "indicator_name", "date", "agg_func");
            case RANGE_WINDOW -> List.of("market", "filter_scope", "indicator_name", "period", "date", "select_type", "agg_func", "count_exp");
            case PAIR_WINDOW -> List.of("market", "filter_scope", "indicator_name_1", "indicator_name_2", "date", "select_type", "count_exp");
            case INDUSTRY_AGGREGATE -> List.of("market", "filter_scope", "indicator_name", "date", "agg_func");
            default -> throw invalid("REGISTRY_LOWERING", "Invalid function lowering: " + function.lowering().kind());
        };
        List<String> actual = function.parameters().stream().map(StockSlotRegistryConfig.ParameterDefinition::name).toList();
        require(actual.equals(required) && names.equals(Set.copyOf(required)),
                "REGISTRY_SIGNATURE", "Signature does not match lowering " + function.lowering().kind() + " for " + function.name());
        for (var parameter : function.parameters())
            require(parameter.type() == expectedParameterType(parameter.name()), "REGISTRY_SIGNATURE",
                    "Wrong type for " + function.name() + "." + parameter.name());
        Set<String> allowedParameters = switch (function.lowering().kind()) {
            case RANGE_WINDOW -> Set.of("mode", "defaultIndicator");
            case PAIR_WINDOW -> Set.of("mode", "threshold");
            case INDUSTRY_AGGREGATE -> Set.of("defaultAggregation");
            case RANK -> Set.of("defaultMethod");
            default -> Set.of();
        };
        require(allowedParameters.containsAll(function.lowering().parameters().keySet()),
                "REGISTRY_UNKNOWN_PARAMETER", "Unknown lowering parameter for " + function.name());
    }

    private StockSlotRegistryConfig.ParameterType expectedParameterType(String name) {
        if (name.equals("market") || name.equals("filter_scope") || name.equals("select_type"))
            return StockSlotRegistryConfig.ParameterType.SET;
        if (name.startsWith("indicator_name")) return StockSlotRegistryConfig.ParameterType.INDICATOR;
        return switch (name) {
            case "keywords" -> StockSlotRegistryConfig.ParameterType.SECURITY;
            case "date" -> StockSlotRegistryConfig.ParameterType.DATE;
            case "period" -> StockSlotRegistryConfig.ParameterType.PERIOD;
            case "direction" -> StockSlotRegistryConfig.ParameterType.DIRECTION;
            case "agg_func" -> StockSlotRegistryConfig.ParameterType.AGGREGATION;
            case "count_exp" -> StockSlotRegistryConfig.ParameterType.COUNT_EXPRESSION;
            default -> throw invalid("REGISTRY_SIGNATURE", "Unknown parameter role: " + name);
        };
    }

    private void validateFunctionLoweringValues(StockSlotRegistryConfig.FunctionDefinition function, Set<String> indicatorNames) {
        Map<String, String> values = function.lowering().parameters();
        switch (function.lowering().kind()) {
            case RANGE_WINDOW -> {
                require(Set.of("MAX", "MIN", "POSITION").contains(values.get("mode")),
                        "REGISTRY_LOWERING", "Invalid range mode for " + function.name());
                require(indicatorNames.contains(values.get("defaultIndicator")),
                        "REGISTRY_REFERENCE", "Unknown defaultIndicator for " + function.name());
            }
            case PAIR_WINDOW -> {
                require(Set.of("CROSS_ABOVE", "CROSS_DOWN", "CLOSE_TOGETHER").contains(values.get("mode")),
                        "REGISTRY_LOWERING", "Invalid pair mode for " + function.name());
                if (values.containsKey("threshold"))
                    require(SAFE_DECIMAL.matcher(values.get("threshold")).matches(),
                            "REGISTRY_UNSAFE_TEMPLATE", "Unsafe threshold for " + function.name());
                require(values.get("mode").equals("CLOSE_TOGETHER") == values.containsKey("threshold"),
                        "REGISTRY_LOWERING", "threshold is required only for CLOSE_TOGETHER");
            }
            case INDUSTRY_AGGREGATE -> require(AGGREGATIONS.contains(values.get("defaultAggregation"))
                            && !values.get("defaultAggregation").isEmpty(),
                    "REGISTRY_LOWERING", "Invalid industry aggregation for " + function.name());
            case RANK -> require(Set.of("RANK", "DENSE_RANK", "ROW_NUMBER").contains(values.get("defaultMethod")),
                    "REGISTRY_LOWERING", "Invalid rank method for " + function.name());
            default -> require(values.isEmpty(), "REGISTRY_UNKNOWN_PARAMETER",
                    "Lowering parameters are not allowed for " + function.name());
        }
    }

    private void validatePositiveVectors(StockSlotRegistry registry) {
        for (var vector : registry.testVectors().positive()) {
            require(vector.id() != null && vector.kind() != null && vector.name() != null && vector.expected() != null,
                    "REGISTRY_TEST_VECTOR", "Incomplete positive test vector");
            switch (vector.kind()) {
                case "INDICATOR_EXPRESSION" -> require(registry.expression(registry.indicator(vector.name())).equals(vector.expected()),
                        "REGISTRY_TEST_VECTOR", "Positive vector mismatch: " + vector.id());
                case "FUNCTION_LOWERING" -> require(registry.function(vector.name()).lowering().kind().name().equals(vector.expected()),
                        "REGISTRY_TEST_VECTOR", "Positive vector mismatch: " + vector.id());
                default -> throw invalid("REGISTRY_TEST_VECTOR", "Unknown positive vector kind: " + vector.kind());
            }
        }
    }

    private Set<String> placeholders(String template) {
        Set<String> result = new HashSet<>();
        Matcher matcher = PLACEHOLDER.matcher(template);
        while (matcher.find()) result.add(matcher.group(1));
        return result;
    }

    private void rejectSql(String value, String owner) {
        String lower = value.toLowerCase(Locale.ROOT);
        if (value.contains(";") || value.contains("--") || value.contains("/*") || lower.matches(".*\\b(select|from|union|join|with)\\b.*"))
            throw invalid("REGISTRY_UNSAFE_TEMPLATE", "Unsafe SQL in " + owner);
    }

    private void identifier(String value, String owner) {
        require(value != null && IDENTIFIER.matcher(value).matches(), "REGISTRY_UNSAFE_IDENTIFIER", "Unsafe " + owner + ": " + value);
    }
    private void unique(Set<String> values, String value, String owner) {
        require(value != null && !value.isBlank() && values.add(value), "REGISTRY_DUPLICATE", "Duplicate " + owner + ": " + value);
    }
    private void require(boolean condition, String code, String message) { if (!condition) throw invalid(code, message); }
    private CompileException invalid(String code, String message) { return new CompileException(code, message, 1, 1); }
}
