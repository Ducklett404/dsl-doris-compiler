package com.acme.dorisdsl.plan;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.registry.RegistryConfig;

import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class AccessPathPlanner {
    private static final double UNSUPPORTED = 1_000_000_000_000_000d;
    private static final double STALE = 1_000_000_000_000d;
    private final Registry registry;
    private final CatalogSnapshot catalog;

    public AccessPathPlanner(Registry registry, CatalogSnapshot catalog) {
        this.registry = registry;
        this.catalog = catalog;
    }

    public LogicalPlan.AccessPathDecision choose(Ast.Query query, int lookback, boolean needsFinancial) {
        boolean hasWindow = containsKind(query.where(), RegistryConfig.LoweringKind.WINDOW_AVG);
        boolean featureCovered = allFunctionsFeatureBacked(query.where());
        boolean fresh = !catalog.feature().refreshedAt()
                .isBefore(query.asOf().atStartOfDay(ZoneOffset.UTC).toInstant());
        var detail = metadata("DETAIL");
        boolean hasIndex = detail != null && !detail.indexes().isEmpty();
        boolean hasBuckets = detail != null && detail.bucketInfo() != null && detail.bucketInfo().count() > 0;
        boolean hasMv = detail != null && !detail.materializedViews().isEmpty();

        List<LogicalPlan.Candidate> candidates = List.of(
                candidate("DETAIL_TABLE", "DETAIL", lookback, needsFinancial, true, false, false, List.of()),
                candidate("PARTITION_BUCKET_INDEX", "DETAIL", lookback, needsFinancial, hasIndex && hasBuckets,
                        false, false, reasons(hasIndex && hasBuckets, "No usable bucket/index metadata")),
                candidate("PREFIX_DAILY", "PREFIX_DAILY", lookback, needsFinancial,
                        hasWindow && catalog.doris().supports("prefixDaily"), false,
                        !catalog.doris().supports("prefixDaily"), reasons(hasWindow, "No supported window aggregate")),
                candidate("FEATURE_DAILY", "FEATURE_DAILY", lookback, needsFinancial,
                        featureCovered && fresh, !fresh, false,
                        combine(reasons(featureCovered, "Referenced expressions are not fully feature-backed"),
                                reasons(fresh, "Feature snapshot is stale for target date"))),
                candidate("MATERIALIZED_VIEW", "DETAIL", lookback, needsFinancial,
                        hasMv && fresh && catalog.doris().supports("materializedViewRewrite"), !fresh,
                        !catalog.doris().supports("materializedViewRewrite"),
                        combine(reasons(hasMv, "No applicable materialized view"), reasons(fresh, "Materialized view is stale"))),
                candidate("QUERY_CACHE_FRIENDLY", "DETAIL", lookback, needsFinancial,
                        catalog.doris().supports("queryCache"), false, !catalog.doris().supports("queryCache"),
                        reasons(catalog.doris().supports("queryCache"), "Doris query cache capability is unavailable"))
        );

        LogicalPlan.Candidate selected;
        String reason;
        if (!fresh) {
            selected = candidates.get(0);
            reason = "Freshness requirement failed; mandatory fallback to DETAIL_TABLE";
        } else {
            selected = candidates.stream().filter(LogicalPlan.Candidate::eligible)
                    .min(Comparator.comparingDouble(LogicalPlan.Candidate::cost)).orElse(candidates.get(0));
            reason = "Selected lowest-cost eligible candidate using the rule-based cost model";
        }
        return new LogicalPlan.AccessPathDecision(selected.path(), candidates, reason);
    }

    private LogicalPlan.Candidate candidate(String path, String metadataKey, int lookback, boolean needsFinancial,
                                            boolean eligible, boolean stale, boolean unsupported,
                                            List<String> eliminationReasons) {
        if (!eligible && unsupported && eliminationReasons.isEmpty())
            eliminationReasons = List.of("Required Doris capability is unavailable");
        var metadata = metadata(metadataKey);
        double scan = estimatedScanBytes(metadata, lookback);
        if (path.equals("PARTITION_BUCKET_INDEX")) scan *= 0.12;
        if (path.equals("MATERIALIZED_VIEW")) scan *= 0.08;
        if (path.equals("QUERY_CACHE_FRIENDLY")) scan *= 0.04;
        double window = lookback == 0 ? 0 : scan * Math.log1p(lookback) / 12.0;
        if (path.equals("PREFIX_DAILY") || path.equals("FEATURE_DAILY") || path.equals("MATERIALIZED_VIEW")) window *= 0.05;
        double join = needsFinancial && !path.equals("FEATURE_DAILY") ? scan * 0.30 : 0;
        var costs = new LogicalPlan.CostBreakdown(scan, window, join, stale ? STALE : 0, unsupported ? UNSUPPORTED : 0);
        String explanation = eligible
                ? "Eligible; cost=" + costs.total()
                : "Eliminated: " + String.join("; ", eliminationReasons);
        return new LogicalPlan.Candidate(path, costs, eligible, eliminationReasons, explanation);
    }

    private double estimatedScanBytes(CatalogSnapshot.TableMetadata metadata, int lookback) {
        if (metadata == null || metadata.estimatedRows() <= 0 || metadata.estimatedRowBytes() <= 0) return UNSUPPORTED;
        double dateFraction = Math.min(1.0, Math.max(1, lookback + 1) / 250.0);
        return metadata.estimatedRows() * (double) metadata.estimatedRowBytes() * dateFraction;
    }

    private CatalogSnapshot.TableMetadata metadata(String key) { return catalog.tableMetadata().get(key); }
    private List<String> reasons(boolean condition, String reason) { return condition ? List.of() : List.of(reason); }
    private List<String> combine(List<String> first, List<String> second) {
        List<String> result = new ArrayList<>(first); result.addAll(second); return result;
    }

    private boolean containsKind(Ast.Expr expr, RegistryConfig.LoweringKind kind) {
        if (expr == null) return false;
        if (expr instanceof Ast.FunctionCall call) {
            if (registry.function(call.name(), call.span().line(), call.span().column()).loweringKind() == kind) return true;
            return call.arguments().stream().anyMatch(e -> containsKind(e, kind));
        }
        if (expr instanceof Ast.Binary e) return containsKind(e.left(), kind) || containsKind(e.right(), kind);
        if (expr instanceof Ast.Unary e) return containsKind(e.operand(), kind);
        if (expr instanceof Ast.Between e) return containsKind(e.value(), kind) || containsKind(e.lower(), kind) || containsKind(e.upper(), kind);
        if (expr instanceof Ast.InList e) return containsKind(e.value(), kind) || e.options().stream().anyMatch(v -> containsKind(v, kind));
        return false;
    }

    private boolean allFunctionsFeatureBacked(Ast.Expr expr) {
        if (expr == null) return false;
        List<Ast.FunctionCall> calls = new ArrayList<>();
        collect(expr, calls);
        return !calls.isEmpty() && calls.stream().allMatch(call -> {
            var fn = registry.function(call.name(), call.span().line(), call.span().column());
            return fn.featureColumn() != null && !fn.featureColumn().isBlank();
        });
    }

    private void collect(Ast.Expr expr, List<Ast.FunctionCall> out) {
        if (expr instanceof Ast.FunctionCall call) { out.add(call); call.arguments().forEach(e -> collect(e, out)); }
        else if (expr instanceof Ast.Binary e) { collect(e.left(), out); collect(e.right(), out); }
        else if (expr instanceof Ast.Unary e) collect(e.operand(), out);
        else if (expr instanceof Ast.Between e) { collect(e.value(), out); collect(e.lower(), out); collect(e.upper(), out); }
        else if (expr instanceof Ast.InList e) { collect(e.value(), out); e.options().forEach(v -> collect(v, out)); }
    }
}
