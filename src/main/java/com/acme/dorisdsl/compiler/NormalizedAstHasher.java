package com.acme.dorisdsl.compiler;

import com.acme.dorisdsl.ast.Ast;
import com.acme.dorisdsl.registry.Registry;
import com.acme.dorisdsl.registry.RegistryConfig;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

final class NormalizedAstHasher {
    private final Registry registry;

    NormalizedAstHasher(Registry registry) {
        this.registry = registry;
    }

    String hash(Ast.Query query) {
        String normalized = "QUERY|date:?|adjust:" + query.adjustment() + "|where:" + expression(query.where(), false)
                + "|order:" + (query.orderBy() == null ? "-" : expression(query.orderBy().expression(), false)
                + ":" + query.orderBy().direction()) + "|limit:" + query.limit();
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(normalized.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }

    private String expression(Ast.Expr expression, boolean structuralLiteral) {
        if (expression == null) return "-";
        return switch (expression) {
            case Ast.Literal literal -> structuralLiteral ? "L:" + literalValue(literal) : "L:" + literal.type() + ":?";
            case Ast.Identifier identifier -> "I:" + identifier.name() + ":" + identifier.type();
            case Ast.FunctionCall call -> {
                RegistryConfig.FunctionDefinition definition = registry.function(
                        call.name(), call.span().line(), call.span().column());
                StringBuilder value = new StringBuilder("F:").append(call.name()).append('(');
                for (int index = 0; index < call.arguments().size(); index++) {
                    if (index > 0) value.append(',');
                    boolean structural = definition.loweringKind() == RegistryConfig.LoweringKind.WINDOW_AVG
                            && definition.lookbackArg() != null && definition.lookbackArg() == index;
                    value.append(expression(call.arguments().get(index), structural));
                }
                yield value.append(')').toString();
            }
            case Ast.Binary binary -> "B:" + binary.operator() + '(' + expression(binary.left(), false) + ','
                    + expression(binary.right(), false) + ')';
            case Ast.Unary unary -> "U:" + unary.operator() + '(' + expression(unary.operand(), false) + ')';
            case Ast.Between between -> "BETWEEN(" + expression(between.value(), false) + ','
                    + expression(between.lower(), false) + ',' + expression(between.upper(), false) + ')';
            case Ast.InList in -> "IN(" + expression(in.value(), false) + ",count:" + in.options().size() + ')';
        };
    }

    private String literalValue(Ast.Literal literal) {
        if (literal.value() instanceof BigDecimal number) return number.stripTrailingZeros().toPlainString();
        return String.valueOf(literal.value());
    }
}
