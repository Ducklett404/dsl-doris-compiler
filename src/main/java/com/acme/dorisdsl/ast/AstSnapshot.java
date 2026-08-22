package com.acme.dorisdsl.ast;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class AstSnapshot {
    public static final String SCHEMA_VERSION = "1.0.0";

    private AstSnapshot() {}

    public static Map<String, Object> from(Ast.Query query) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("schemaVersion", SCHEMA_VERSION);
        snapshot.put("kind", "Query");
        snapshot.put("asOf", query.asOf().toString());
        snapshot.put("context", query.context().values());
        snapshot.put("adjustment", query.adjustment().name());
        snapshot.put("where", expression(query.where()));
        snapshot.put("orderBy", query.orderBy() == null ? null : orderBy(query.orderBy()));
        snapshot.put("limit", query.limit());
        return snapshot;
    }

    private static Map<String, Object> orderBy(Ast.OrderBy orderBy) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("expression", expression(orderBy.expression()));
        value.put("direction", orderBy.direction().name());
        return value;
    }

    private static Object expression(Ast.Expr expr) {
        if (expr == null) return null;
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("kind", expr.getClass().getSimpleName());
        value.put("type", expr.type().name());
        switch (expr) {
            case Ast.Literal literal -> value.put("value", literal.value());
            case Ast.Identifier identifier -> value.put("name", identifier.name());
            case Ast.FunctionCall call -> {
                value.put("name", call.name());
                value.put("arguments", call.arguments().stream().map(AstSnapshot::expression).toList());
            }
            case Ast.Binary binary -> {
                value.put("operator", binary.operator());
                value.put("left", expression(binary.left()));
                value.put("right", expression(binary.right()));
            }
            case Ast.Unary unary -> {
                value.put("operator", unary.operator());
                value.put("operand", expression(unary.operand()));
            }
            case Ast.Between between -> {
                value.put("value", expression(between.value()));
                value.put("lower", expression(between.lower()));
                value.put("upper", expression(between.upper()));
            }
            case Ast.InList in -> {
                value.put("value", expression(in.value()));
                value.put("options", in.options().stream().map(AstSnapshot::expression).toList());
            }
            case Ast.IsNull isNull -> {
                value.put("value", expression(isNull.value()));
                value.put("negated", isNull.negated());
            }
            case Ast.NamedArgument named -> {
                value.put("name", named.name());
                value.put("value", expression(named.value()));
            }
        }
        return value;
    }
}
