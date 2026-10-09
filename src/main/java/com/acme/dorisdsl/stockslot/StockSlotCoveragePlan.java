package com.acme.dorisdsl.stockslot;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

/** Availability of computed inputs before user predicates, ranking and limits. */
public record StockSlotCoveragePlan(String sql, String samplesSql, List<Object> bindings,
                                    LocalDate evaluationDate, List<Input> inputs, boolean extensionRequired, String combinedSql) {
    public StockSlotCoveragePlan {
        bindings = List.copyOf(bindings);
        inputs = List.copyOf(inputs);
    }
    public record Input(String function, String indicator, String alias, String inputId, String window,
                        String role, int requiredObservations,
                        @com.fasterxml.jackson.annotation.JsonIgnore StockSlotAst.Expr expression, int horizon) {
        public Input(String function, String indicator, String alias, StockSlotAst.Expr expression, String role, int horizon) {
            this(function, indicator, alias, "", "", role, 0, expression, horizon);
        }
    }

    static StockSlotCoveragePlan create(String prefix, List<Object> values, String source,
                                        LocalDate date, List<Input> inputs, StockSlotRegistry registry, boolean extension) {
        // Repeated expressions may have different SQL aliases. Availability is a
        // semantic input identity, not an occurrence count; retain the first alias.
        var unique = new java.util.LinkedHashMap<String, Input>();
        for (Input input : inputs) {
            var described = StockSlotAvailabilityDiagnostics.describe(input, registry, date);
            unique.putIfAbsent(described.inputId(), described);
        }
        inputs = unique.values().stream().sorted(java.util.Comparator.comparing(Input::alias)
                .thenComparing(Input::function).thenComparing(Input::indicator)).toList();
        var bindings = new ArrayList<>(values);
        String from = " FROM " + source + " cov";
        String missing = "0";
        if (extension) {
            from += " LEFT JOIN " + registry.table("extension").qualifiedName() + " cx ON cx."
                    + registry.field("extension", "marketCode") + "=cov.mktcode AND cx."
                    + registry.field("extension", "securityCode") + "=cov.tgtcode AND cx."
                    + registry.field("extension", "tradeDate") + "=?";
            bindings.add(date);
            missing = "CASE WHEN cx." + registry.field("extension", "securityCode") + " IS NULL THEN 1 ELSE 0 END";
        }
        var counts = new StringBuilder(prefix).append("\nSELECT COUNT(*),COALESCE(SUM(").append(missing).append("),0)");
        var samples = new StringBuilder(prefix).append("\nSELECT cov.mktcode,cov.tgtcode,").append(missing);
        var unavailable = new ArrayList<String>();
        for (Input input : inputs) {
            String test = "cov.`" + input.alias() + "` IS NULL";
            counts.append(",COALESCE(SUM(CASE WHEN ").append(test).append(" THEN 1 ELSE 0 END),0)");
            samples.append(",CASE WHEN ").append(test).append(" THEN 1 ELSE 0 END");
            unavailable.add(test);
        }
        if (extension) unavailable.add("(" + missing + ")=1");
        samples.append(from).append(" WHERE ").append(unavailable.isEmpty() ? "FALSE" : String.join(" OR ", unavailable))
                .append(" ORDER BY cov.mktcode,cov.tgtcode LIMIT 20;");
        // One history evaluation supplies both totals and the first 20 unavailable securities.
        // Rank unavailable rows first; keep one zero-valued row even for an empty universe.
        var combined = new StringBuilder(prefix).append(",\ncoverage_flags AS (\n  SELECT cov.mktcode,cov.tgtcode,")
                .append(missing).append(" AS ext_missing");
        for (int i = 0; i < inputs.size(); i++) combined.append(",CASE WHEN cov.`").append(inputs.get(i).alias())
                .append("` IS NULL THEN 1 ELSE 0 END AS u").append(i);
        combined.append(from).append("\n),\ncoverage_totals AS (\n  SELECT coverage_flags.*,COUNT(*) OVER () AS observed,")
                .append("SUM(ext_missing) OVER () AS missing");
        for (int i = 0; i < inputs.size(); i++) combined.append(",SUM(u").append(i).append(") OVER () AS n").append(i);
        var flags = new ArrayList<String>(); flags.add("ext_missing=1");
        for (int i = 0; i < inputs.size(); i++) flags.add("u" + i + "=1");
        combined.append(",ROW_NUMBER() OVER (ORDER BY CASE WHEN ").append(String.join(" OR ", flags))
                .append(" THEN 0 ELSE 1 END,mktcode,tgtcode) AS sample_rank\n  FROM coverage_flags\n)\n")
                .append("SELECT COALESCE(d.observed,0),COALESCE(d.missing,0)");
        for (int i = 0; i < inputs.size(); i++) combined.append(",COALESCE(d.n").append(i).append(",0)");
        combined.append(",d.mktcode,d.tgtcode,d.ext_missing");
        for (int i = 0; i < inputs.size(); i++) combined.append(",d.u").append(i);
        combined.append("\nFROM (SELECT 1 AS seed) s LEFT JOIN (SELECT * FROM coverage_totals WHERE sample_rank<=20) d ON TRUE\nORDER BY d.sample_rank;");
        return new StockSlotCoveragePlan(counts.append(from).append(';').toString(), samples.toString(), bindings,
                date, inputs, extension, combined.toString());
    }

    static Input describe(StockSlotAst.FunctionCall call, String alias, StockSlotAst.SemanticModel model) {
        String indicator = model.calls().stream().filter(c -> c.span().equals(call.span()))
                .flatMap(c -> c.slots().stream()).filter(s -> s.name().startsWith("indicator_name"))
                .map(StockSlotAst.SlotSemantics::rawValue).filter(s -> !s.isEmpty()).distinct()
                .collect(java.util.stream.Collectors.joining(" / "));
        return new Input(call.name(), indicator, alias, call, "VALUE", 0);
    }
}
