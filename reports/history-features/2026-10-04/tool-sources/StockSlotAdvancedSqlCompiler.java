package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.CompileException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Window-aware lowering for stock-slot-v1.  It is deliberately separate from the
 * single-day fast path so historical rows are never accidentally removed before
 * a window is evaluated.
 */
final class StockSlotAdvancedSqlCompiler {
    private static final Pattern CN_DATE = Pattern.compile("^(\\d{4})年(\\d{1,2})月(\\d{1,2})日$");
    private static final Pattern PERIOD = Pattern.compile("^(\\d+)日$");
    private static final Pattern ANCHORED_PERIOD = Pattern.compile("^(.+?)(?:近|前)(\\d+)日$");
    private static final Pattern MA = Pattern.compile("^(\\d+)日均线$");
    private static final Pattern RSI = Pattern.compile("^RSI\\((\\d+)\\)$", Pattern.CASE_INSENSITIVE);
    private static final Pattern COUNT = Pattern.compile("^(CONS|EXIST)(>=|=)(\\d+)日$");
    private static final Pattern RANGE = Pattern.compile("^([\\[(])\\s*(-?\\d+(?:\\.\\d+)?%?)\\s*,\\s*(-?\\d+(?:\\.\\d+)?%?)\\s*([\\])])$");
    private final StockSlotAst.SemanticModel model;
    private final StockSlotRegistry registry;
    private final boolean allowFeatureAccess;
    private final HistoricalExtremaFeatureCatalog historicalFeatures;
    private final String snapshotId;
    private final String manifestSha256;
    private String materializedMarketColumn;
    private final LinkedHashMap<String, RawMetric> rawMetrics = new LinkedHashMap<>();
    private final IdentityHashMap<StockSlotAst.FunctionCall, CallSpec> calls = new IdentityHashMap<>();
    private final List<CallSpec> featureCalls = new ArrayList<>();
    private final Map<String, HistoricalExtremum> historicalExtrema = new LinkedHashMap<>();
    private final LinkedHashMap<StockSlotAst.FunctionCall, RankSpec> ranks = new LinkedHashMap<>();
    private final Map<StockSlotAst.Expr, CountSpec> counts = new LinkedHashMap<>();
    private final Set<StockSlotAst.FunctionCall> countedCalls = java.util.Collections.newSetFromMap(new IdentityHashMap<>());
    private final List<StockSlotWindowContract> contracts = new ArrayList<>();
    private final List<StockSlotSqlArtifact.PlanNode> plan = new ArrayList<>();
    private final List<Object> bindings = new ArrayList<>();
    private final List<Object> featureBindings = new ArrayList<>();
    private LocalDate targetDate;
    private String market = "";
    private String scope = "";
    private boolean needsCode;
    private boolean needsExt;
    private boolean needsDelta;
    private boolean needsFeature;
    private boolean needsHistory;

    StockSlotAdvancedSqlCompiler(StockSlotAst.SemanticModel model, StockSlotRegistry registry, boolean allowFeatureAccess,
                                 HistoricalExtremaFeatureCatalog historicalFeatures, String snapshotId, String manifestSha256) {
        this.model = model;
        this.registry = registry;
        this.allowFeatureAccess = allowFeatureAccess;
        this.historicalFeatures = historicalFeatures;
        this.snapshotId = snapshotId;
        this.manifestSha256 = manifestSha256;
    }

    static boolean requiresAdvanced(StockSlotAst.SemanticModel model, StockSlotRegistry registry) {
        return hasAdvanced(model.document().expression(), registry);
    }

    private static boolean hasAdvanced(StockSlotAst.Expr expression, StockSlotRegistry registry) {
        return switch (expression) {
            case StockSlotAst.FunctionCall call -> {
                var kind = registry.function(call.name()).lowering().kind();
                boolean indicator = kind == StockSlotRegistryConfig.LoweringKind.INDICATOR;
                boolean rank = kind == StockSlotRegistryConfig.LoweringKind.RANK;
                if (!indicator && !rank) yield true;
                boolean advancedSlot = false;
                for (int i = 0; i < call.arguments().size(); i++) {
                    if (call.arguments().get(i) instanceof StockSlotAst.Literal literal
                            && literal.value() instanceof String text && !text.isEmpty()) {
                        if ((i == 1) || (indicator && i >= 4)
                                || (rank && (i >= 5 || (i == 3 && text.contains(":")))))
                            advancedSlot = true;
                        if (i == 2) {
                            try { if (registry.indicator(text).pattern() != null) advancedSlot = true; }
                            catch (RuntimeException ignored) { }
                        }
                        if ((indicator && i == 3 || rank && i == 4)
                                && ANCHORED_PERIOD.matcher(text).matches()) advancedSlot = true;
                    }
                }
                yield advancedSlot;
            }
            case StockSlotAst.Binary binary -> hasAdvanced(binary.left(), registry) || hasAdvanced(binary.right(), registry);
            case StockSlotAst.Unary unary -> hasAdvanced(unary.operand(), registry);
            default -> false;
        };
    }

    StockSlotSqlArtifact generate() {
        collect(model.document().expression());
        collectCounts(model.document().expression());
        if (needsFeature && needsHistory)
            fail("EXECUTION_FEATURE_MIXED", "Accelerated latest-date features cannot be mixed with historical window lowering");
        if (needsFeature && (needsExt || rawMetrics.values().stream()
                .anyMatch(raw -> !raw.metric.expression().startsWith(registry.table("features").alias() + "."))))
            fail("EXECUTION_FEATURE_MIXED", "Accelerated feature lookup cannot be mixed with raw-table indicators");
        if (targetDate == null) fail("EXECUTION_DATE_REQUIRED", "Window execution requires an explicit evaluation date");
        // Counts and mixed windows need extrema at every historical row.
        boolean aggregateHistory = allowFeatureAccess && counts.isEmpty() && ranks.isEmpty()
                && !needsDelta && !needsFeature && !uniqueCalls().isEmpty()
                && uniqueCalls().stream().allMatch(spec -> historicalExtrema.containsKey(spec.alias));
        boolean materializedHistory = aggregateHistory && historicalFeatures != null
                && historicalFeatures.matches(registry, snapshotId, manifestSha256, targetDate)
                && rawMetrics.values().stream().allMatch(raw -> historicalFeatures.columns(raw.metric.expression()) != null);
        if (materializedHistory) aggregateHistory = false;

        StockSlotAst.Expr pre = null;
        StockSlotAst.Expr post = model.document().expression();
        if (post instanceof StockSlotAst.Binary binary && binary.operator().equals("THEN")) {
            pre = binary.left();
            post = binary.right();
        }

        StringBuilder sql;
        if (materializedHistory) {
            sql = historicalFeatureSql();
        } else {
        var basic = registry.table("basic");
        var extension = registry.table("extension");
        var code = registry.table("code");
        String scanKey = needsFeature ? "features" : "basic";
        var scan = registry.table(scanKey);
        sql = new StringBuilder("WITH history AS (\n  SELECT ")
                .append(registry.column(scanKey, "marketCode")).append(" AS mktcode,")
                .append(registry.column(scanKey, "securityCode")).append(" AS tgtcode,")
                .append(registry.column(scanKey, "tradeDate")).append(" AS bizdate");
        if (needsCode) sql.append(',').append(registry.column("code", "name")).append(" AS name,")
                .append(registry.column("code", "industry")).append(" AS hyBlkRefName");
        rawMetrics.values().forEach(raw -> sql.append(",\n    ").append(raw.metric.expression()).append(" AS `").append(raw.alias).append('`'));
        if (aggregateHistory) {
            sql.append(",\n    CASE WHEN ").append(registry.column(scanKey, "tradeDate"))
                    .append(" = ? THEN 1 ELSE 0 END AS is_current");
            bindings.add(targetDate);
        }
        sql.append("\n  FROM ").append(scan.qualifiedName()).append(' ').append(scan.alias()).append("\n");
        if (needsCode) sql.append("  LEFT JOIN ").append(code.qualifiedName()).append(' ').append(code.alias())
                .append(" ON ").append(registry.column("code", "marketCode")).append('=').append(registry.column(scanKey, "marketCode"))
                .append(" AND ").append(registry.column("code", "securityCode")).append('=').append(registry.column(scanKey, "securityCode")).append("\n");
        if (needsExt) sql.append("  LEFT JOIN ").append(extension.qualifiedName()).append(' ').append(extension.alias())
                .append(" ON ").append(registry.column("extension", "marketCode")).append('=').append(registry.column("basic", "marketCode"))
                .append(" AND ").append(registry.column("extension", "securityCode")).append('=').append(registry.column("basic", "securityCode"))
                .append(" AND ").append(registry.column("extension", "tradeDate")).append('=').append(registry.column("basic", "tradeDate")).append("\n");
        sql.append("  WHERE ").append(registry.column(scanKey, "tradeDate")).append(needsFeature ? " = ?" : " <= ?");
        bindings.add(targetDate);
        String marketSql = marketPredicate(market);
        if (!marketSql.isEmpty()) sql.append("\n    AND ").append(marketSql);
        if (!scope.isEmpty() && !scope.equals("行业")) {
            needsCode = true;
            List<String> terms = split(scope, '|');
            sql.append("\n    AND c.hyBlkRefName IN (").append(String.join(",", terms.stream().map(x -> "?").toList())).append(')');
            bindings.addAll(terms);
        }
        sql.append("\n)");
        plan.add(new StockSlotSqlArtifact.PlanNode(needsFeature ? "FeatureScan" : "HistoryScan", scan.qualifiedName() + " through " + targetDate));
        if (needsCode) plan.add(new StockSlotSqlArtifact.PlanNode("CodeJoin", code.qualifiedName() + " on (mktcode,tgtcode)"));
        if (needsExt) plan.add(new StockSlotSqlArtifact.PlanNode("LeftJoin", extension.qualifiedName() + " on (mktcode,tgtcode,bizdate)"));

        String source = "history";
        if (needsDelta) {
            RawMetric close = rawMetric(metric("收盘价"));
            sql.append(",\ndeltas AS (\n  SELECT history.*, `").append(close.alias).append("` - LAG(`")
                    .append(close.alias).append("`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate) AS `price_delta`\n  FROM history\n)");
            source = "deltas";
            plan.add(new StockSlotSqlArtifact.PlanNode("Lag", "close delta over observed trading rows"));
        }

        if (aggregateHistory) {
            sql.append(",\nhistorical_extrema AS (\n  SELECT mktcode,tgtcode,MAX(is_current) AS has_current");
            // Validated source keys guarantee at most one row per security/date. The
            // conditional aggregate retains its NULL value and never substitutes an older row.
            for (RawMetric raw : rawMetrics.values())
                sql.append(",\n    MAX(CASE WHEN is_current=1 THEN `").append(raw.alias)
                        .append("` END) AS `").append(raw.alias).append("_current`");
            for (CallSpec spec : uniqueCalls()) {
                var extremum = historicalExtrema.get(spec.alias);
                sql.append(",\n    ").append(extremum.function).append("(`").append(extremum.rawAlias)
                        .append("`) AS `").append(spec.alias).append("_extremum`");
            }
            sql.append("\n  FROM history\n  GROUP BY mktcode,tgtcode\n),\nfeatures AS (\n  SELECT a.*");
            for (CallSpec spec : uniqueCalls()) {
                var extremum = historicalExtrema.get(spec.alias);
                // All-NULL history and a NULL current value both produce SQL NULL.
                sql.append(",\n    a.`").append(extremum.rawAlias).append("_current` = a.`")
                        .append(spec.alias).append("_extremum` AS `").append(spec.alias).append('`');
            }
            sql.append("\n  FROM historical_extrema a\n)");
            plan.add(new StockSlotSqlArtifact.PlanNode("HistoricalAggregate", "MIN/MAX through evaluation date grouped by (mktcode,tgtcode)"));
        } else {
            sql.append(",\nfeatures AS (\n  SELECT ").append(source).append(".*");
            for (CallSpec spec : uniqueCalls())
                if (!spec.rank) sql.append(",\n    ").append(spec.expression).append(" AS `").append(spec.alias).append('`');
            bindings.addAll(featureBindings);
            sql.append("\n  FROM ").append(source).append("\n)");
            if (uniqueCalls().stream().anyMatch(c -> !c.rank)) plan.add(new StockSlotSqlArtifact.PlanNode("Window", contracts.size() + " contract(s)"));
        }
        }
        String source = "features";

        if (!counts.isEmpty()) {
            sql.append(",\npredicates AS (\n  SELECT features.*");
            for (CountSpec count : counts.values())
                sql.append(",\n    ").append(renderPlain(count.comparison)).append(" AS `").append(count.predicateAlias).append('`');
            sql.append("\n  FROM features\n),\ncounted AS (\n  SELECT predicates.*");
            for (CountSpec count : counts.values()) sql.append(",\n    ").append(countExpression(count)).append(" AS `").append(count.resultAlias).append('`');
            sql.append("\n  FROM predicates\n)");
            source = "counted";
            plan.add(new StockSlotSqlArtifact.PlanNode("OccurrenceWindow", counts.size() + " CONS/EXIST expression(s)"));
        }

        sql.append(",\ncurrent_rows AS (\n  SELECT * FROM ").append(source);
        if (aggregateHistory) sql.append(" WHERE has_current=1");
        else { sql.append(" WHERE bizdate = ?"); bindings.add(targetDate); }
        sql.append("\n)");
        source = "current_rows";
        plan.add(new StockSlotSqlArtifact.PlanNode("EvaluationDateFilter", targetDate.toString()));

        if (pre != null) {
            sql.append(",\nprefiltered AS (\n  SELECT * FROM current_rows WHERE ").append(render(pre)).append("\n)");
            source = "prefiltered";
            plan.add(new StockSlotSqlArtifact.PlanNode("Filter", "then precondition before ranking"));
        }
        if (!ranks.isEmpty()) {
            sql.append(",\nrank_input AS (\n  SELECT * FROM ").append(source).append(" WHERE ")
                    .append(String.join(" AND ", ranks.values().stream().map(r -> "`" + r.metricAlias + "` IS NOT NULL").toList()))
                    .append("\n),\nranked AS (\n  SELECT rank_input.*");
            for (RankSpec rank : ranks.values()) {
                sql.append(",\n    ").append(rank.method).append("() OVER (");
                if (rank.industryPartition) sql.append("PARTITION BY hyBlkRefName ");
                sql.append("ORDER BY `").append(rank.metricAlias).append("` ").append(rank.direction.toUpperCase(Locale.ROOT));
                if (rank.method.equals("ROW_NUMBER")) sql.append(",mktcode,tgtcode");
                sql.append(") AS `").append(rank.alias).append('`');
            }
            sql.append("\n  FROM rank_input\n)");
            source = "ranked";
            plan.add(new StockSlotSqlArtifact.PlanNode("NullFilter", "exclude NULL rank metrics"));
            plan.add(new StockSlotSqlArtifact.PlanNode("Rank", ranks.values().stream().map(r -> r.method).distinct().toList().toString()));
        }

        sql.append("\nSELECT mktcode,tgtcode\nFROM ").append(source).append("\nWHERE ").append(render(post));
        boolean ordered = !ranks.isEmpty();
        if (ordered) sql.append("\nORDER BY `").append(ranks.values().iterator().next().alias).append("`,mktcode,tgtcode");
        else sql.append("\nORDER BY mktcode,tgtcode");
        plan.add(new StockSlotSqlArtifact.PlanNode("Sort", ordered ? "rank,mktcode,tgtcode" : "mktcode,tgtcode"));
        StockSlotAst.SelectionLimit limit = model.document().selectionLimit();
        if (limit != null) {
            plan.add(new StockSlotSqlArtifact.PlanNode("CardinalityConstraint", limit.minimum() + "," + limit.maximum()));
            if (limit.maximum() != -1) sql.append("\nLIMIT ").append(limit.maximum());
        }
        sql.append(';');
        plan.add(new StockSlotSqlArtifact.PlanNode("Project", "mktcode,tgtcode"));
        return new StockSlotSqlArtifact(StockSlotCompiler.DSL_VERSION, model, plan, contracts, sql.toString(), bindings, ordered);
    }

    private StringBuilder historicalFeatureSql() {
        var sql = new StringBuilder("WITH features AS (\n  SELECT h.mktcode,h.tgtcode,h.bizdate");
        for (CallSpec spec : uniqueCalls()) {
            var extremum = historicalExtrema.get(spec.alias);
            RawMetric raw = rawMetrics.values().stream().filter(r -> r.alias.equals(extremum.rawAlias)).findFirst().orElseThrow();
            var columns = historicalFeatures.columns(raw.metric.expression());
            sql.append(",\n    h.`").append(columns.currentField()).append("` = h.`")
                    .append(extremum.function.equals("MIN") ? columns.minField() : columns.maxField())
                    .append("` AS `").append(spec.alias).append('`');
        }
        sql.append("\n  FROM ").append(historicalFeatures.qualifiedTable()).append(" h\n");
        if (needsCode) {
            var code = registry.table("code");
            sql.append("  LEFT JOIN ").append(code.qualifiedName()).append(' ').append(code.alias())
                    .append(" ON ").append(registry.column("code", "marketCode")).append("=h.mktcode AND ")
                    .append(registry.column("code", "securityCode")).append("=h.tgtcode\n");
            plan.add(new StockSlotSqlArtifact.PlanNode("CodeJoin", code.qualifiedName()));
        }
        sql.append("  WHERE h.snapshot_id=? AND h.manifest_sha256=? AND h.registry_fingerprint=? AND h.bizdate=?");
        bindings.add(snapshotId); bindings.add(manifestSha256); bindings.add(registry.fingerprint()); bindings.add(targetDate);
        materializedMarketColumn = "h.mktcode";
        String marketSql = marketPredicate(market);
        if (!marketSql.isEmpty()) sql.append("\n    AND ").append(marketSql);
        if (!scope.isEmpty() && !scope.equals("行业")) {
            var terms = split(scope, '|');
            sql.append("\n    AND ").append(registry.column("code", "industry")).append(" IN (")
                    .append(String.join(",", terms.stream().map(x -> "?").toList())).append(')');
            bindings.addAll(terms);
        }
        sql.append("\n)");
        plan.add(new StockSlotSqlArtifact.PlanNode("HistoricalFeatureScan", historicalFeatures.qualifiedTable()
                + " snapshot=" + snapshotId + " date=" + targetDate));
        return sql;
    }

    private void collect(StockSlotAst.Expr expression) {
        switch (expression) {
            case StockSlotAst.FunctionCall call -> collectCall(call);
            case StockSlotAst.Binary binary -> { collect(binary.left()); collect(binary.right()); }
            case StockSlotAst.Unary unary -> collect(unary.operand());
            default -> { }
        }
    }

    private void collectCall(StockSlotAst.FunctionCall call) {
        var function = registry.function(call.name());
        mergeMarket(arg(call, 0, "market"));
        if (function.lowering().kind() != StockSlotRegistryConfig.LoweringKind.QUERY_DATA)
            mergeScope(arg(call, 1, "filter_scope"));
        switch (function.lowering().kind()) {
            case INDICATOR -> indicator(call);
            case RANK -> rank(call);
            case QUERY_DATA -> queryData(call);
            case RANGE_WINDOW -> rangeFunction(call, function);
            case PAIR_WINDOW -> pairFunction(call, function);
            case INDUSTRY_AGGREGATE -> industry(call, function);
            default -> fail("EXECUTION_FUNCTION_UNSUPPORTED", "No SQL lowering for function: " + call.name());
        }
    }

    private void indicator(StockSlotAst.FunctionCall call) {
        String name = arg(call, 2, "indicator_name");
        DateSpec date = date(arg(call, 3, "date"));
        mergeDate(date.date);
        rejectSelectType(arg(call, 4, "select_type"));
        String agg = aggregation(arg(call, 5, "agg_func"));
        String count = arg(call, 6, "count_exp");
        var resolved = registry.indicator(name);
        String expression;
        if (resolved.lowering().kind() == StockSlotRegistryConfig.LoweringKind.WINDOW_AVG) {
            int n = window(Integer.parseInt(resolved.parameters().get("N")));
            if (allowFeatureAccess && Integer.toString(n).equals(resolved.parameters().get("featureWindow"))
                    && date.date.toString().equals(resolved.parameters().get("featureDate"))
                    && date.lookback == 0 && count.isEmpty()) {
                needsFeature = true;
                String table = resolved.parameters().get("featureTable");
                String field = resolved.parameters().get("featureField");
                RawMetric raw = rawMetric(new Metric(registry.column(table, field), false));
                expression = "`" + raw.alias + "`";
            } else {
                needsHistory = true;
                RawMetric raw = rawMetric(metric(resolved.parameters().get("baseIndicator")));
                expression = strictWindow("AVG", raw.alias, n);
            }
            contract("indicator:MA", n, true);
        } else if (resolved.lowering().kind() == StockSlotRegistryConfig.LoweringKind.RSI) {
            needsHistory = true;
            int n = window(Integer.parseInt(resolved.parameters().get("N")));
            rawMetric(metric(resolved.parameters().get("baseIndicator")));
            needsDelta = true;
            String frame = frame(n);
            expression = "CASE WHEN COUNT(price_delta) OVER " + over(frame) + " = " + n
                    + " THEN 100 - 100 / (1 + (AVG(GREATEST(price_delta,0)) OVER " + over(frame)
                    + ") / NULLIF(AVG(GREATEST(-price_delta,0)) OVER " + over(frame) + ",0)) ELSE NULL END";
            contract("indicator:RSI", n, true);
        } else {
            RawMetric raw = rawMetric(metric(name));
            int n = date.lookback;
            if (!agg.isEmpty()) {
                needsHistory = true;
                if (!resolved.allowedAggregations().contains(agg))
                    fail("EXECUTION_AGGREGATION_UNSUPPORTED", agg + " is not allowed for indicator " + name);
                if (n < 1) fail("EXECUTION_AGGREGATION_PERIOD", "Aggregation requires an anchored period such as 2026-04-14近5日");
                expression = strictWindow(agg, raw.alias, n);
                contract("indicator:" + agg, n, true);
            } else expression = "`" + raw.alias + "`";
        }
        addFeature(call, expression);
        validateCount(count);
    }

    private void rank(StockSlotAst.FunctionCall call) {
        Metric metric = metric(arg(call, 2, "indicator_name"));
        RawMetric raw = rawMetric(metric);
        RankDirection direction = rankDirection(arg(call, 3, "direction"));
        mergeDate(date(arg(call, 4, "date")).date);
        rejectSelectType(arg(call, 5, "select_type"));
        if (!arg(call, 6, "agg_func").isEmpty()) fail("EXECUTION_RANK_AGGREGATE", "Rank aggregation must be materialized as an indicator first");
        validateCount(arg(call, 7, "count_exp"));
        String alias = "r" + (ranks.size() + 1);
        calls.put(call, new CallSpec(alias, "", true));
        ranks.put(call, new RankSpec(alias, raw.alias, direction.method, direction.direction, scope.equals("行业")));
        contracts.add(new StockSlotWindowContract("rank:" + direction.method,
                scope.equals("行业") ? List.of("hyBlkRefName") : List.of(), List.of(raw.alias),
                "CROSS_SECTION", 1, "NOT_APPLICABLE", "NULL", "EXCLUDE_NULL_METRIC", false));
    }

    private void queryData(StockSlotAst.FunctionCall call) {
        needsCode = true;
        String keyword = arg(call, 1, "keywords");
        if (keyword.isEmpty() || keyword.contains("|") || keyword.contains("&") || keyword.contains("^"))
            fail("EXECUTION_QUERY_TARGET", "queryData requires one exact security code or name");
        RawMetric raw = rawMetric(metric(arg(call, 2, "indicator_name")));
        mergeDate(date(arg(call, 3, "date")).date);
        String agg = aggregation(arg(call, 4, "agg_func"));
        if (agg.isEmpty()) agg = "MAX";
        featureBindings.add(keyword);
        featureBindings.add(keyword);
        String expression = agg + "(CASE WHEN tgtcode=? OR name=? THEN `" + raw.alias + "` END) OVER (PARTITION BY bizdate)";
        addFeature(call, expression);
        contracts.add(new StockSlotWindowContract("queryData:" + agg, List.of("bizdate"), List.of(),
                "CROSS_SECTION", 1, "NOT_APPLICABLE", "NULL_IF_TARGET_MISSING", "IGNORE_NULL_INPUTS", false));
    }

    private void rangeFunction(StockSlotAst.FunctionCall call, StockSlotRegistryConfig.FunctionDefinition definition) {
        needsHistory = true;
        String function = definition.name();
        String mode = definition.lowering().parameters().get("mode");
        String indicator = arg(call, 2, "indicator_name");
        if (indicator.isEmpty()) indicator = definition.lowering().parameters().get("defaultIndicator");
        RawMetric raw = rawMetric(metric(indicator));
        PeriodSpec period = period(arg(call, 3, "period"));
        mergeDate(date(arg(call, 4, "date")).date);
        rejectSelectType(arg(call, 5, "select_type"));
        if (!arg(call, 6, "agg_func").isEmpty()) fail("EXECUTION_NESTED_AGGREGATE", function + " does not accept a second aggregation");
        validateCount(arg(call, 7, "count_exp"));
        String frame = period.unbounded ? "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW" : frame(period.length);
        String over = over(frame);
        String complete = period.unbounded ? "COUNT(`" + raw.alias + "`) OVER " + over + " > 0"
                : "COUNT(`" + raw.alias + "`) OVER " + over + " = " + period.length;
        String expression;
        if (mode.equals("POSITION")) {
            String min = "MIN(`" + raw.alias + "`) OVER " + over;
            String max = "MAX(`" + raw.alias + "`) OVER " + over;
            expression = "CASE WHEN NOT (" + complete + ") OR " + max + "=" + min + " THEN NULL "
                    + "WHEN `" + raw.alias + "` <= " + min + "+(" + max + "-" + min + ")/3 THEN '低' "
                    + "WHEN `" + raw.alias + "` >= " + min + "+2*(" + max + "-" + min + ")/3 THEN '高' ELSE '中' END";
        } else {
            String fn = mode;
            expression = "CASE WHEN " + complete + " THEN `" + raw.alias + "` = " + fn + "(`" + raw.alias + "`) OVER " + over + " ELSE NULL END";
        }
        addFeature(call, expression);
        if (period.unbounded && (mode.equals("MIN") || mode.equals("MAX"))
                && arg(call, 7, "count_exp").isEmpty())
            historicalExtrema.put(calls.get(call).alias, new HistoricalExtremum(raw.alias, mode));
        contract(function, period.unbounded ? 0 : period.length, !period.unbounded);
    }

    private void pairFunction(StockSlotAst.FunctionCall call, StockSlotRegistryConfig.FunctionDefinition definition) {
        needsHistory = true;
        String function = definition.name();
        String mode = definition.lowering().parameters().get("mode");
        RawMetric left = rawMetric(metric(arg(call, 2, "indicator_name_1")));
        RawMetric right = rawMetric(metric(arg(call, 3, "indicator_name_2")));
        mergeDate(date(arg(call, 4, "date")).date);
        rejectSelectType(arg(call, 5, "select_type"));
        validateCount(arg(call, 6, "count_exp"));
        String a = "`" + left.alias + "`", b = "`" + right.alias + "`";
        String pa = "LAG(" + a + ") OVER " + over(""), pb = "LAG(" + b + ") OVER " + over("");
        String nonNull = a + " IS NOT NULL AND " + b + " IS NOT NULL AND " + pa + " IS NOT NULL AND " + pb + " IS NOT NULL";
        String predicate = switch (mode) {
            case "CROSS_ABOVE" -> a + ">" + b + " AND " + pa + "<=" + pb;
            case "CROSS_DOWN" -> a + "<" + b + " AND " + pa + ">=" + pb;
            case "CLOSE_TOGETHER" -> "ABS(" + a + "-" + b + ")/NULLIF(GREATEST(ABS(" + a + "),ABS(" + b + ")),0)<="
                    + definition.lowering().parameters().get("threshold");
            default -> throw new IllegalStateException(mode);
        };
        String expression = mode.equals("CLOSE_TOGETHER")
                ? "CASE WHEN " + a + " IS NULL OR " + b + " IS NULL THEN NULL ELSE (" + predicate + ") END"
                : "CASE WHEN " + nonNull + " THEN (" + predicate + ") ELSE NULL END";
        addFeature(call, expression);
        contract(function, mode.equals("CLOSE_TOGETHER") ? 1 : 2, true);
    }

    private void industry(StockSlotAst.FunctionCall call, StockSlotRegistryConfig.FunctionDefinition definition) {
        needsCode = true;
        RawMetric raw = rawMetric(metric(arg(call, 2, "indicator_name")));
        mergeDate(date(arg(call, 3, "date")).date);
        String agg = aggregation(arg(call, 4, "agg_func"));
        if (agg.isEmpty()) agg = definition.lowering().parameters().get("defaultAggregation");
        String expression = "CASE WHEN hyBlkRefName IS NULL THEN NULL ELSE " + agg
                + "(`" + raw.alias + "`) OVER (PARTITION BY hyBlkRefName,bizdate) END";
        addFeature(call, expression);
        contracts.add(new StockSlotWindowContract(definition.name() + ":" + agg, List.of("hyBlkRefName", "bizdate"), List.of(),
                "CROSS_SECTION", 1, "NOT_APPLICABLE", "NULL_IF_INDUSTRY_MISSING", "IGNORE_NULL_INPUTS", false));
    }

    private void collectCounts(StockSlotAst.Expr expression) {
        switch (expression) {
            case StockSlotAst.Binary binary -> {
                if (!binary.operator().matches("AND|OR|THEN|[+\\-*/]")) {
                    StockSlotAst.FunctionCall counted = countedCall(binary);
                    if (counted != null) {
                        addCount(binary, counted);
                    }
                }
                collectCounts(binary.left()); collectCounts(binary.right());
            }
            case StockSlotAst.Unary unary -> collectCounts(unary.operand());
            case StockSlotAst.FunctionCall call -> {
                if (!countArgument(call).isEmpty() && !countedCalls.contains(call)) {
                    if (call.type() != StockSlotAst.ValueType.BOOLEAN)
                        fail("EXECUTION_COUNT_SHAPE", "A counted numeric call must be a direct comparison operand");
                    addCount(call, call);
                }
            }
            default -> { }
        }
    }

    private void addCount(StockSlotAst.Expr predicate, StockSlotAst.FunctionCall call) {
        if (registry.function(call.name()).lowering().kind() == StockSlotRegistryConfig.LoweringKind.RANK)
            fail("EXECUTION_COUNT_RANK", "Historical counts of cross-sectional ranks are not supported");
        if (predicate instanceof StockSlotAst.Binary binary
                && binary.left() instanceof StockSlotAst.FunctionCall left
                && binary.right() instanceof StockSlotAst.FunctionCall right
                && !countArgument(left).isEmpty() && !countArgument(right).isEmpty())
            fail("EXECUTION_COUNT_SHAPE", "A comparison must have only one counted call");
        Matcher matcher = COUNT.matcher(countArgument(call));
        if (!matcher.matches()) fail("EXECUTION_COUNT_UNSUPPORTED", "Unsupported count expression");
        int n;
        try { n = window(Integer.parseInt(matcher.group(3))); }
        catch (NumberFormatException e) { throw new CompileException("EXECUTION_WINDOW_RANGE", "Count window is too large", 1, 1); }
        int horizon = matcher.group(1).equals("CONS")
                ? (matcher.group(2).equals("=") ? n + 1 : n) : Math.max(20, n);
        String id = "c" + (counts.size() + 1);
        counts.put(predicate, new CountSpec(predicate, matcher.group(1), matcher.group(2), n, horizon, "p" + id, id));
        countedCalls.add(call);
        needsHistory = true;
        contract(matcher.group(1), horizon, true);
    }

    private StockSlotAst.FunctionCall countedCall(StockSlotAst.Binary comparison) {
        if (comparison.left() instanceof StockSlotAst.FunctionCall call && !countArgument(call).isEmpty()) return call;
        if (comparison.right() instanceof StockSlotAst.FunctionCall call && !countArgument(call).isEmpty()) return call;
        return null;
    }

    private String countArgument(StockSlotAst.FunctionCall call) {
        var parameters = registry.function(call.name()).parameters();
        int index = -1;
        for (int i = 0; i < parameters.size(); i++)
            if (parameters.get(i).name().equals("count_exp")) { index = i; break; }
        return index < 0 ? "" : arg(call, index, "count_exp");
    }

    private String countExpression(CountSpec count) {
        String fullCount = "COUNT(*) OVER " + over(frame(count.horizon));
        if (count.mode.equals("CONS")) {
            String lastN = "SUM(CASE WHEN `" + count.predicateAlias + "` THEN 1 ELSE 0 END) OVER " + over(frame(count.threshold));
            String result = lastN + "=" + count.threshold;
            if (count.operator.equals("="))
                result += " AND NOT COALESCE(LAG(`" + count.predicateAlias + "`," + count.threshold + ") OVER " + over("") + ",FALSE)";
            return "CASE WHEN " + fullCount + "=" + count.horizon + " THEN (" + result + ") ELSE NULL END";
        }
        String trueCount = "SUM(CASE WHEN `" + count.predicateAlias + "` THEN 1 ELSE 0 END) OVER " + over(frame(count.horizon));
        return "CASE WHEN " + fullCount + "=" + count.horizon + " THEN (" + trueCount + count.operator + count.threshold + ") ELSE NULL END";
    }

    private String render(StockSlotAst.Expr expression) {
        if (counts.containsKey(expression)) return "`" + counts.get(expression).resultAlias + "`";
        return renderPlain(expression);
    }

    private String renderPlain(StockSlotAst.Expr expression) {
        return switch (expression) {
            case StockSlotAst.Literal literal -> bind(literal.value());
            case StockSlotAst.Unary unary -> "(" + unary.operator() + render(unary.operand()) + ")";
            case StockSlotAst.FunctionCall call -> "`" + calls.get(call).alias + "`";
            case StockSlotAst.Binary binary -> {
                String op = binary.operator().toUpperCase(Locale.ROOT);
                if (op.equals("THEN")) fail("EXECUTION_THEN_SHAPE", "then is supported only once at the top level");
                if (op.equals("BETWEEN")) yield renderRange(binary.left(), binary.right());
                if (op.equals("~=")) {
                    String left = render(binary.left()), right = render(binary.right());
                    bindings.add(new BigDecimal("0.000001"));
                    yield "(ABS(" + left + "-" + right + ")<=?)";
                }
                yield "(" + render(binary.left()) + " " + op + " " + render(binary.right()) + ")";
            }
        };
    }

    private String renderRange(StockSlotAst.Expr value, StockSlotAst.Expr range) {
        if (!(range instanceof StockSlotAst.Literal literal) || !(literal.value() instanceof String))
            fail("EXECUTION_BETWEEN", "between requires a quoted numeric interval");
        String raw = (String) ((StockSlotAst.Literal) range).value();
        Matcher matcher = RANGE.matcher(raw);
        if (!matcher.matches()) fail("EXECUTION_BETWEEN", "Invalid interval: " + raw);
        String target = render(value);
        bindings.add(number(matcher.group(2)));
        String upperValue = render(value);
        bindings.add(number(matcher.group(3)));
        return "(" + target + (matcher.group(1).equals("[") ? ">=" : ">") + "? AND " + upperValue
                + (matcher.group(4).equals("]") ? "<=" : "<") + "?)";
    }

    private String strictWindow(String fn, String alias, int n) {
        String over = over(frame(n));
        return "CASE WHEN COUNT(`" + alias + "`) OVER " + over + "=" + n + " THEN " + fn + "(`" + alias + "`) OVER " + over + " ELSE NULL END";
    }

    private String over(String frame) {
        return "(PARTITION BY mktcode,tgtcode ORDER BY bizdate" + (frame.isEmpty() ? "" : " " + frame) + ")";
    }
    private String frame(int n) { return "ROWS BETWEEN " + (n - 1) + " PRECEDING AND CURRENT ROW"; }

    private void contract(String function, int lookback, boolean full) {
        contracts.add(new StockSlotWindowContract(function, List.of("mktcode", "tgtcode"), List.of("bizdate"),
                "TRADING_DAY", lookback, "OBSERVED_ROWS_SKIP_SUSPENSION", "NULL", "STRICT_NO_IMPUTATION", full));
    }

    private List<CallSpec> uniqueCalls() {
        return new ArrayList<>(new LinkedHashSet<>(featureCalls));
    }

    private void addFeature(StockSlotAst.FunctionCall call, String expression) {
        CallSpec spec = new CallSpec(alias(), expression, false);
        calls.put(call, spec);
        featureCalls.add(spec);
    }

    private RawMetric rawMetric(Metric metric) {
        RawMetric raw = rawMetrics.computeIfAbsent(metric.expression, ignored -> new RawMetric("v" + (rawMetrics.size() + 1), metric));
        needsExt |= metric.extension;
        return raw;
    }

    private Metric metric(String name) {
        var indicator = registry.indicator(name);
        if (indicator.pattern() != null) fail("EXECUTION_INDICATOR_WINDOW", "Pattern indicator cannot be used as a raw field: " + name);
        return new Metric(registry.expression(indicator), registry.requiresTable(indicator, "extension"));
    }

    private String alias() { return "f" + (calls.size() + 1); }
    private String bind(Object value) { bindings.add(value); return "?"; }
    private BigDecimal number(String value) { return new BigDecimal(value.endsWith("%") ? value.substring(0, value.length() - 1) : value); }

    private String arg(StockSlotAst.FunctionCall call, int index, String name) {
        if (index >= call.arguments().size() || !(call.arguments().get(index) instanceof StockSlotAst.Literal literal)
                || !(literal.value() instanceof String)) fail("EXECUTION_SLOT", call.name() + "." + name + " must be a string literal");
        return (String) ((StockSlotAst.Literal) call.arguments().get(index)).value();
    }

    private DateSpec date(String raw) {
        Matcher anchored = ANCHORED_PERIOD.matcher(raw);
        if (anchored.matches()) return new DateSpec(parseDate(anchored.group(1)), window(Integer.parseInt(anchored.group(2))));
        return new DateSpec(parseDate(raw), 0);
    }

    private LocalDate parseDate(String raw) {
        try { return LocalDate.parse(raw, DateTimeFormatter.ISO_LOCAL_DATE); }
        catch (DateTimeParseException ignored) { }
        Matcher matcher = CN_DATE.matcher(raw);
        if (matcher.matches()) return LocalDate.of(Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)), Integer.parseInt(matcher.group(3)));
        fail("EXECUTION_DATE_UNSUPPORTED", "A deterministic absolute date is required: " + raw);
        return null;
    }

    private PeriodSpec period(String raw) {
        if (raw.equals("历史")) return new PeriodSpec(0, true);
        Matcher matcher = PERIOD.matcher(raw);
        if (matcher.matches()) return new PeriodSpec(window(Integer.parseInt(matcher.group(1))), false);
        fail("EXECUTION_PERIOD_UNSUPPORTED", "Period must be N日 or 历史: " + raw);
        return null;
    }

    private int window(int n) {
        if (n < 1 || n > 5000) fail("EXECUTION_WINDOW_RANGE", "Window length must be 1..5000");
        return n;
    }

    private String aggregation(String raw) {
        String value = raw.toUpperCase(Locale.ROOT);
        if (!Set.of("", "MAX", "MIN", "AVG", "SUM").contains(value))
            fail("EXECUTION_AGGREGATION_UNSUPPORTED", "SQL lowering is not defined for aggregation: " + raw);
        return value;
    }

    private RankDirection rankDirection(String raw) {
        String[] pieces = raw.toLowerCase(Locale.ROOT).split(":");
        String direction = pieces[0], method = pieces.length == 1 ? "DENSE_RANK" : pieces[1].toUpperCase(Locale.ROOT);
        if (!Set.of("asc", "desc").contains(direction) || !Set.of("RANK", "DENSE_RANK", "ROW_NUMBER").contains(method))
            fail("EXECUTION_DIRECTION", "Use asc/desc or asc|desc:rank|dense_rank|row_number");
        return new RankDirection(direction, method);
    }

    private void rejectSelectType(String value) {
        if (!value.isEmpty()) fail("EXECUTION_SELECT_TYPE_UNSUPPORTED", "No accepted majorType mapping for select_type: " + value);
    }
    private void validateCount(String value) {
        if (!value.isEmpty() && !COUNT.matcher(value).matches())
            fail("EXECUTION_COUNT_UNSUPPORTED", "Supported count forms are CONS>=N日, CONS=N日, EXIST>=N日 and EXIST=N日");
    }
    private void mergeDate(LocalDate value) {
        if (targetDate == null) targetDate = value;
        else if (!targetDate.equals(value)) fail("EXECUTION_MULTI_DATE_UNSUPPORTED", "All functions must share one evaluation date");
    }
    private void mergeMarket(String value) {
        if (value.isEmpty()) return;
        if (market.isEmpty()) market = value;
        else if (!market.equals(value)) fail("EXECUTION_MARKET_MISMATCH", "All functions must share one market expression");
    }
    private void mergeScope(String value) {
        if (value.isEmpty()) return;
        if (scope.isEmpty()) scope = value;
        else if (!scope.equals(value)) fail("EXECUTION_SCOPE_MISMATCH", "All functions must share one scope expression");
        needsCode = true;
    }

    private String marketPredicate(String value) {
        if (value.isEmpty()) return "";
        List<String> or = split(value, '|');
        if (or.size() > 1) return "(" + String.join(" OR ", or.stream().map(this::marketAtom).toList()) + ")";
        return marketAtom(value);
    }
    private String marketAtom(String raw) {
        String value = raw.trim();
        if (value.startsWith("^")) return "NOT(" + marketAtom(value.substring(1)) + ")";
        if (value.contains("&") || value.substring(Math.min(1, value.length())).contains("^"))
            fail("EXECUTION_MARKET_COMPLEX", "Advanced windows currently support market union and exclusion only");
        Integer code = registry.markets().get(value);
        if (code == null) fail("EXECUTION_MARKET_UNSUPPORTED", "No accepted market mapping: " + value);
        return (materializedMarketColumn == null ? registry.column(needsFeature ? "features" : "basic", "marketCode")
                : materializedMarketColumn) + "=" + code;
    }
    private List<String> split(String value, char separator) {
        List<String> result = new ArrayList<>();
        for (String item : value.split(Pattern.quote(String.valueOf(separator)))) result.add(item.trim());
        return result;
    }

    private static void fail(String code, String message) { throw new CompileException(code, message, 1, 1); }

    private record Metric(String expression, boolean extension) {}
    private record RawMetric(String alias, Metric metric) {}
    private record CallSpec(String alias, String expression, boolean rank) {}
    private record HistoricalExtremum(String rawAlias, String function) {}
    private record RankSpec(String alias, String metricAlias, String method, String direction, boolean industryPartition) {}
    private record RankDirection(String direction, String method) {}
    private record DateSpec(LocalDate date, int lookback) {}
    private record PeriodSpec(int length, boolean unbounded) {}
    private record CountSpec(StockSlotAst.Expr comparison, String mode, String operator, int threshold, int horizon,
                             String predicateAlias, String resultAlias) {}
}
