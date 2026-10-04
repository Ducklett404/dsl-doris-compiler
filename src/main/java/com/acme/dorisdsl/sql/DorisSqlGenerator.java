package com.acme.dorisdsl.sql;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.compiler.CompilationArtifact;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.plan.AccessPathPlanner;
import com.acme.dorisdsl.plan.LogicalPlan;
import com.acme.dorisdsl.plan.WindowSpec;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.registry.RegistryConfig;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

public final class DorisSqlGenerator {
    private static final Pattern SAFE_ALIAS = Pattern.compile("[a-z_][a-z0-9_]*");
    private final Registry registry;
    private final CatalogSnapshot catalog;

    public DorisSqlGenerator(Registry registry, CatalogSnapshot catalog) {
        this.registry = registry;
        this.catalog = catalog;
    }

    public Result generate(Ast.Query query) { return new Generation(query).run(); }

    public record Result(String sql, List<Object> bindings, int lookback, LogicalPlan logicalPlan,
                         List<WindowSpec> windowSpecs,
                         List<CompilationArtifact.IndicatorVersion> indicatorVersions,
                         List<CompilationArtifact.Diagnostic> diagnostics) {}

    private final class Generation {
        private final Ast.Query query;
        private final Set<String> baseFields = new LinkedHashSet<>();
        private final Map<String, String> columnMetrics = new LinkedHashMap<>();
        private final Map<String, String> windowMetrics = new LinkedHashMap<>();
        private final Map<String, String> changeMetrics = new LinkedHashMap<>();
        private final Map<String, String> rsiMetrics = new LinkedHashMap<>();
        private final Map<String, String> metricAliases = new LinkedHashMap<>();
        private final Map<String, String> previousAliases = new LinkedHashMap<>();
        private final Map<String, WindowSpec> windowSpecs = new LinkedHashMap<>();
        private final Map<String, CompilationArtifact.IndicatorVersion> indicatorVersions = new LinkedHashMap<>();
        private final List<Object> bindings = new ArrayList<>();
        private final List<CompilationArtifact.Diagnostic> diagnostics = new ArrayList<>();
        private RegistryConfig.FinancialMetadata financialMetadata;
        private int maxWindow;
        private boolean hasCross;
        private boolean needsFinancial;

        private Generation(Ast.Query query) { this.query = query; }

        private Result run() {
            collect(query.where());
            if (query.orderBy() != null) collect(query.orderBy().expression());
            int lookback = windowSpecs.values().stream()
                    .mapToInt(WindowSpec::requiredLookbackTradingDays)
                    .max()
                    .orElse(0);
            if (hasCross) lookback = Math.max(lookback, maxWindow + 1);
            var accessPath = new AccessPathPlanner(registry, catalog).choose(query, lookback, needsFinancial);
            if (!"DETAIL_TABLE".equals(accessPath.selected())) {
                diagnostics.add(new CompilationArtifact.Diagnostic("INFO", "ACCESS_PATH_CANDIDATE",
                        accessPath.selected() + " has the lowest eligible cost."));
            }
            boolean usePrefixDaily = "PREFIX_DAILY".equals(accessPath.selected());
            boolean useFeatureDaily = "FEATURE_DAILY".equals(accessPath.selected());
            String sql = StableSqlFormatter.format(useFeatureDaily ? buildFeatureDailySql()
                    : usePrefixDaily ? buildPrefixDailySql() : buildSql(lookback));
            List<LogicalPlan.PlanNode> nodes = new ArrayList<>();
            String scanTable = useFeatureDaily ? catalog.tables().featureTable()
                    : usePrefixDaily ? catalog.tables().prefixSumTable() : catalog.tables().detailTable();
            nodes.add(new LogicalPlan.PlanNode("Scan", scanTable));
            if (needsFinancial && !useFeatureDaily) nodes.add(new LogicalPlan.PlanNode("PointInTimeJoin", catalog.tables().financialPitTable()));
            if (useFeatureDaily) nodes.add(new LogicalPlan.PlanNode("FeatureVersionFilter",
                    catalog.feature().version() + "/" + catalog.feature().adjustmentVersion() + "/" + catalog.feature().sourceSnapshot()));
            if (usePrefixDaily) nodes.add(new LogicalPlan.PlanNode("PrefixDifference", "current cumulative value minus N-day-prior cumulative value"));
            if (!changeMetrics.isEmpty()) nodes.add(new LogicalPlan.PlanNode("Change", String.join(", ", changeMetrics.keySet())));
            if (!usePrefixDaily && (!windowMetrics.isEmpty() || !rsiMetrics.isEmpty())) {
                List<String> metrics = new ArrayList<>(windowMetrics.keySet());
                metrics.addAll(rsiMetrics.keySet());
                nodes.add(new LogicalPlan.PlanNode("Window", String.join(", ", metrics)));
            }
            if (!previousAliases.isEmpty()) nodes.add(new LogicalPlan.PlanNode("Signal", "LAG operands for cross signals"));
            nodes.add(new LogicalPlan.PlanNode("Filter", "Target-date predicate"));
            if (query.orderBy() != null) nodes.add(new LogicalPlan.PlanNode("Sort", query.orderBy().direction().name()));
            nodes.add(new LogicalPlan.PlanNode("Limit", Integer.toString(query.limit())));
            return new Result(sql, List.copyOf(bindings), lookback, new LogicalPlan(nodes, accessPath),
                    List.copyOf(windowSpecs.values()), List.copyOf(indicatorVersions.values()),
                    List.copyOf(diagnostics));
        }

        private void collect(Ast.Expr expr) {
            if (expr == null) return;
            switch (expr) {
                case Ast.Identifier id -> ensureField(id.name());
                case Ast.FunctionCall call -> {
                    var definition = fn(call);
                    definition.requiredFields().forEach(this::ensureField);
                    switch (definition.loweringKind()) {
                        case COLUMN, WINDOW_AVG, WINDOW_EMA, WINDOW_STDDEV, RETURN_N, RSI, RANK_BY, PERCENTILE_RANK -> ensureMetric(call);
                        case CROSS_UP -> {
                            recordIndicator(definition);
                            hasCross = true;
                            String left = ensureValueAlias(call.arguments().get(0));
                            String right = ensureValueAlias(call.arguments().get(1));
                            previousAliases.putIfAbsent(left, "prev_" + left);
                            previousAliases.putIfAbsent(right, "prev_" + right);
                            ensureLagSpec(left, previousAliases.get(left));
                            ensureLagSpec(right, previousAliases.get(right));
                        }
                        case CROSS_DOWN -> {
                            recordIndicator(definition);
                            hasCross = true;
                            String left = ensureValueAlias(call.arguments().get(0));
                            String right = ensureValueAlias(call.arguments().get(1));
                            previousAliases.putIfAbsent(left, "prev_" + left);
                            previousAliases.putIfAbsent(right, "prev_" + right);
                            ensureLagSpec(left, previousAliases.get(left));
                            ensureLagSpec(right, previousAliases.get(right));
                        }
                        case TEMPLATE -> call.arguments().forEach(this::collect);
                    }
                }
                case Ast.Binary e -> { collect(e.left()); collect(e.right()); }
                case Ast.Unary e -> collect(e.operand());
                case Ast.Between e -> { collect(e.value()); collect(e.lower()); collect(e.upper()); }
                case Ast.InList e -> { collect(e.value()); e.options().forEach(this::collect); }
                case Ast.IsNull e -> collect(e.value());
                case Ast.NamedArgument e -> collect(e.value());
                default -> { }
            }
        }

        private String ensureMetric(Ast.FunctionCall call) {
            String key = signature(call);
            if (metricAliases.containsKey(key)) return metricAliases.get(key);
            var definition = fn(call);
            recordIndicator(definition);
            String alias;
            if (definition.loweringKind() == RegistryConfig.LoweringKind.COLUMN) {
                alias = uniqueAlias(call.name().toLowerCase(Locale.ROOT));
                columnMetrics.put(alias, definition.sqlTemplate());
                if (definition.sqlTemplate().contains("f.")) {
                    needsFinancial = true;
                    financialMetadata = mergeFinancialMetadata(financialMetadata, definition.financialMetadata(), call);
                    diagnostics.add(new CompilationArtifact.Diagnostic("INFO", "FINANCIAL_PIT",
                            call.name() + " uses point-in-time financial visibility: f." +
                                    financialMetadata.visibleFromColumn() + " <= q.trade_date < f." +
                                    financialMetadata.visibleToColumn() + "; report period column f." +
                                    financialMetadata.reportPeriodColumn() + " is not used for direct joins."));
                }
            } else if (definition.loweringKind() == RegistryConfig.LoweringKind.WINDOW_EMA) {
                throw new CompileException("EMA_LOWERING_UNAVAILABLE",
                        "EMA requires recursive semantics or a versioned precomputed feature; refusing to lower it as MA",
                        call.span().line(), call.span().column());
            } else if (isWindowMetric(definition.loweringKind())) {
                String inputAlias = ensureValueAlias(call.arguments().get(0));
                int lookbackArg = definition.lookbackArg() == null && definition.windowSpec() != null
                        ? definition.windowSpec().lengthArg() : definition.lookbackArg() == null ? 1 : definition.lookbackArg();
                int window = literalInt(call.arguments().get(lookbackArg));
                if (window < 1 || window > com.acme.dorisdsl.semantic.SemanticAnalyzer.MAX_WINDOW_LENGTH)
                    throw new CompileException("WINDOW_RANGE", "Window must be between 1 and " +
                            com.acme.dorisdsl.semantic.SemanticAnalyzer.MAX_WINDOW_LENGTH, call.span().line(), call.span().column());
                maxWindow = Math.max(maxWindow, window);
                alias = uniqueAlias(call.name().toLowerCase(Locale.ROOT) + "_" + inputAlias + "_" + window);
                String frame = " OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN "
                        + (window - 1) + " PRECEDING AND CURRENT ROW)";
                String aggregate = definition.loweringKind() == RegistryConfig.LoweringKind.WINDOW_STDDEV
                        ? "STDDEV_SAMP(" + q(inputAlias) + ")" : "AVG(" + q(inputAlias) + ")";
                windowMetrics.put(alias, "CASE WHEN COUNT(" + q(inputAlias) + ")" + frame + " = " + window
                        + " THEN " + aggregate + frame + " ELSE NULL END");
                windowSpecs.put(alias, new WindowSpec(alias, call.name(), window, WindowSpec.Unit.TRADING_DAY,
                        List.of("symbol"), List.of("trade_date"), WindowSpec.NullPolicy.STRICT_FULL_WINDOW, true));
            } else if (definition.loweringKind() == RegistryConfig.LoweringKind.RETURN_N) {
                String inputAlias = ensureValueAlias(call.arguments().get(0));
                int window = literalInt(call.arguments().get(definition.lookbackArg()));
                maxWindow = Math.max(maxWindow, window);
                alias = uniqueAlias("return_n_" + inputAlias + "_" + window);
                windowMetrics.put(alias, "(" + q(inputAlias) + " / LAG(" + q(inputAlias) + ", " + window
                        + ") OVER (PARTITION BY symbol ORDER BY trade_date) - 1)");
                windowSpecs.put(alias, new WindowSpec(alias, call.name(), window, WindowSpec.Unit.TRADING_DAY,
                        List.of("symbol"), List.of("trade_date"), WindowSpec.NullPolicy.ALLOW_PARTIAL_WINDOW, true));
            } else if (definition.loweringKind() == RegistryConfig.LoweringKind.RSI) {
                String inputAlias = ensureValueAlias(call.arguments().get(0));
                if (rsiMetrics.containsKey(inputAlias))
                    throw new CompileException("RSI_NESTING_UNSUPPORTED", "RSI cannot consume another RSI in the same lowering pipeline",
                            call.span().line(), call.span().column());
                int window = literalInt(call.arguments().get(definition.lookbackArg()));
                maxWindow = Math.max(maxWindow, window + 1);
                alias = uniqueAlias("rsi_" + inputAlias + "_" + window);
                String changeAlias = "change_" + inputAlias;
                changeMetrics.putIfAbsent(changeAlias, q(inputAlias) + " - LAG(" + q(inputAlias)
                        + ") OVER (PARTITION BY symbol ORDER BY trade_date)");
                String frame = " OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN "
                        + (window - 1) + " PRECEDING AND CURRENT ROW)";
                String averageGain = "AVG(GREATEST(" + q(changeAlias) + ", 0))" + frame;
                String averageLoss = "AVG(ABS(LEAST(" + q(changeAlias) + ", 0)))" + frame;
                rsiMetrics.put(alias, "(100 - 100 / (1 + " + averageGain + " / NULLIF(" + averageLoss + ", 0)))");
                windowSpecs.put(alias, new WindowSpec(alias, call.name(), window + 1, WindowSpec.Unit.TRADING_DAY,
                        List.of("symbol"), List.of("trade_date"), WindowSpec.NullPolicy.ALLOW_PARTIAL_WINDOW, true));
            } else if (definition.loweringKind() == RegistryConfig.LoweringKind.RANK_BY ||
                    definition.loweringKind() == RegistryConfig.LoweringKind.PERCENTILE_RANK) {
                String inputAlias = ensureValueAlias(call.arguments().get(0));
                String direction = definition.loweringKind() == RegistryConfig.LoweringKind.RANK_BY
                        ? rankDirection(call) : "DESC";
                alias = uniqueAlias(call.name().toLowerCase(Locale.ROOT) + "_" + inputAlias + "_" + direction.toLowerCase(Locale.ROOT));
                String fn = definition.loweringKind() == RegistryConfig.LoweringKind.PERCENTILE_RANK ? "PERCENT_RANK()" : "DENSE_RANK()";
                windowMetrics.put(alias, fn + " OVER (PARTITION BY trade_date ORDER BY " + q(inputAlias) + " " + direction + ")");
            } else {
                throw new CompileException("LOWERING_ERROR", "Function is not a metric: " + call.name(), call.span().line(), call.span().column());
            }
            metricAliases.put(key, alias);
            return alias;
        }

        private void ensureLagSpec(String inputAlias, String previousAlias) {
            windowSpecs.putIfAbsent(previousAlias, new WindowSpec(previousAlias, "LAG", 1, WindowSpec.Unit.TRADING_DAY,
                    List.of("symbol"), List.of("trade_date"), WindowSpec.NullPolicy.ALLOW_PARTIAL_WINDOW, true));
        }

        private String ensureValueAlias(Ast.Expr expr) {
            if (expr instanceof Ast.Identifier id) return ensureField(id.name());
            if (expr instanceof Ast.FunctionCall call) {
                var kind = fn(call).loweringKind();
                if (kind == RegistryConfig.LoweringKind.COLUMN || kind == RegistryConfig.LoweringKind.WINDOW_AVG
                        || kind == RegistryConfig.LoweringKind.WINDOW_EMA || kind == RegistryConfig.LoweringKind.WINDOW_STDDEV
                        || kind == RegistryConfig.LoweringKind.RETURN_N || kind == RegistryConfig.LoweringKind.RSI
                        || kind == RegistryConfig.LoweringKind.RANK_BY || kind == RegistryConfig.LoweringKind.PERCENTILE_RANK)
                    return ensureMetric(call);
            }
            throw new CompileException("METRIC_ARGUMENT", "Window/cross operand must resolve to a field or metric", expr.span().line(), expr.span().column());
        }

        private String ensureField(String name) {
            var field = registry.field(name, 1, 1);
            recordIndicator(field);
            String alias = name.toLowerCase(Locale.ROOT);
            baseFields.add(alias);
            return alias;
        }

        private String buildSql(int lookback) {
            List<String> baseSelect = new ArrayList<>();
            baseSelect.add("q.symbol AS symbol");
            baseSelect.add("q.trade_date AS trade_date");
            baseFields.remove("symbol");
            baseFields.remove("trade_date");
            for (String alias : baseFields) {
                var field = registry.field(alias, 1, 1);
                baseSelect.add(adjust(field.sourceSql()) + " AS " + q(alias));
            }
            columnMetrics.forEach((alias, expression) -> baseSelect.add(expression + " AS " + q(alias)));

            StringBuilder sql = new StringBuilder("WITH base AS (\n  SELECT\n    ")
                    .append(String.join(",\n    ", baseSelect))
                    .append("\n  FROM ").append(catalog.tables().detailTable()).append(" q\n");
            if (needsFinancial) {
                sql.append("  LEFT JOIN ").append(catalog.tables().financialPitTable()).append(" f\n")
                        .append("    ON f.symbol = q.symbol\n")
                        .append("   AND f.").append(financialMetadata.visibleFromColumn()).append(" <= q.trade_date\n")
                        .append("   AND q.trade_date < f.").append(financialMetadata.visibleToColumn()).append("\n");
            }
            if (lookback > 0) {
                sql.append("  WHERE q.trade_date BETWEEN (\n")
                        .append("    SELECT MIN(cal_date) FROM (\n")
                        .append("      SELECT cal_date FROM ").append(catalog.tables().calendarTable()).append("\n")
                        .append("      WHERE market = 'CN' AND is_open = 1 AND cal_date <= ?\n")
                        .append("      ORDER BY cal_date DESC LIMIT ").append(lookback + 1).append("\n")
                        .append("    ) trading_days\n  ) AND ?\n");
                bindings.add(query.asOf());
                bindings.add(query.asOf());
            } else {
                sql.append("  WHERE q.trade_date = ?\n");
                bindings.add(query.asOf());
            }
            appendContextFilters(sql);
            sql.append(")");

            String source = "base";
            if (!windowMetrics.isEmpty()) {
                String cte = rsiMetrics.isEmpty() ? "metrics" : "window_inputs";
                sql.append(",\n").append(cte).append(" AS (\n  SELECT base.*");
                windowMetrics.forEach((alias, expression) -> sql.append(",\n    ").append(expression).append(" AS ").append(q(alias)));
                sql.append("\n  FROM base\n)");
                source = cte;
            }
            if (!changeMetrics.isEmpty()) {
                String from = source;
                sql.append(",\nchanges AS (\n  SELECT ").append(from).append(".*");
                changeMetrics.forEach((alias, expression) -> sql.append(",\n    ").append(expression).append(" AS ").append(q(alias)));
                sql.append("\n  FROM ").append(from).append("\n)");
                source = "changes";
            }
            if (!rsiMetrics.isEmpty()) {
                sql.append(",\nmetrics AS (\n  SELECT changes.*");
                rsiMetrics.forEach((alias, expression) -> sql.append(",\n    ").append(expression).append(" AS ").append(q(alias)));
                sql.append("\n  FROM changes\n)");
                source = "metrics";
            }
            if (!previousAliases.isEmpty()) {
                String from = source;
                sql.append(",\nsignals AS (\n  SELECT ").append(from).append(".*");
                previousAliases.forEach((alias, previous) -> sql.append(",\n    LAG(").append(q(alias))
                        .append(") OVER (PARTITION BY symbol ORDER BY trade_date) AS ").append(q(previous)));
                sql.append("\n  FROM ").append(from).append("\n)");
                source = "signals";
            }

            LinkedHashSet<String> outputs = new LinkedHashSet<>();
            outputs.add("symbol");
            outputs.add("trade_date");
            outputs.addAll(columnMetrics.keySet());
            outputs.addAll(windowMetrics.keySet());
            outputs.addAll(rsiMetrics.keySet());
            sql.append("\nSELECT ").append(outputs.stream().map(this::q).reduce((a, b) -> a + ", " + b).orElse("symbol"))
                    .append("\nFROM ").append(source)
                    .append("\nWHERE trade_date = ?");
            bindings.add(query.asOf());
            if (query.where() != null) sql.append("\n  AND ").append(render(query.where()));
            if (query.orderBy() != null) {
                sql.append("\nORDER BY ").append(render(query.orderBy().expression())).append(" ")
                        .append(query.orderBy().direction().name());
            }
            sql.append("\nLIMIT ").append(query.limit()).append(';');
            return sql.toString();
        }

        private String buildPrefixDailySql() {
            Map<String, PrefixMetric> prefixMetrics = new LinkedHashMap<>();
            collectPrefixMetrics(query.where(), prefixMetrics);
            if (query.orderBy() != null) collectPrefixMetrics(query.orderBy().expression(), prefixMetrics);
            if (prefixMetrics.isEmpty()) throw new IllegalStateException("PREFIX_DAILY selected without prefix metrics");

            String sequence = catalog.prefixDaily().tradingDaySequenceColumn();
            StringBuilder sql = new StringBuilder("WITH target_day AS (\n")
                    .append("  SELECT symbol, trade_date, ").append(sequence).append("\n")
                    .append("  FROM ").append(catalog.tables().prefixSumTable()).append("\n")
                    .append("  WHERE trade_date = ?\n),\nprefix_points AS (\n  SELECT t.symbol, t.trade_date");
            bindings.add(query.asOf());
            for (PrefixMetric metric : prefixMetrics.values()) {
                sql.append(",\n    CASE WHEN (cur.").append(metric.countColumn()).append(" - COALESCE(prev_")
                        .append(metric.alias()).append('.').append(metric.countColumn()).append(", 0)) = ")
                        .append(metric.window()).append(" THEN (cur.").append(metric.sumColumn())
                        .append(" - COALESCE(prev_").append(metric.alias()).append('.').append(metric.sumColumn())
                        .append(", 0)) / ").append(metric.window()).append(" ELSE NULL END AS ").append(q(metric.alias()));
            }
            sql.append("\n  FROM target_day t\n  JOIN ").append(catalog.tables().prefixSumTable())
                    .append(" cur ON cur.symbol = t.symbol AND cur.").append(sequence).append(" = t.").append(sequence);
            for (PrefixMetric metric : prefixMetrics.values()) {
                sql.append("\n  LEFT JOIN ").append(catalog.tables().prefixSumTable()).append(" prev_").append(metric.alias())
                        .append(" ON prev_").append(metric.alias()).append(".symbol = t.symbol")
                        .append(" AND prev_").append(metric.alias()).append('.').append(sequence)
                        .append(" = t.").append(sequence).append(" - ").append(metric.window());
            }
            sql.append("\n)\nSELECT `symbol`, `trade_date`");
            prefixMetrics.values().forEach(metric -> sql.append(", ").append(q(metric.alias())));
            sql.append("\nFROM prefix_points\nWHERE ").append(render(query.where()));
            if (query.orderBy() != null) sql.append("\nORDER BY ").append(render(query.orderBy().expression()))
                    .append(' ').append(query.orderBy().direction().name());
            sql.append("\nLIMIT ").append(query.limit()).append(';');
            return sql.toString();
        }

        private void collectPrefixMetrics(Ast.Expr expr, Map<String, PrefixMetric> metrics) {
            if (expr == null) return;
            if (expr instanceof Ast.FunctionCall call) {
                if (fn(call).loweringKind() == RegistryConfig.LoweringKind.WINDOW_AVG) {
                    var field = (Ast.Identifier) call.arguments().get(0);
                    int window = literalInt(call.arguments().get(fn(call).lookbackArg()));
                    var columns = catalog.prefixDaily().fields().get(field.name().toUpperCase(Locale.ROOT));
                    String alias = metricAliases.get(signature(call));
                    metrics.putIfAbsent(alias, new PrefixMetric(alias, columns.cumulativeValueColumn(),
                            columns.cumulativeCountColumn(), window));
                }
                call.arguments().forEach(argument -> collectPrefixMetrics(argument, metrics));
            } else if (expr instanceof Ast.Binary e) { collectPrefixMetrics(e.left(), metrics); collectPrefixMetrics(e.right(), metrics); }
            else if (expr instanceof Ast.Unary e) collectPrefixMetrics(e.operand(), metrics);
            else if (expr instanceof Ast.Between e) { collectPrefixMetrics(e.value(), metrics); collectPrefixMetrics(e.lower(), metrics); collectPrefixMetrics(e.upper(), metrics); }
            else if (expr instanceof Ast.InList e) { collectPrefixMetrics(e.value(), metrics); e.options().forEach(option -> collectPrefixMetrics(option, metrics)); }
            else if (expr instanceof Ast.IsNull e) collectPrefixMetrics(e.value(), metrics);
            else if (expr instanceof Ast.NamedArgument e) collectPrefixMetrics(e.value(), metrics);
        }

        private record PrefixMetric(String alias, String sumColumn, String countColumn, int window) {}

        private String buildFeatureDailySql() {
            Map<String, String> features = new LinkedHashMap<>();
            collectFeatureColumns(query.where(), features);
            if (query.orderBy() != null) collectFeatureColumns(query.orderBy().expression(), features);
            StringBuilder sql = new StringBuilder("WITH features AS (\n  SELECT symbol, trade_date");
            features.forEach((alias, column) -> sql.append(",\n    ").append(q(column)).append(" AS ").append(q(alias)));
            sql.append("\n  FROM ").append(catalog.tables().featureTable())
                    .append("\n  WHERE trade_date = ?")
                    .append("\n    AND feature_version = ?")
                    .append("\n    AND adjustment_version = ?")
                    .append("\n    AND source_snapshot = ?\n)")
                    .append("\nSELECT `symbol`, `trade_date`");
            bindings.add(query.asOf());
            bindings.add(catalog.feature().version());
            bindings.add(catalog.feature().adjustmentVersion());
            bindings.add(catalog.feature().sourceSnapshot());
            features.keySet().forEach(alias -> sql.append(", ").append(q(alias)));
            sql.append("\nFROM features\nWHERE ").append(render(query.where()));
            if (query.orderBy() != null) sql.append("\nORDER BY ").append(render(query.orderBy().expression()))
                    .append(' ').append(query.orderBy().direction().name());
            sql.append("\nLIMIT ").append(query.limit()).append(';');
            return sql.toString();
        }

        private void collectFeatureColumns(Ast.Expr expr, Map<String, String> features) {
            if (expr == null) return;
            if (expr instanceof Ast.FunctionCall call) {
                String column = catalog.feature().indicatorColumns().get(featureSignature(call));
                if (column != null) features.putIfAbsent(metricAliases.get(signature(call)), column);
                return;
            }
            if (expr instanceof Ast.Binary e) { collectFeatureColumns(e.left(), features); collectFeatureColumns(e.right(), features); }
            else if (expr instanceof Ast.Unary e) collectFeatureColumns(e.operand(), features);
            else if (expr instanceof Ast.Between e) { collectFeatureColumns(e.value(), features); collectFeatureColumns(e.lower(), features); collectFeatureColumns(e.upper(), features); }
            else if (expr instanceof Ast.InList e) { collectFeatureColumns(e.value(), features); e.options().forEach(option -> collectFeatureColumns(option, features)); }
            else if (expr instanceof Ast.IsNull e) collectFeatureColumns(e.value(), features);
            else if (expr instanceof Ast.NamedArgument e) collectFeatureColumns(e.value(), features);
        }

        private String featureSignature(Ast.Expr expr) {
            return switch (expr) {
                case Ast.Identifier id -> id.name().toUpperCase(Locale.ROOT);
                case Ast.Literal literal -> String.valueOf(literal.value()).replace(".0", "");
                case Ast.FunctionCall call -> call.name().toUpperCase(Locale.ROOT) + "("
                        + call.arguments().stream().map(this::featureSignature).reduce((a, b) -> a + "," + b).orElse("") + ")";
                case Ast.Binary binary -> featureSignature(binary.left()) + binary.operator() + featureSignature(binary.right());
                case Ast.Unary unary -> unary.operator() + featureSignature(unary.operand());
                case Ast.Between between -> featureSignature(between.value()) + "BETWEEN" + featureSignature(between.lower()) + "AND" + featureSignature(between.upper());
                case Ast.InList in -> featureSignature(in.value()) + "IN" + in.options().stream().map(this::featureSignature).toList();
                case Ast.IsNull isNull -> featureSignature(isNull.value()) + (isNull.negated() ? "ISNOTNULL" : "ISNULL");
                case Ast.NamedArgument named -> named.name() + "=" + featureSignature(named.value());
            };
        }
        private String render(Ast.Expr expr) {
            return switch (expr) {
                case Ast.Literal literal -> bind(literal.value());
                case Ast.Identifier id -> q(id.name().toLowerCase(Locale.ROOT));
                case Ast.FunctionCall call -> renderFunction(call);
                case Ast.Binary binary -> "(" + render(binary.left()) + " " + binary.operator() + " " + render(binary.right()) + ")";
                case Ast.Unary unary -> unary.operator().equals("NOT")
                        ? "(NOT " + render(unary.operand()) + ")" : "(" + unary.operator() + render(unary.operand()) + ")";
                case Ast.Between between -> "(" + render(between.value()) + " BETWEEN " + render(between.lower()) + " AND " + render(between.upper()) + ")";
                case Ast.InList in -> "(" + render(in.value()) + " IN (" + in.options().stream().map(this::render).reduce((a,b) -> a + ", " + b).orElse("") + "))";
                case Ast.IsNull isNull -> "(" + render(isNull.value()) + " IS " + (isNull.negated() ? "NOT " : "") + "NULL)";
                case Ast.NamedArgument named -> throw new CompileException("NAMED_ARGUMENT_RENDER", "Named argument cannot be rendered directly", named.span().line(), named.span().column());
            };
        }

        private String renderFunction(Ast.FunctionCall call) {
            var definition = fn(call);
            return switch (definition.loweringKind()) {
                case COLUMN, WINDOW_AVG, WINDOW_EMA, WINDOW_STDDEV, RETURN_N, RSI, RANK_BY, PERCENTILE_RANK -> q(ensureMetric(call));
                case CROSS_UP -> {
                    String left = ensureValueAlias(call.arguments().get(0));
                    String right = ensureValueAlias(call.arguments().get(1));
                    yield "(" + q(left) + " > " + q(right) + " AND " + q(previousAliases.get(left)) + " <= " + q(previousAliases.get(right)) + ")";
                }
                case CROSS_DOWN -> {
                    String left = ensureValueAlias(call.arguments().get(0));
                    String right = ensureValueAlias(call.arguments().get(1));
                    yield "(" + q(left) + " < " + q(right) + " AND " + q(previousAliases.get(left)) + " >= " + q(previousAliases.get(right)) + ")";
                }
                case TEMPLATE -> {
                    var matcher = Pattern.compile("\\{(\\d+)}").matcher(definition.sqlTemplate());
                    StringBuilder rendered = new StringBuilder();
                    while (matcher.find()) matcher.appendReplacement(rendered,
                            java.util.regex.Matcher.quoteReplacement(render(call.arguments().get(Integer.parseInt(matcher.group(1))))));
                    matcher.appendTail(rendered);
                    if (rendered.indexOf("{") >= 0 || rendered.indexOf("}") >= 0)
                        throw new CompileException("TEMPLATE_UNRESOLVED",
                                "SQL template for " + call.name() + " contains an unresolved placeholder",
                                call.span().line(), call.span().column());
                    yield rendered.toString();
                }
            };
        }

        private String bind(Object value) {
            bindings.add(value);
            return "?";
        }

        private String adjust(String sourceSql) {
            if (query.adjustment() == Ast.Adjustment.FORWARD) return sourceSql;
            if (query.adjustment() == Ast.Adjustment.BACKWARD) return sourceSql.replace("_qfq", "_hfq");
            return sourceSql.replace("_qfq", "").replace("_hfq", "");
        }

        private int literalInt(Ast.Expr expr) {
            if (expr instanceof Ast.Literal l && l.value() instanceof BigDecimal value) return value.intValueExact();
            throw new CompileException("WINDOW_LITERAL", "Window must be an integer literal", expr.span().line(), expr.span().column());
        }

        private String rankDirection(Ast.FunctionCall call) {
            if (call.arguments().size() < 2) return "DESC";
            Ast.Expr argument = call.arguments().get(1);
            if (argument instanceof Ast.NamedArgument named) argument = named.value();
            if (argument instanceof Ast.Literal literal && literal.value() instanceof String value) {
                String direction = value.toUpperCase(Locale.ROOT);
                if (direction.equals("ASC") || direction.equals("DESC")) return direction;
            }
            throw new CompileException("RANK_DIRECTION", "RANK_BY direction must be ASC or DESC", argument.span().line(), argument.span().column());
        }

        private void appendContextFilters(StringBuilder sql) {
            for (var entry : query.context().values().entrySet()) {
                String key = entry.getKey().toUpperCase(Locale.ROOT);
                if (key.equals("USER")) continue;
                String field = switch (key) {
                    case "MARKET", "INDUSTRY", "UNIVERSE" -> adjust(registry.field(key, query.span().line(), query.span().column()).sourceSql());
                    default -> throw new CompileException("CONTEXT_KEY", "Unsupported context key: " + key, query.span().line(), query.span().column());
                };
                if (entry.getValue().size() == 1) {
                    sql.append("    AND ").append(field).append(" = ?\n");
                    bindings.add(entry.getValue().get(0));
                } else {
                    sql.append("    AND ").append(field).append(" IN (")
                            .append("?,".repeat(entry.getValue().size()));
                    sql.setLength(sql.length() - 1);
                    sql.append(")\n");
                    bindings.addAll(entry.getValue());
                }
            }
        }

        private RegistryConfig.FunctionDefinition fn(Ast.FunctionCall call) {
            return registry.function(call.name(), call.span().line(), call.span().column());
        }

        private boolean isWindowMetric(RegistryConfig.LoweringKind kind) {
            return kind == RegistryConfig.LoweringKind.WINDOW_AVG
                    || kind == RegistryConfig.LoweringKind.WINDOW_STDDEV;
        }

        private void recordIndicator(RegistryConfig.FunctionDefinition definition) {
            String version = definition.version() == null || definition.version().isBlank() ? "builtin" : definition.version();
            indicatorVersions.putIfAbsent(definition.name().toUpperCase(Locale.ROOT),
                    new CompilationArtifact.IndicatorVersion(definition.name().toUpperCase(Locale.ROOT), version));
        }

        private void recordIndicator(RegistryConfig.FieldDefinition definition) {
            String version = definition.version() == null || definition.version().isBlank() ? "builtin" : definition.version();
            indicatorVersions.putIfAbsent(definition.name().toUpperCase(Locale.ROOT),
                    new CompilationArtifact.IndicatorVersion(definition.name().toUpperCase(Locale.ROOT), version));
        }

        private RegistryConfig.FinancialMetadata mergeFinancialMetadata(RegistryConfig.FinancialMetadata current,
                                                                        RegistryConfig.FinancialMetadata next,
                                                                        Ast.FunctionCall call) {
            if (next == null)
                throw new CompileException("FINANCIAL_METADATA", "Financial function requires point-in-time metadata: " + call.name(),
                        call.span().line(), call.span().column());
            if (current == null) return next;
            if (!current.equals(next))
                throw new CompileException("FINANCIAL_METADATA", "Financial functions use incompatible point-in-time metadata",
                        call.span().line(), call.span().column());
            return current;
        }

        private String signature(Ast.Expr expr) {
            return switch (expr) {
                case Ast.Identifier id -> id.name();
                case Ast.Literal l -> String.valueOf(l.value());
                case Ast.FunctionCall f -> f.name() + "(" + f.arguments().stream().map(this::signature).reduce((a,b) -> a + "," + b).orElse("") + ")";
                case Ast.Binary b -> "(" + signature(b.left()) + b.operator() + signature(b.right()) + ")";
                case Ast.Unary u -> u.operator() + signature(u.operand());
                case Ast.Between b -> signature(b.value()) + " BETWEEN " + signature(b.lower()) + " AND " + signature(b.upper());
                case Ast.InList in -> signature(in.value()) + " IN " + in.options().stream().map(this::signature).toList();
                case Ast.IsNull isNull -> signature(isNull.value()) + (isNull.negated() ? " IS NOT NULL" : " IS NULL");
                case Ast.NamedArgument named -> named.name() + "=" + signature(named.value());
            };
        }

        private String uniqueAlias(String proposed) {
            String base = proposed.replaceAll("[^a-zA-Z0-9_]", "_").toLowerCase(Locale.ROOT);
            if (!SAFE_ALIAS.matcher(base).matches()) base = "m_" + base;
            String alias = base;
            int suffix = 2;
            Set<String> used = new LinkedHashSet<>();
            used.addAll(baseFields); used.addAll(columnMetrics.keySet()); used.addAll(windowMetrics.keySet());
            used.addAll(changeMetrics.keySet()); used.addAll(rsiMetrics.keySet());
            while (used.contains(alias)) alias = base + "_" + suffix++;
            return alias;
        }

        private String q(String alias) {
            String value = alias.toLowerCase(Locale.ROOT);
            if (!SAFE_ALIAS.matcher(value).matches()) throw new IllegalArgumentException("Unsafe generated identifier: " + alias);
            return "`" + value + "`";
        }
    }
}
