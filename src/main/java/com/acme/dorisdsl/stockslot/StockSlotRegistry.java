package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.CompileException;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class StockSlotRegistry {
    private final String fingerprint;
    private final String version;
    private final Map<String, StockSlotRegistryConfig.TableDefinition> tables;
    private final Map<String, Integer> markets;
    private final Set<String> recognizedMarkets;
    private final Set<String> aggregations;
    private final Map<String, StockSlotRegistryConfig.IndicatorDefinition> indicators;
    private final List<CompiledPattern> indicatorPatterns;
    private final BoundedCache<String, ResolvedIndicator> resolvedIndicatorCache = new BoundedCache<>(512);
    private final Map<String, StockSlotRegistryConfig.FunctionDefinition> functions;
    private final StockSlotRegistryConfig.TestVectors testVectors;

    StockSlotRegistry(StockSlotRegistryConfig config) {
        try {
            byte[] canonical = com.acme.dorisdsl.util.JsonSupport.MAPPER.copy()
                    .enable(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
                    .writeValueAsBytes(config);
            fingerprint = java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(canonical));
        } catch (Exception e) { throw new IllegalArgumentException("Cannot fingerprint stock registry", e); }
        version = config.registryVersion();
        tables = config.tables();
        markets = config.markets();
        recognizedMarkets = Set.copyOf(config.recognizedMarkets());
        aggregations = Set.copyOf(config.aggregations());
        testVectors = config.testVectors();
        Map<String, StockSlotRegistryConfig.IndicatorDefinition> byName = new LinkedHashMap<>();
        for (var definition : config.indicators()) {
            byName.put(definition.name(), definition);
            for (String alias : definition.aliases()) byName.put(alias, definition);
        }
        indicators = Map.copyOf(byName);
        indicatorPatterns = config.indicatorPatterns().stream()
                .map(item -> new CompiledPattern(item, Pattern.compile(item.pattern(), Pattern.CASE_INSENSITIVE)))
                .toList();
        Map<String, StockSlotRegistryConfig.FunctionDefinition> byFunction = new LinkedHashMap<>();
        for (var definition : config.functions()) byFunction.put(definition.name().toLowerCase(Locale.ROOT), definition);
        functions = Map.copyOf(byFunction);
    }

    public String version() { return version; }
    public String fingerprint() { return fingerprint; }
    public Map<String, Integer> markets() { return markets; }
    public Set<String> recognizedMarkets() { return recognizedMarkets; }
    public StockSlotRegistryConfig.TestVectors testVectors() { return testVectors; }

    public StockSlotRegistryConfig.TableDefinition table(String key) {
        var value = tables.get(key);
        if (value == null) throw error("REGISTRY_REFERENCE", "Unknown table key: " + key);
        return value;
    }

    public StockSlotRegistryConfig.FunctionDefinition function(String name) {
        var value = functions.get(name.toLowerCase(Locale.ROOT));
        if (value == null) throw error("UNSUPPORTED_FUNCTION", "Unsupported stock-slot-v1 function: " + name);
        return value;
    }

    public ResolvedIndicator indicator(String name) {
        ResolvedIndicator cached = resolvedIndicatorCache.get(name);
        if (cached != null) return cached;
        var exact = indicators.get(name);
        if (exact != null) {
            ResolvedIndicator resolved = new ResolvedIndicator(exact, null, Map.of());
            resolvedIndicatorCache.put(name, resolved);
            return resolved;
        }
        for (CompiledPattern candidate : indicatorPatterns) {
            Matcher matcher = candidate.pattern.matcher(name);
            if (matcher.matches()) {
                Map<String, String> parameters = new LinkedHashMap<>();
                for (var parameter : candidate.definition.lowering().parameters().entrySet()) {
                    if (!parameter.getValue().equals("capture")) {
                        parameters.put(parameter.getKey(), parameter.getValue());
                        continue;
                    }
                    try { parameters.put(parameter.getKey(), matcher.group(parameter.getKey())); }
                    catch (IllegalArgumentException e) { throw error("REGISTRY_PATTERN", "Pattern does not expose parameter " + parameter.getKey()); }
                }
                ResolvedIndicator resolved = new ResolvedIndicator(null, candidate.definition, parameters);
                resolvedIndicatorCache.put(name, resolved);
                return resolved;
            }
        }
        throw error("EXECUTION_INDICATOR_UNSUPPORTED", "Indicator has no accepted data mapping: " + name);
    }

    public String field(String tableKey, String logicalField) {
        String value = table(tableKey).fields().get(logicalField);
        if (value == null) throw error("REGISTRY_REFERENCE", "Unknown field " + tableKey + "." + logicalField);
        return value;
    }

    public String column(String tableKey, String logicalField) {
        var table = table(tableKey);
        return table.alias() + "." + field(tableKey, logicalField);
    }

    public String expression(ResolvedIndicator resolved) {
        if (resolved.exact == null) throw error("REGISTRY_LOWERING", "Pattern indicators are lowered by their declared window kind");
        var indicator = resolved.exact;
        var source = indicator.source();
        var lowering = indicator.lowering();
        String alias = table(source.table()).alias();
        String field = field(source.table(), source.field());
        String expression = switch (lowering.expressionTemplate()) {
            case "{alias}.{field}" -> alias + "." + field;
            case "NULLIF({alias}.{field},{sentinel})" -> "NULLIF(" + alias + "." + field + "," + numeric(indicator.sentinelValues().getFirst()) + ")";
            default -> throw error("REGISTRY_TEMPLATE", "Template was not validated: " + lowering.expressionTemplate());
        };
        BigDecimal multiply = indicator.scale().multiply();
        BigDecimal divide = indicator.scale().divide();
        if (multiply.compareTo(BigDecimal.ONE) != 0 || divide.compareTo(BigDecimal.ONE) != 0)
            expression = "(" + expression + " * " + numeric(multiply) + " / " + numeric(divide) + ")";
        return expression;
    }

    public boolean requiresTable(ResolvedIndicator indicator, String tableKey) {
        return indicator.exact != null && indicator.exact.source().table().equals(tableKey);
    }

    public Set<String> allowedAggregations() {
        return aggregations;
    }

    public IndicatorCacheStats indicatorCacheStats() {
        var stats = resolvedIndicatorCache.stats();
        return new IndicatorCacheStats(stats.size(), stats.capacity(), stats.hits(), stats.misses());
    }

    private String numeric(BigDecimal value) { return value.stripTrailingZeros().toPlainString(); }
    private CompileException error(String code, String message) { return new CompileException(code, message, 1, 1); }

    public record ResolvedIndicator(
            StockSlotRegistryConfig.IndicatorDefinition exact,
            StockSlotRegistryConfig.IndicatorPatternDefinition pattern,
            Map<String, String> parameters
    ) {
        public ResolvedIndicator { parameters = Map.copyOf(parameters); }
        public StockSlotAst.ValueType valueType() { return exact != null ? exact.valueType() : pattern.valueType(); }
        public String name() { return exact != null ? exact.name() : pattern.name(); }
        public List<String> allowedAggregations() { return exact != null ? exact.allowedAggregations() : pattern.allowedAggregations(); }
        public int maxLookback() { return exact != null ? exact.maxLookback() : pattern.maxLookback(); }
        public StockSlotRegistryConfig.Lowering lowering() { return exact != null ? exact.lowering() : pattern.lowering(); }
    }

    public record IndicatorCacheStats(int size, int capacity, long hits, long misses) {}

    private record CompiledPattern(StockSlotRegistryConfig.IndicatorPatternDefinition definition, Pattern pattern) {}
}
