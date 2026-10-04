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

public final class StockSlotSqlCompiler {
    public enum AccessPathMode { OPTIMIZED, FULL_SCAN_REFERENCE }
    private static final int DEFAULT_CACHE_CAPACITY = 256;
    private static final Pattern CHINESE_DATE = Pattern.compile("^(\\d{4})年(\\d{1,2})月(\\d{1,2})日$");
    private static final Pattern RANGE = Pattern.compile("^([\\[(])\\s*(-?\\d+(?:\\.\\d+)?%?)\\s*,\\s*(-?\\d+(?:\\.\\d+)?%?)\\s*([\\])])$");
    private final StockSlotRegistry registry;
    private final HistoricalExtremaFeatureCatalog historicalFeatures;
    private final RollingAverageFeatureCatalog rollingFeatures;
    private final StockSlotCompiler frontEnd;
    private final BoundedCache<String, StockSlotAst.Document> astCache;
    private final BoundedCache<String, StockSlotAst.SemanticModel> semanticCache;
    private final BoundedCache<CompileKey, StockSlotSqlArtifact> sqlTemplateCache;

    public StockSlotSqlCompiler() { this(new StockSlotRegistryLoader().loadDefault()); }
    public StockSlotSqlCompiler(StockSlotRegistry registry) { this(registry, DEFAULT_CACHE_CAPACITY); }
    public StockSlotSqlCompiler(StockSlotRegistry registry, int cacheCapacity) {
        this(registry, cacheCapacity, null);
    }
    public StockSlotSqlCompiler(StockSlotRegistry registry, int cacheCapacity, HistoricalExtremaFeatureCatalog historicalFeatures) {
        this(registry,cacheCapacity,historicalFeatures,null);
    }
    public StockSlotSqlCompiler(StockSlotRegistry registry, int cacheCapacity, HistoricalExtremaFeatureCatalog historicalFeatures,
                                RollingAverageFeatureCatalog rollingFeatures) {
        this.registry = registry;
        this.historicalFeatures = historicalFeatures;
        this.rollingFeatures = rollingFeatures;
        this.frontEnd = new StockSlotCompiler(registry);
        this.astCache = new BoundedCache<>(cacheCapacity);
        this.semanticCache = new BoundedCache<>(cacheCapacity);
        this.sqlTemplateCache = new BoundedCache<>(cacheCapacity);
    }

    public StockSlotSqlArtifact compile(String dsl) {
        return compile(dsl, AccessPathMode.OPTIMIZED);
    }

    /** Feature materializations belong to a specific validated source snapshot. */
    public StockSlotSqlArtifact compileForSnapshot(String dsl, String snapshotId) {
        return compileForSnapshot(dsl, snapshotId, null);
    }

    /** Historical features require the exact source manifest as well as snapshot identity. */
    public StockSlotSqlArtifact compileForSnapshot(String dsl, String snapshotId, String manifestSha256) {
        var artifact = compileProfiled(dsl, AccessPathMode.OPTIMIZED, true, snapshotId, manifestSha256).artifact();
        if (artifact.logicalPlan().stream().noneMatch(node -> node.kind().equals("FeatureScan"))) return artifact;
        for (var call : artifact.semanticModel().calls()) for (var slot : call.slots()) {
            if (!slot.name().equals("indicator_name")) continue;
            var indicator = registry.indicator(slot.rawValue());
            if (indicator.pattern() != null && !java.util.Objects.equals(snapshotId, indicator.parameters().get("featureSnapshotId")))
                return compile(dsl, AccessPathMode.FULL_SCAN_REFERENCE);
        }
        return artifact;
    }

    public StockSlotSqlArtifact compile(String dsl, AccessPathMode accessPathMode) {
        return compileProfiled(dsl, accessPathMode).artifact();
    }

    public StockSlotCompileProfile compileProfiled(String dsl) {
        return compileProfiled(dsl, AccessPathMode.OPTIMIZED);
    }

    public StockSlotCompileProfile compileProfiled(String dsl, AccessPathMode accessPathMode) {
        return compileProfiled(dsl, accessPathMode, true);
    }

    /** Benchmark entry point: executes every compiler phase while retaining the already loaded registry. */
    public StockSlotCompileProfile compileProfiledUncached(String dsl) {
        return compileProfiled(dsl, AccessPathMode.OPTIMIZED, false);
    }

    public void clearCaches() { astCache.clear(); semanticCache.clear(); sqlTemplateCache.clear(); }

    public CacheStats cacheStats() {
        var ast = astCache.stats(); var semantic = semanticCache.stats(); var sql = sqlTemplateCache.stats();
        return new CacheStats(ast.size(), semantic.size(), sql.size(), ast.capacity(),
                ast.hits(), ast.misses(), semantic.hits(), semantic.misses(), sql.hits(), sql.misses(),
                registry.indicatorCacheStats());
    }

    private StockSlotCompileProfile compileProfiled(String dsl, AccessPathMode accessPathMode, boolean useCaches) {
        return compileProfiled(dsl, accessPathMode, useCaches, null, null);
    }

    private StockSlotCompileProfile compileProfiled(String dsl, AccessPathMode accessPathMode, boolean useCaches,
                                                    String snapshotId, String manifestSha256) {
        long totalStart = System.nanoTime();
        frontEnd.validate(dsl);
        CompileKey key = new CompileKey(dsl, accessPathMode, snapshotId, manifestSha256);
        if (useCaches) {
            StockSlotSqlArtifact cached = sqlTemplateCache.get(key);
            if (cached != null) return profile(cached, 0, 0, 0, 0, 0, totalStart, true, true, true);
        }

        boolean astHit = false, semanticHit = false;
        long parseStart = System.nanoTime();
        StockSlotAst.Document document = useCaches ? astCache.get(dsl) : null;
        if (document == null) {
            document = frontEnd.parse(dsl);
            if (useCaches) astCache.put(dsl, document);
        } else astHit = true;
        long parseNanos = System.nanoTime() - parseStart;

        long semanticStart = System.nanoTime();
        StockSlotAst.SemanticModel model = useCaches ? semanticCache.get(dsl) : null;
        if (model == null) {
            var analyzed = frontEnd.analyze(document);
            if (!analyzed.diagnostics().isEmpty()) {
                StockSlotDiagnostic first = analyzed.diagnostics().getFirst();
                throw new CompileException(first.code(), first.message(), first.line(), first.column());
            }
            model = analyzed.semanticModel();
            if (useCaches) semanticCache.put(dsl, model);
        } else semanticHit = true;
        long semanticNanos = System.nanoTime() - semanticStart;

        long rewriteStart = System.nanoTime();
        StockSlotAst.SemanticModel rewritten = normalize(model);
        long rewriteNanos = System.nanoTime() - rewriteStart;

        long planningStart = System.nanoTime();
        boolean advanced = StockSlotAdvancedSqlCompiler.requiresAdvanced(rewritten, registry);
        long planningNanos = System.nanoTime() - planningStart;

        long sqlStart = System.nanoTime();
        StockSlotSqlArtifact artifact;
        if (advanced) {
            try {
                artifact = new StockSlotAdvancedSqlCompiler(rewritten, registry,
                        accessPathMode == AccessPathMode.OPTIMIZED, historicalFeatures, rollingFeatures, snapshotId, manifestSha256).generate();
            } catch (CompileException error) {
                if (!error.code().equals("EXECUTION_FEATURE_MIXED")) throw error;
                artifact = new StockSlotAdvancedSqlCompiler(rewritten, registry, false,
                        historicalFeatures, rollingFeatures, snapshotId, manifestSha256).generate();
            }
        } else artifact = new Generation(rewritten, accessPathMode).generate();
        long sqlNanos = System.nanoTime() - sqlStart;
        if (useCaches) sqlTemplateCache.put(key, artifact);
        return profile(artifact, parseNanos, semanticNanos, rewriteNanos, planningNanos, sqlNanos,
                totalStart, astHit, semanticHit, false);
    }

    private StockSlotAst.SemanticModel normalize(StockSlotAst.SemanticModel model) {
        // Semantic analysis already emits the canonical typed tree; this explicit phase is the stable rule hook.
        return model;
    }

    private StockSlotCompileProfile profile(StockSlotSqlArtifact artifact, long parse, long semantic,
                                            long rewrite, long planning, long sql, long totalStart,
                                            boolean astHit, boolean semanticHit, boolean sqlHit) {
        return new StockSlotCompileProfile(artifact, new StockSlotCompileProfile.Timings(parse, semantic,
                rewrite, planning, sql, System.nanoTime() - totalStart, astHit, semanticHit, sqlHit));
    }

    public record CacheStats(int astSize, int semanticSize, int sqlTemplateSize, int capacity,
                             long astHits, long astMisses, long semanticHits, long semanticMisses,
                             long sqlTemplateHits, long sqlTemplateMisses,
                             StockSlotRegistry.IndicatorCacheStats indicatorDefinitions) {}
    private record CompileKey(String dsl, AccessPathMode accessPathMode, String snapshotId, String manifestSha256) {}

    private record Metric(String expression, boolean extension) {}

    private final class Generation {
        private final StockSlotAst.SemanticModel model;
        private final AccessPathMode accessPathMode;
        private final LinkedHashMap<String, String> metricAliases = new LinkedHashMap<>();
        private final IdentityHashMap<StockSlotAst.FunctionCall, String> callAliases = new IdentityHashMap<>();
        private final LinkedHashMap<StockSlotAst.FunctionCall, RankSpec> ranks = new LinkedHashMap<>();
        private final List<Object> bindings = new ArrayList<>();
        private final List<StockSlotSqlArtifact.PlanNode> plan = new ArrayList<>();
        private final List<StockSlotWindowContract> contracts = new ArrayList<>();
        private LocalDate date;
        private String market = "";
        private boolean needsExtension;

        private Generation(StockSlotAst.SemanticModel model, AccessPathMode accessPathMode) {
            this.model = model;
            this.accessPathMode = accessPathMode;
        }

        private StockSlotSqlArtifact generate() {
            collect(model.document().expression());
            if (date == null) unsupported("EXECUTION_DATE_REQUIRED", "Executable subset requires one explicit date");

            StockSlotAst.Expr preFilter = null;
            StockSlotAst.Expr postFilter = model.document().expression();
            if (postFilter instanceof StockSlotAst.Binary binary && binary.operator().equals("THEN")) {
                preFilter = binary.left();
                postFilter = binary.right();
                if (containsThen(postFilter)) unsupported("EXECUTION_THEN_SHAPE", "Executable subset supports one top-level then");
            } else if (containsThen(postFilter)) {
                unsupported("EXECUTION_THEN_SHAPE", "Executable subset supports one top-level then");
            }

            StringBuilder sql = new StringBuilder("WITH base AS (\n  SELECT ")
                    .append(registry.column("basic", "marketCode")).append(" AS mktcode, ")
                    .append(registry.column("basic", "securityCode")).append(" AS tgtcode, ")
                    .append(registry.column("basic", "tradeDate")).append(" AS bizdate");
            metricAliases.forEach((expression, alias) -> sql.append(",\n    ").append(expression).append(" AS `").append(alias).append('`'));
            String basicView = registry.table("basic").qualifiedName();
            String extView = registry.table("extension").qualifiedName();
            sql.append("\n  FROM ").append(basicView).append(' ').append(registry.table("basic").alias()).append("\n");
            if (needsExtension) sql.append("  LEFT JOIN ").append(extView).append(' ').append(registry.table("extension").alias())
                    .append(" ON ").append(registry.column("extension", "marketCode")).append('=').append(registry.column("basic", "marketCode"))
                    .append(" AND ").append(registry.column("extension", "securityCode")).append('=').append(registry.column("basic", "securityCode"))
                    .append(" AND ").append(registry.column("extension", "tradeDate")).append('=').append(registry.column("basic", "tradeDate")).append("\n");
            String tradeDate = registry.column("basic", "tradeDate");
            if (accessPathMode == AccessPathMode.FULL_SCAN_REFERENCE)
                tradeDate = "DATE_FORMAT(" + tradeDate + ",'%Y-%m-%d')";
            sql.append("  WHERE ").append(tradeDate).append(" = ?");
            bindings.add(date);
            String marketPredicate = marketPredicate(market);
            if (!marketPredicate.isEmpty()) sql.append("\n    AND ").append(marketPredicate);
            sql.append("\n)");
            plan.add(new StockSlotSqlArtifact.PlanNode("Scan", basicView));
            if (needsExtension) plan.add(new StockSlotSqlArtifact.PlanNode("LeftJoin", extView + " on (mktcode,tgtcode,bizdate)"));
            plan.add(new StockSlotSqlArtifact.PlanNode("DateAndMarketFilter", date + (market.isEmpty() ? "" : " " + market)));

            String source = "base";
            if (preFilter != null) {
                sql.append(",\nprefiltered AS (\n  SELECT * FROM base WHERE ").append(render(preFilter)).append("\n)");
                source = "prefiltered";
                plan.add(new StockSlotSqlArtifact.PlanNode("Filter", "pre-rank predicate"));
            }
            if (!ranks.isEmpty()) {
                sql.append(",\nrank_input AS (\n  SELECT * FROM ").append(source).append(" WHERE ")
                        .append(String.join(" AND ", ranks.values().stream()
                                .map(rank -> "`" + rank.metricAlias() + "` IS NOT NULL").toList()))
                        .append("\n),\nranked AS (\n  SELECT rank_input.*");
                for (var entry : ranks.entrySet()) {
                    RankSpec rank = entry.getValue();
                    sql.append(",\n    DENSE_RANK() OVER (ORDER BY `").append(rank.metricAlias()).append("` ")
                            .append(rank.direction().toUpperCase(Locale.ROOT)).append(") AS `").append(rank.alias()).append('`');
                }
                sql.append("\n  FROM rank_input\n)");
                source = "ranked";
                plan.add(new StockSlotSqlArtifact.PlanNode("Rank", ranks.size() + " dense rank expression(s)"));
            }

            sql.append("\nSELECT mktcode, tgtcode\nFROM ").append(source).append("\nWHERE ").append(render(postFilter));
            boolean ordered = !ranks.isEmpty();
            if (ordered) {
                String first = ranks.values().iterator().next().alias();
                sql.append("\nORDER BY `").append(first).append("`, mktcode, tgtcode");
                plan.add(new StockSlotSqlArtifact.PlanNode("Sort", first + ", mktcode, tgtcode"));
            } else {
                sql.append("\nORDER BY mktcode, tgtcode");
                plan.add(new StockSlotSqlArtifact.PlanNode("Sort", "mktcode, tgtcode"));
            }
            StockSlotAst.SelectionLimit limit = model.document().selectionLimit();
            if (limit != null) {
                plan.add(new StockSlotSqlArtifact.PlanNode("CardinalityConstraint", limit.minimum() + "," + limit.maximum()));
                if (limit.maximum() != -1) sql.append("\nLIMIT ").append(limit.maximum());
            }
            sql.append(';');
            plan.add(new StockSlotSqlArtifact.PlanNode("Project", "mktcode,tgtcode"));
            return new StockSlotSqlArtifact(StockSlotCompiler.DSL_VERSION, model, plan, contracts, sql.toString(), bindings, ordered);
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
            var kind = function.lowering().kind();
            if (kind != StockSlotRegistryConfig.LoweringKind.INDICATOR && kind != StockSlotRegistryConfig.LoweringKind.RANK)
                unsupported("EXECUTION_FUNCTION_UNSUPPORTED", "No executable lowering for function: " + call.name());
            String marketValue = stringArg(call, 0, "market");
            mergeMarket(marketValue);
            String filterScope = stringArg(call, 1, "filter_scope");
            if (!filterScope.isEmpty()) unsupported("EXECUTION_SCOPE_UNSUPPORTED", "filter_scope requires an unavailable membership table: " + filterScope);
            String indicator = stringArg(call, 2, "indicator_name");
            var resolved = registry.indicator(indicator);
            if (resolved.pattern() != null) unsupported("EXECUTION_INDICATOR_WINDOW", "Pattern indicator requires window lowering: " + indicator);
            Metric metric = new Metric(registry.expression(resolved), registry.requiresTable(resolved, "extension"));
            boolean isRank = kind == StockSlotRegistryConfig.LoweringKind.RANK;
            String direction = isRank ? stringArg(call, 3, "direction") : null;
            int dateIndex = isRank ? 4 : 3;
            LocalDate callDate = parseDate(stringArg(call, dateIndex, "date"));
            if (date == null) date = callDate;
            else if (!date.equals(callDate)) unsupported("EXECUTION_MULTI_DATE_UNSUPPORTED", "Executable subset requires all functions to use the same date");
            int selectIndex = isRank ? 5 : 4;
            int aggIndex = isRank ? 6 : 5;
            int countIndex = isRank ? 7 : 6;
            if (!stringArg(call, selectIndex, "select_type").isEmpty()) unsupported("EXECUTION_SELECT_TYPE_UNSUPPORTED", "select_type data source is unavailable");
            if (!stringArg(call, aggIndex, "agg_func").isEmpty()) unsupported("EXECUTION_AGGREGATION_UNSUPPORTED", "Time aggregation is outside the first executable subset");
            if (!stringArg(call, countIndex, "count_exp").isEmpty()) unsupported("EXECUTION_COUNT_UNSUPPORTED", "CONS/EXIST execution is outside the first executable subset");

            String metricAlias = metricAliases.computeIfAbsent(metric.expression(), ignored -> "m" + (metricAliases.size() + 1));
            callAliases.put(call, metricAlias);
            needsExtension |= metric.extension();
            if (isRank) {
                if (!direction.equals("asc") && !direction.equals("desc")) unsupported("EXECUTION_DIRECTION", "rank direction must be asc or desc");
                ranks.put(call, new RankSpec("r" + (ranks.size() + 1), metricAlias, direction));
                contracts.add(new StockSlotWindowContract("rank:DENSE_RANK", List.of(), List.of(metricAlias),
                        "CROSS_SECTION", 1, "NOT_APPLICABLE", "NULL", "EXCLUDE_NULL_METRIC", false));
            }
        }

        private String render(StockSlotAst.Expr expression) {
            return switch (expression) {
                case StockSlotAst.Literal literal -> bind(literal.value());
                case StockSlotAst.Unary unary -> "(" + unary.operator() + render(unary.operand()) + ")";
                case StockSlotAst.FunctionCall call -> "`" + (registry.function(call.name()).lowering().kind() == StockSlotRegistryConfig.LoweringKind.RANK
                        ? ranks.get(call).alias() : callAliases.get(call)) + "`";
                case StockSlotAst.Binary binary -> renderBinary(binary);
            };
        }

        private String renderBinary(StockSlotAst.Binary binary) {
            String operator = binary.operator().toUpperCase(Locale.ROOT);
            if (operator.equals("THEN")) unsupported("EXECUTION_THEN_SHAPE", "then is only supported at the top level");
            if (operator.equals("BETWEEN")) return renderRange(binary.left(), binary.right());
            if (operator.equals("~=")) {
                String left = render(binary.left());
                String right = render(binary.right());
                bindings.add(new BigDecimal("0.000001"));
                return "(ABS(" + left + " - " + right + ") <= ?)";
            }
            return "(" + render(binary.left()) + " " + operator + " " + render(binary.right()) + ")";
        }

        private String renderRange(StockSlotAst.Expr value, StockSlotAst.Expr rangeExpression) {
            if (!(rangeExpression instanceof StockSlotAst.Literal literal) || !(literal.value() instanceof String)) {
                unsupported("EXECUTION_BETWEEN", "between range must be a string");
                return "FALSE";
            }
            String raw = (String) literal.value();
            Matcher matcher = RANGE.matcher(raw);
            if (!matcher.matches()) {
                unsupported("EXECUTION_BETWEEN", "Unsupported between range: " + raw);
                return "FALSE";
            }
            String rendered = render(value);
            bindings.add(number(matcher.group(2)));
            String upperValue = render(value);
            bindings.add(number(matcher.group(3)));
            String lower = matcher.group(1).equals("[") ? ">=" : ">";
            String upper = matcher.group(4).equals("]") ? "<=" : "<";
            return "(" + rendered + " " + lower + " ? AND " + upperValue + " " + upper + " ?)";
        }

        private BigDecimal number(String text) {
            return new BigDecimal(text.endsWith("%") ? text.substring(0, text.length() - 1) : text);
        }

        private String bind(Object value) { bindings.add(value); return "?"; }

        private String stringArg(StockSlotAst.FunctionCall call, int index, String slot) {
            if (!(call.arguments().get(index) instanceof StockSlotAst.Literal literal) || !(literal.value() instanceof String)) {
                unsupported("EXECUTION_SLOT", call.name() + "." + slot + " must be a string literal");
                return "";
            }
            return (String) literal.value();
        }

        private LocalDate parseDate(String raw) {
            try { return LocalDate.parse(raw, DateTimeFormatter.ISO_LOCAL_DATE); }
            catch (DateTimeParseException ignored) { }
            Matcher matcher = CHINESE_DATE.matcher(raw);
            if (matcher.matches()) return LocalDate.of(Integer.parseInt(matcher.group(1)),
                    Integer.parseInt(matcher.group(2)), Integer.parseInt(matcher.group(3)));
            unsupported("EXECUTION_DATE_UNSUPPORTED", "Date is not deterministic in the executable subset: " + raw);
            return null;
        }

        private void mergeMarket(String value) {
            if (value.isEmpty()) return;
            if (market.isEmpty()) market = value;
            else if (!market.equals(value)) unsupported("EXECUTION_MARKET_MISMATCH", "All functions must use the same market expression");
        }

        private String marketPredicate(String value) {
            if (value.isEmpty()) return "";
            return marketOr(value);
        }

        private String marketOr(String value) {
            List<String> terms = splitTop(value, '|');
            if (terms.size() > 1) return "(" + String.join(" OR ", terms.stream().map(this::marketXor).toList()) + ")";
            return marketXor(value);
        }
        private String marketXor(String value) {
            if (value.trim().startsWith("^")) return marketAnd(value);
            List<String> terms = splitTop(value, '^');
            if (terms.size() > 1) unsupported("EXECUTION_MARKET_XOR", "Binary ^ market expressions are not executable in the first subset");
            return marketAnd(value);
        }
        private String marketAnd(String value) {
            List<String> terms = splitTop(value, '&');
            if (terms.size() > 1) return "(" + String.join(" AND ", terms.stream().map(this::marketAtom).toList()) + ")";
            return marketAtom(value);
        }
        private String marketAtom(String value) {
            String term = value.trim();
            if (term.startsWith("^")) return "NOT (" + marketAtom(term.substring(1)) + ")";
            Integer code = registry.markets().get(term);
            if (code == null) {
                unsupported("EXECUTION_MARKET_UNSUPPORTED", "Market has no accepted code mapping: " + term);
                return "FALSE";
            }
            return registry.column("basic", "marketCode") + " = " + code;
        }
        private List<String> splitTop(String value, char separator) {
            List<String> result = new ArrayList<>();
            int start = 0;
            for (int i = 0; i < value.length(); i++) if (value.charAt(i) == separator) {
                result.add(value.substring(start, i)); start = i + 1;
            }
            result.add(value.substring(start));
            return result;
        }

        private boolean containsThen(StockSlotAst.Expr expression) {
            return switch (expression) {
                case StockSlotAst.Binary binary -> binary.operator().equals("THEN") || containsThen(binary.left()) || containsThen(binary.right());
                case StockSlotAst.Unary unary -> containsThen(unary.operand());
                default -> false;
            };
        }

        private void unsupported(String code, String message) {
            throw new CompileException(code, message, 1, 1);
        }

        private record RankSpec(String alias, String metricAlias, String direction) {}
    }
}
