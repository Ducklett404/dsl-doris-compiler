package com.acme.dorisdsl.competition;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.util.JsonSupport;
import com.fasterxml.jackson.databind.JsonNode;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Team-reviewed mappings only. The compiler ships no guessed organizer indicator mappings. */
public final class VerifiedIndicatorCatalog {
    public enum Unit { NUMBER, PERCENT }

    /** Deliberately finite: no user-supplied SQL identifier reaches the generator. */
    public enum Column {
        LAST_PX("lastPx"), CLOSE_PX("closePx"), OPEN_PX("openPx"), HIGH_PX("highPx"),
        LOW_PX("lowPx"), VOLUME("volume"), TURNOVER("turnover"), TURN_RATIO("turnRatio"),
        PE_TTM("pETTM");

        private final String sqlName;
        Column(String sqlName) { this.sqlName = sqlName; }
        public String sqlName() { return sqlName; }
        public boolean storesInt32() { return this == TURN_RATIO; }
    }

    /** rawPerDisplayUnit converts a DSL threshold into the integer stored by Doris. */
    public record Metric(String name, List<String> aliases, Column column, Unit unit,
                         BigDecimal rawPerDisplayUnit, String evidence) {
        public Metric {
            if (name == null || name.isBlank() || column == null || unit == null
                    || rawPerDisplayUnit == null || rawPerDisplayUnit.signum() <= 0
                    || evidence == null || evidence.isBlank())
                throw new IllegalArgumentException("Verified metric needs name, column, unit, positive scale and evidence");
            aliases = List.copyOf(aliases == null ? List.of() : aliases);
            for (String alias : aliases)
                if (alias == null || alias.isBlank()) throw new IllegalArgumentException("Blank indicator alias");
        }
    }

    private final Map<String, Metric> byName;

    public VerifiedIndicatorCatalog(List<Metric> metrics) {
        Map<String, Metric> names = new HashMap<>();
        for (Metric metric : metrics) {
            register(names, metric.name(), metric);
            for (String alias : metric.aliases()) register(names, alias, metric);
        }
        byName = Map.copyOf(names);
    }

    private static void register(Map<String, Metric> names, String name, Metric metric) {
        if (names.putIfAbsent(name, metric) != null)
            throw new IllegalArgumentException("Duplicate indicator or alias: " + name);
    }

    public Metric require(String name, SlotAst.Span span) {
        Metric metric = byName.get(name);
        if (metric == null)
            throw new CompileException("DSL_INDICATOR_UNVERIFIED", "Indicator is not in the verified catalog: " + name,
                    span.line(), span.column());
        return metric;
    }

    /** Explicit VERIFIED status records a human review claim; it is not evidence of live Doris contents. */
    public static VerifiedIndicatorCatalog load(Path path) throws IOException {
        JsonNode root = JsonSupport.MAPPER.readTree(path.toFile());
        if (root.path("version").asInt(-1) != 1
                || !"VERIFIED".equals(root.path("status").asText())
                || !"newzl.hsj_stock_hq_basic".equals(root.path("table").asText())
                || !root.path("mappings").isArray())
            throw new IllegalArgumentException("Catalog requires version 1, VERIFIED status, basic table and mappings array");
        List<Metric> metrics = new java.util.ArrayList<>();
        for (JsonNode item : root.path("mappings")) {
            List<String> aliases = new java.util.ArrayList<>();
            if (item.has("aliases")) {
                if (!item.path("aliases").isArray()) throw new IllegalArgumentException("aliases must be an array");
                for (JsonNode alias : item.path("aliases")) aliases.add(alias.asText());
            }
            try {
                metrics.add(new Metric(item.path("name").asText(), aliases,
                        Column.valueOf(item.path("column").asText()),
                        Unit.valueOf(item.path("unit").asText()),
                        new BigDecimal(item.path("rawPerDisplayUnit").asText()),
                        item.path("evidence").asText()));
            } catch (RuntimeException e) {
                throw new IllegalArgumentException("Invalid verified mapping: " + item.path("name").asText(), e);
            }
        }
        return new VerifiedIndicatorCatalog(metrics);
    }
}
