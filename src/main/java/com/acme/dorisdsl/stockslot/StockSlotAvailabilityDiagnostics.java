package com.acme.dorisdsl.stockslot;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.*;

/** Bounded evidence from actual observations. SQL availability flags remain authoritative. */
public final class StockSlotAvailabilityDiagnostics {
    public static final int MAX_SAMPLES = 20, MAX_HISTORY = 10001, MAX_FIELDS = 32, MAX_DATES = 20;
    private static final int MAX_WORK_PER_INPUT = 250000;
    private static final MathContext MC = MathContext.DECIMAL128;
    private StockSlotAvailabilityDiagnostics() {}

    public record Field(String table, String field) {}
    public record FetchPlan(String sql, List<Object> bindings, List<Field> fields, int historyRows, int maxRows) {
        public FetchPlan { bindings = List.copyOf(bindings); fields = List.copyOf(fields); }
    }
    public record Reason(String code, String indicator, int requiredObservations, int minimumObserved,
                         int maximumObserved, List<String> relatedDates, int totalRelatedDates, boolean datesTruncated) {
        public Reason { relatedDates = List.copyOf(relatedDates); }
    }
    public record InputIssue(String inputId, String function, String indicator, String window, String role,
                             String status, List<Reason> reasons) {
        public InputIssue { reasons = List.copyOf(reasons); }
    }
    public record SampleDetail(String marketCode, String securityCode, String evaluationDate,
                               boolean currentExtensionMissing, boolean historyTruncated,
                               List<InputIssue> inputs) {
        public SampleDetail { inputs = List.copyOf(inputs); }
    }
    private record Key(String market, String code) {}
    private record Observation(LocalDate date, boolean extension, Map<Field, BigDecimal> values) {}
    private static final class Partial extends RuntimeException {
        final String code;
        Partial(String code) { this.code = code; }
    }

    static StockSlotCoveragePlan.Input describe(StockSlotCoveragePlan.Input input, StockSlotRegistry registry, LocalDate date) {
        int needed = dependency(input.expression(), registry);
        int required = input.role().equals("COUNT_RESULT") ? input.horizon()
                : input.role().equals("COUNT_INPUT") ? (needed == 0 ? 0 : needed + input.horizon() - 1) : needed;
        String window = input.role().startsWith("COUNT") ? input.horizon() + " 条条件观察；指标完整依赖 "
                + (required == 0 ? "截至评价日的历史" : required + " 条观察")
                : needed == 0 ? "截至评价日的历史 / 跨证券来源" : needed + " 条观察记录";
        String identity = registry.fingerprint() + "|" + date + "|" + input.role() + "|" + input.horizon()
                + "|" + canonical(valueIdentity(input, registry));
        try {
            String id = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(identity.getBytes(StandardCharsets.UTF_8)));
            return new StockSlotCoveragePlan.Input(input.function(), input.indicator(), input.alias(), id, window,
                    input.role(), required, input.expression(), input.horizon());
        } catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    private static StockSlotAst.Expr valueIdentity(StockSlotCoveragePlan.Input input, StockSlotRegistry registry) {
        if (!input.role().equals("VALUE") || !(input.expression() instanceof StockSlotAst.FunctionCall f)) return input.expression();
        var arguments = new ArrayList<>(f.arguments());
        var parameters = registry.function(f.name()).parameters();
        for (int i = 0; i < parameters.size(); i++) if (parameters.get(i).name().equals("count_exp"))
            arguments.set(i, new StockSlotAst.Literal("", StockSlotAst.ValueType.STRING, f.span()));
        return new StockSlotAst.FunctionCall(f.name(), arguments, f.type(), f.span());
    }

    // Source spans, aliases, document order and LIMIT are deliberately excluded.
    private static String canonical(StockSlotAst.Expr expr) {
        return switch (expr) {
            case StockSlotAst.Literal l -> l.value() instanceof BigDecimal n ? "N:" + n.stripTrailingZeros().toPlainString()
                    : "S:" + String.valueOf(l.value()).length() + ":" + l.value();
            case StockSlotAst.FunctionCall f -> f.name().toLowerCase(Locale.ROOT) + "(" + f.arguments().stream()
                    .map(StockSlotAvailabilityDiagnostics::canonical).collect(java.util.stream.Collectors.joining(",")) + ")";
            case StockSlotAst.Binary b -> "(" + canonical(b.left()) + b.operator() + canonical(b.right()) + ")";
            case StockSlotAst.Unary u -> u.operator() + "(" + canonical(u.operand()) + ")";
        };
    }

    private static String arg(StockSlotAst.FunctionCall call, int index) {
        return String.valueOf(((StockSlotAst.Literal) call.arguments().get(index)).value());
    }
    private static String indicator(StockSlotAst.FunctionCall call, StockSlotRegistry registry) {
        String value = arg(call, 2);
        return value.isEmpty() ? registry.function(call.name()).lowering().parameters().get("defaultIndicator") : value;
    }
    private static int dependency(StockSlotAst.Expr expression, StockSlotRegistry registry) {
        if (expression instanceof StockSlotAst.Binary b) {
            int a = dependency(b.left(), registry), c = dependency(b.right(), registry);
            return a == 0 || c == 0 ? 0 : Math.max(a, c);
        }
        if (expression instanceof StockSlotAst.Unary u) return dependency(u.operand(), registry);
        if (!(expression instanceof StockSlotAst.FunctionCall call)) return 1;
        return switch (registry.function(call.name()).lowering().kind()) {
            case INDICATOR, RANK -> {
                var resolved = registry.indicator(arg(call, 2));
                yield switch (resolved.lowering().kind()) {
                    case WINDOW_AVG -> Integer.parseInt(resolved.parameters().get("N"));
                    case RSI -> Integer.parseInt(resolved.parameters().get("N")) + 1;
                    default -> registry.function(call.name()).lowering().kind() == StockSlotRegistryConfig.LoweringKind.INDICATOR
                            && !arg(call, 5).isEmpty() ? lookback(arg(call, 3)) : 1;
                };
            }
            case RANGE_WINDOW -> arg(call, 3).equals("历史") ? 0 : Integer.parseInt(arg(call, 3).replace("日", ""));
            case PAIR_WINDOW -> registry.function(call.name()).lowering().parameters().get("mode").equals("CLOSE_TOGETHER") ? 1 : 2;
            default -> 0;
        };
    }
    private static int lookback(String date) {
        var matcher = java.util.regex.Pattern.compile("(?:近|前)(\\d+)日$").matcher(date);
        if (!matcher.find()) throw new Partial("DETAIL_NOT_SUPPORTED");
        return Integer.parseInt(matcher.group(1));
    }
    private static Field field(StockSlotRegistry registry, String name, boolean position) {
        var resolved = registry.indicator(name);
        if (resolved.exact() == null) return field(registry, resolved.parameters().get("baseIndicator"), false);
        var source = resolved.exact().source();
        String column = position ? resolved.lowering().parameters().getOrDefault("positionField", registry.field(source.table(), source.field()))
                : registry.field(source.table(), source.field());
        if (column == null || !Set.of("basic", "extension").contains(source.table())) throw new Partial("DETAIL_NOT_SUPPORTED");
        return new Field(source.table(), column);
    }
    // Fixed project-view dependencies; never interpolate DSL text as a raw column name.
    private static List<String> operands(StockSlotRegistry registry, String name) {
        var resolved = registry.indicator(name);
        if (resolved.exact() == null || !resolved.exact().source().table().equals("basic")
                || !registry.table("basic").qualifiedName().equals("newzl.v_hsj_stock_hq_basic")) return List.of();
        return switch (registry.field("basic", resolved.exact().source().field())) {
            case "marketValue" -> List.of("lastPx", "totalShare");
            case "listedMarketValue" -> List.of("lastPx", "listedShare");
            case "risePct" -> List.of("lastPx", "preClosePx");
            case "avgPx" -> List.of("turnover", "volume");
            case "closeQfq" -> List.of("closePx", "qfqMulti", "qfqAdd");
            case "closeHfq" -> List.of("closePx", "hfqMulti", "hfqAdd");
            default -> List.of();
        };
    }
    private static void addField(StockSlotRegistry registry, String name, boolean position, Set<Field> output) {
        output.add(field(registry, name, position));
        operands(registry, name).forEach(column -> output.add(new Field("basic", column)));
    }
    private static void fields(StockSlotAst.Expr expression, StockSlotRegistry registry, Set<Field> output) {
        if (expression instanceof StockSlotAst.Binary b) { fields(b.left(), registry, output); fields(b.right(), registry, output); }
        else if (expression instanceof StockSlotAst.Unary u) fields(u.operand(), registry, output);
        else if (expression instanceof StockSlotAst.FunctionCall f) {
            var kind = registry.function(f.name()).lowering().kind();
            try {
                switch (kind) {
                    case INDICATOR, RANK -> addField(registry, arg(f, 2), false, output);
                    case RANGE_WINDOW -> addField(registry, indicator(f, registry),
                            registry.function(f.name()).lowering().parameters().get("mode").equals("POSITION"), output);
                    case PAIR_WINDOW -> { addField(registry, arg(f, 2), false, output); addField(registry, arg(f, 3), false, output); }
                    default -> { /* Cross-security lookups need separate evidence; never guess. */ }
                }
            } catch (Partial ignored) { }
        }
    }

    /** At most 20 keys, registered values and fixed project operands, tail before the three-key join. */
    public static FetchPlan fetchPlan(StockSlotCoveragePlan coverage, StockSlotRegistry registry, List<List<String>> samples) {
        if (samples.isEmpty() || samples.size() > MAX_SAMPLES) throw new IllegalArgumentException("Expected 1..20 samples");
        var columns = new LinkedHashSet<Field>();
        coverage.inputs().forEach(i -> fields(i.expression(), registry, columns));
        if (columns.size() > MAX_FIELDS) throw new Partial("DETAIL_FIELD_LIMIT");
        int history = coverage.inputs().stream().mapToInt(i -> i.requiredObservations() == 0 ? MAX_HISTORY : i.requiredObservations()).max().orElse(1);
        history = Math.min(MAX_HISTORY, history);
        var bindings = new ArrayList<Object>(); bindings.add(coverage.evaluationDate());
        var predicates = new ArrayList<String>();
        for (var sample : samples) {
            if (sample.size() != coverage.inputs().size() + 3) throw new IllegalArgumentException("Invalid sample flag width");
            predicates.add("(" + registry.column("basic", "marketCode") + "=? AND " + registry.column("basic", "securityCode") + "=?)");
            bindings.add(Integer.parseInt(sample.get(0))); bindings.add(sample.get(1));
        }
        var fields = List.copyOf(columns);
        var sql = new StringBuilder("WITH diagnostic_history AS (SELECT ")
                .append(registry.column("basic", "marketCode")).append(" AS mktcode,")
                .append(registry.column("basic", "securityCode")).append(" AS tgtcode,")
                .append(registry.column("basic", "tradeDate")).append(" AS bizdate");
        for (int i = 0; i < fields.size(); i++) if (fields.get(i).table().equals("basic"))
            sql.append(',').append(registry.table("basic").alias()).append('.').append(fields.get(i).field()).append(" AS v").append(i);
        sql.append(",ROW_NUMBER() OVER (PARTITION BY ").append(registry.column("basic", "marketCode")).append(',')
                .append(registry.column("basic", "securityCode")).append(" ORDER BY ").append(registry.column("basic", "tradeDate"))
                .append(" DESC) AS rn FROM ").append(registry.table("basic").qualifiedName()).append(' ').append(registry.table("basic").alias())
                .append(" WHERE ").append(registry.column("basic", "tradeDate")).append("<=? AND (").append(String.join(" OR ", predicates))
                .append(")),diagnostic_tail AS (SELECT * FROM diagnostic_history WHERE rn<=").append(history + 1).append(")\n")
                .append("SELECT t.mktcode,t.tgtcode,t.bizdate,");
        boolean extension = coverage.extensionRequired() || fields.stream().anyMatch(f -> f.table().equals("extension"));
        sql.append(extension ? "CASE WHEN x." + registry.field("extension", "securityCode") + " IS NULL THEN 0 ELSE 1 END" : "1");
        for (int i = 0; i < fields.size(); i++) sql.append(',').append(fields.get(i).table().equals("basic") ? "t.v" + i : "x." + fields.get(i).field());
        sql.append(" FROM diagnostic_tail t");
        if (extension) sql.append(" LEFT JOIN ").append(registry.table("extension").qualifiedName()).append(" x ON x.")
                .append(registry.field("extension", "marketCode")).append("=t.mktcode AND x.")
                .append(registry.field("extension", "securityCode")).append("=t.tgtcode AND x.")
                .append(registry.field("extension", "tradeDate")).append("=t.bizdate");
        sql.append(" ORDER BY t.mktcode,t.tgtcode,t.bizdate;");
        return new FetchPlan(sql.toString(), bindings, fields, history, samples.size() * (history + 1));
    }

    public static List<SampleDetail> explain(StockSlotCoveragePlan coverage, StockSlotRegistry registry,
                                           List<List<String>> samples, FetchPlan fetch, List<List<String>> rawRows) {
        if (rawRows.size() > fetch.maxRows()) throw new IllegalArgumentException("Diagnostic row limit exceeded");
        var histories = new HashMap<Key, List<Observation>>();
        for (var row : rawRows) {
            if (row.size() != fetch.fields().size() + 4) throw new IllegalArgumentException("Diagnostic field width mismatch");
            var values = new HashMap<Field, BigDecimal>();
            for (int i = 0; i < fetch.fields().size(); i++) {
                String raw = row.get(i + 4);
                values.put(fetch.fields().get(i), raw == null || raw.equals("NULL") ? null : new BigDecimal(raw));
            }
            histories.computeIfAbsent(new Key(row.get(0), row.get(1)), k -> new ArrayList<>())
                    .add(new Observation(LocalDate.parse(row.get(2)), row.get(3).equals("1"), values));
        }
        var output = new ArrayList<SampleDetail>();
        for (var sample : samples) {
            var history = histories.getOrDefault(new Key(sample.get(0), sample.get(1)), List.of()).stream()
                    .sorted(Comparator.comparing(Observation::date)).toList();
            boolean clipped = history.size() > fetch.historyRows();
            if (clipped) history = history.subList(history.size() - fetch.historyRows(), history.size());
            var issues = new ArrayList<InputIssue>();
            for (int i = 0; i < coverage.inputs().size(); i++) if ("1".equals(sample.get(i + 3))) {
                var input = coverage.inputs().get(i);
                var evaluator = new Evaluator(registry, history, clipped);
                String status = "EXPLAINED";
                try {
                    if (history.isEmpty() || !history.getLast().date().equals(coverage.evaluationDate())) throw new Partial("DIAGNOSTIC_HISTORY_MISSING");
                    if (input.role().startsWith("COUNT")) {
                        evaluator.complete(input.horizon(), history.size() - 1, input.function());
                        if (input.role().equals("COUNT_INPUT")) {
                            int first = Math.max(0, history.size() - input.horizon());
                            for (int j = first; j < history.size(); j++) if (evaluator.eval(input.expression(), j) == null)
                                evaluator.cause("UNKNOWN_PREDICATE", input.indicator(), 0, 0, history.get(j).date());
                        }
                    } else evaluator.eval(input.expression(), history.size() - 1);
                    if (evaluator.causes.isEmpty()) throw new Partial("UNCLASSIFIED_SQL_NULL");
                } catch (Partial limit) {
                    status = "PARTIAL_DETAIL";
                    evaluator.cause(limit.code, input.indicator(), input.requiredObservations(), history.size(), coverage.evaluationDate());
                }
                issues.add(new InputIssue(input.inputId(), input.function(), input.indicator(), input.window(), input.role(), status, evaluator.reasons()));
            }
            output.add(new SampleDetail(sample.get(0), sample.get(1), coverage.evaluationDate().toString(), "1".equals(sample.get(2)), clipped, issues));
        }
        return List.copyOf(output);
    }

    public static List<SampleDetail> unavailable(StockSlotCoveragePlan coverage, List<List<String>> samples, String code) {
        return samples.stream().map(s -> {
            var issues = new ArrayList<InputIssue>();
            for (int i = 0; i < coverage.inputs().size(); i++) if ("1".equals(s.get(i + 3))) {
                var input = coverage.inputs().get(i);
                issues.add(new InputIssue(input.inputId(), input.function(), input.indicator(), input.window(), input.role(),
                        "PARTIAL_DETAIL", List.of(new Reason(code, input.indicator(), input.requiredObservations(), 0, 0,
                        List.of(), 0, false))));
            }
            return new SampleDetail(s.get(0), s.get(1), coverage.evaluationDate().toString(), "1".equals(s.get(2)), false, issues);
        }).toList();
    }
    static String failureCode(RuntimeException error) { return error instanceof Partial p ? p.code : "DETAIL_NOT_SUPPORTED"; }

    public static String reasonLabel(String code) {
        return switch (code) {
            case "INSUFFICIENT_OBSERVATIONS" -> "观察记录不足（不推测缺少哪些交易日）";
            case "SOURCE_NULL" -> "来源指标值为 NULL";
            case "SOURCE_OPERAND_NULL" -> "派生指标的原始计算字段为 NULL";
            case "SENTINEL_VALUE" -> "注册表规定的哨兵值";
            case "EXTENSION_ROW_MISSING" -> "该观察日缺少衍生行情";
            case "FLAT_WINDOW" -> "区间最高值等于最低值";
            case "ZERO_LOSS_DENOMINATOR" -> "RSI 平均下跌幅为零";
            case "ZERO_DENOMINATOR" -> "分母为零";
            case "UNKNOWN_PREDICATE" -> "该观察日条件无法判定";
            case "DETAIL_HISTORY_LIMIT" -> "历史检查达到上限，原因未完整确定";
            case "DETAIL_WORK_LIMIT" -> "解释计算达到上限，原因未完整确定";
            case "DETAIL_FIELD_LIMIT" -> "解释所需字段超过 32 列上限";
            case "DETAIL_SCAN_LIMIT" -> "解释查询的扫描估算超过预算";
            case "DETAIL_ROW_LIMIT" -> "解释查询返回行数超过预算";
            case "DETAIL_QUERY_UNAVAILABLE" -> "解释查询失败或超时";
            case "DIAGNOSTIC_HISTORY_MISSING" -> "解释查询未取得该证券的评价日记录";
            case "UNCLASSIFIED_SQL_NULL" -> "SQL 已确认缺值，尚未归类原因";
            default -> "该输入暂不支持完整日期解释";
        };
    }

    private static final class Accumulator {
        final String code, indicator; final int required;
        int minimum = Integer.MAX_VALUE, maximum;
        final SortedSet<String> dates = new TreeSet<>();
        Accumulator(String code, String indicator, int required) { this.code = code; this.indicator = indicator; this.required = required; }
    }
    private static final class Evaluator {
        final StockSlotRegistry registry; final List<Observation> rows; final boolean clipped;
        final Map<String, Accumulator> causes = new LinkedHashMap<>();
        int work = MAX_WORK_PER_INPUT;
        boolean quiet;
        Evaluator(StockSlotRegistry registry, List<Observation> rows, boolean clipped) { this.registry = registry; this.rows = rows; this.clipped = clipped; }
        void cause(String code, String metric, int required, int observed, LocalDate date) {
            if (quiet) return;
            String key = code + "|" + metric + "|" + required;
            var a = causes.computeIfAbsent(key, k -> new Accumulator(code, metric, required));
            a.minimum = Math.min(a.minimum, observed); a.maximum = Math.max(a.maximum, observed); a.dates.add(date.toString());
        }
        List<Reason> reasons() { return causes.values().stream().map(a -> new Reason(a.code, a.indicator, a.required,
                a.minimum, a.maximum, a.dates.stream().limit(MAX_DATES).toList(), a.dates.size(), a.dates.size() > MAX_DATES)).toList(); }
        boolean complete(int n, int at, String metric) {
            if (at + 1 >= n) return true;
            if (clipped) throw new Partial("DETAIL_HISTORY_LIMIT");
            cause("INSUFFICIENT_OBSERVATIONS", metric, n, at + 1, rows.get(at).date()); return false;
        }
        BigDecimal raw(String name, int at, boolean position) {
            if (--work < 0) throw new Partial("DETAIL_WORK_LIMIT");
            var resolved = registry.indicator(name);
            if (resolved.exact() == null) throw new Partial("DETAIL_NOT_SUPPORTED");
            Field field = field(registry, name, position);
            Observation row = rows.get(at);
            if (field.table().equals("extension") && !row.extension()) {
                cause("EXTENSION_ROW_MISSING", name, 1, 0, row.date()); return null;
            }
            BigDecimal value = row.values().get(field);
            if (value == null) {
                var dependencies = operands(registry, name);
                if (dependencies.isEmpty()) cause("SOURCE_NULL", name, 1, 1, row.date());
                else {
                    boolean explained = false;
                    for (String column : dependencies) {
                        var source = new Field("basic", column);
                        if (!row.values().containsKey(source)) throw new Partial("DETAIL_NOT_SUPPORTED");
                        BigDecimal operand = row.values().get(source);
                        if (operand == null) {
                            cause("SOURCE_OPERAND_NULL", name + " / " + column, 1, 1, row.date()); explained = true;
                        } else if ((column.equals("volume") || column.equals("preClosePx")) && operand.signum() == 0) {
                            cause("ZERO_DENOMINATOR", name + " / " + column, 1, 1, row.date()); explained = true;
                        }
                    }
                    if (!explained) throw new Partial("UNCLASSIFIED_SQL_NULL");
                }
                return null;
            }
            BigDecimal sourceValue = value;
            if (resolved.exact().sentinelValues().stream().anyMatch(s -> s.compareTo(sourceValue) == 0)) {
                cause("SENTINEL_VALUE", name, 1, 1, row.date()); return null;
            }
            var scale = resolved.exact().scale();
            // A companion is already in normalized units; the compiler casts every position input.
            if (!position || !resolved.lowering().parameters().containsKey("positionField"))
                value = value.multiply(scale.multiply()).divide(scale.divide(), MC);
            return position ? value.setScale(Integer.parseInt(resolved.lowering().parameters().getOrDefault("positionScale", "12")), RoundingMode.HALF_UP) : value;
        }
        List<BigDecimal> window(String name, int n, int at, boolean position, boolean unbounded) {
            if (unbounded && clipped) throw new Partial("DETAIL_HISTORY_LIMIT");
            complete(n, at, name);
            var values = new ArrayList<BigDecimal>();
            for (int j = Math.max(0, at - n + 1); j <= at; j++) {
                quiet = unbounded && j < at;
                try { values.add(raw(name, j, position)); } finally { quiet = false; }
            }
            return values;
        }
        Object call(StockSlotAst.FunctionCall call, int at) {
            var definition = registry.function(call.name());
            switch (definition.lowering().kind()) {
                case INDICATOR, RANK -> {
                    String name = arg(call, 2); var resolved = registry.indicator(name);
                    if (resolved.exact() != null) {
                        if (definition.lowering().kind() != StockSlotRegistryConfig.LoweringKind.INDICATOR || arg(call, 5).isEmpty())
                            return raw(name, at, false);
                        int size = lookback(arg(call, 3));
                        var values = window(name, size, at, false, false);
                        if (values.size() < size || values.contains(null)) return null;
                        return switch (arg(call, 5).toUpperCase(Locale.ROOT)) {
                            case "MIN" -> Collections.min(values); case "MAX" -> Collections.max(values);
                            case "SUM" -> values.stream().reduce(BigDecimal.ZERO, BigDecimal::add);
                            case "AVG" -> values.stream().reduce(BigDecimal.ZERO, BigDecimal::add).divide(BigDecimal.valueOf(size), MC);
                            default -> throw new Partial("DETAIL_NOT_SUPPORTED");
                        };
                    }
                    int n = Integer.parseInt(resolved.parameters().get("N"));
                    boolean rsi = resolved.lowering().kind() == StockSlotRegistryConfig.LoweringKind.RSI;
                    if (!rsi && resolved.lowering().kind() != StockSlotRegistryConfig.LoweringKind.WINDOW_AVG) throw new Partial("DETAIL_NOT_SUPPORTED");
                    int size = n + (rsi ? 1 : 0);
                    var values = window(resolved.parameters().get("baseIndicator"), size, at, false, false);
                    if (values.size() < size || values.contains(null)) return null;
                    if (!rsi) return values.stream().reduce(BigDecimal.ZERO, BigDecimal::add).divide(BigDecimal.valueOf(n), MC);
                    BigDecimal gains = BigDecimal.ZERO, loss = BigDecimal.ZERO;
                    for (int j = 1; j < values.size(); j++) {
                        BigDecimal delta = values.get(j).subtract(values.get(j - 1));
                        if (delta.signum() > 0) gains = gains.add(delta); else loss = loss.subtract(delta);
                    }
                    if (loss.signum() == 0) { evidence("ZERO_LOSS_DENOMINATOR", name, size, at); return null; }
                    return gains.multiply(BigDecimal.valueOf(100)).divide(gains.add(loss), MC);
                }
                case RANGE_WINDOW -> {
                    String name = indicator(call, registry), mode = definition.lowering().parameters().get("mode");
                    boolean unbounded = arg(call, 3).equals("历史");
                    int n = unbounded ? at + 1 : Integer.parseInt(arg(call, 3).replace("日", ""));
                    var values = window(name, n, at, mode.equals("POSITION"), unbounded);
                    BigDecimal current = values.getLast();
                    if (current == null || (!unbounded && (values.size() < n || values.contains(null)))) return null;
                    // Unbounded MIN/MAX ignore old NULL observations under the frozen SQL rules.
                    if (unbounded) values.removeIf(Objects::isNull);
                    if (values.isEmpty()) return null;
                    BigDecimal min = Collections.min(values), max = Collections.max(values);
                    if (!mode.equals("POSITION")) return current.compareTo(mode.equals("MIN") ? min : max) == 0;
                    if (min.compareTo(max) == 0) { evidence("FLAT_WINDOW", name, n, at); return null; }
                    BigDecimal dist = current.subtract(min).multiply(BigDecimal.valueOf(3)), range = max.subtract(min);
                    return dist.compareTo(range) <= 0 ? "低" : dist.compareTo(range.multiply(BigDecimal.valueOf(2))) >= 0 ? "高" : "中";
                }
                case PAIR_WINDOW -> {
                    String a = arg(call, 2), b = arg(call, 3), mode = definition.lowering().parameters().get("mode");
                    boolean close = mode.equals("CLOSE_TOGETHER");
                    boolean enough = complete(close ? 1 : 2, at, a + " / " + b);
                    BigDecimal x = raw(a, at, false), y = raw(b, at, false), px = null, py = null;
                    if (!close && at > 0) { px = raw(a, at - 1, false); py = raw(b, at - 1, false); }
                    if (!enough || x == null || y == null || (!close && (px == null || py == null))) return null;
                    if (!close) return mode.equals("CROSS_ABOVE") ? x.compareTo(y) > 0 && px.compareTo(py) <= 0 : x.compareTo(y) < 0 && px.compareTo(py) >= 0;
                    BigDecimal denominator = x.abs().max(y.abs());
                    if (denominator.signum() == 0) { cause("ZERO_DENOMINATOR", a + " / " + b, 1, 1, rows.get(at).date()); return null; }
                    return x.subtract(y).abs().compareTo(denominator.multiply(new BigDecimal(definition.lowering().parameters().get("threshold")))) <= 0;
                }
                default -> throw new Partial("DETAIL_NOT_SUPPORTED");
            }
        }
        void evidence(String code, String name, int n, int at) {
            for (int j = Math.max(0, at - n + 1); j <= at; j++) cause(code, name, n, Math.min(n, at + 1), rows.get(j).date());
        }
        Object eval(StockSlotAst.Expr expr, int at) {
            if (--work < 0) throw new Partial("DETAIL_WORK_LIMIT");
            if (expr instanceof StockSlotAst.Literal l) return l.value();
            if (expr instanceof StockSlotAst.FunctionCall f) return call(f, at);
            if (expr instanceof StockSlotAst.Unary u) {
                Object value = eval(u.operand(), at);
                if (value == null) return null;
                return switch (u.operator()) { case "NOT" -> !(Boolean) value; case "-" -> ((BigDecimal) value).negate(); case "+" -> value; default -> throw new Partial("DETAIL_NOT_SUPPORTED"); };
            }
            var b = (StockSlotAst.Binary) expr;
            Object x = eval(b.left(), at), y = eval(b.right(), at);
            if (b.operator().equals("AND")) return Boolean.FALSE.equals(x) || Boolean.FALSE.equals(y) ? false : x == null || y == null ? null : true;
            if (b.operator().equals("OR")) return Boolean.TRUE.equals(x) || Boolean.TRUE.equals(y) ? true : x == null || y == null ? null : false;
            if (x == null || y == null) return null;
            if (b.operator().matches("[+*/-]")) {
                BigDecimal a = (BigDecimal) x, c = (BigDecimal) y;
                return switch (b.operator()) {
                    case "+" -> a.add(c); case "-" -> a.subtract(c); case "*" -> a.multiply(c);
                    default -> { if (c.signum() == 0) { cause("ZERO_DENOMINATOR", "算术表达式", 1, 1, rows.get(at).date()); yield null; } yield a.divide(c, MC); }
                };
            }
            int comparison = x instanceof BigDecimal a && y instanceof BigDecimal c ? a.compareTo(c) : x.toString().compareTo(y.toString());
            return switch (b.operator()) {
                case "=" , "==" -> comparison == 0; case "!=" , "<>" -> comparison != 0;
                case ">" -> comparison > 0; case ">=" -> comparison >= 0; case "<" -> comparison < 0; case "<=" -> comparison <= 0;
                default -> throw new Partial("DETAIL_NOT_SUPPORTED");
            };
        }
    }
}
