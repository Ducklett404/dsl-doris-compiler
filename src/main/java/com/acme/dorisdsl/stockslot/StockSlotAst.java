package com.acme.dorisdsl.stockslot;

import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

public final class StockSlotAst {
    private StockSlotAst() {}

    public enum ValueType { UNKNOWN, BOOLEAN, NUMBER, PERCENT, STRING, NULL }

    public record SourceSpan(int line, int column, int endLine, int endColumn) {}

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "kind")
    @JsonSubTypes({
            @JsonSubTypes.Type(value = Literal.class, name = "Literal"),
            @JsonSubTypes.Type(value = FunctionCall.class, name = "FunctionCall"),
            @JsonSubTypes.Type(value = Binary.class, name = "Binary"),
            @JsonSubTypes.Type(value = Unary.class, name = "Unary")
    })
    public sealed interface Expr permits Literal, FunctionCall, Binary, Unary {
        ValueType type();
        SourceSpan span();
    }

    public record Literal(Object value, ValueType type, SourceSpan span) implements Expr {
        public static Literal number(BigDecimal value, SourceSpan span) {
            return new Literal(value, ValueType.NUMBER, span);
        }
    }

    public record FunctionCall(String name, List<Expr> arguments, ValueType type, SourceSpan span) implements Expr {
        public FunctionCall { arguments = List.copyOf(arguments); }
    }

    public record Binary(String operator, Expr left, Expr right, ValueType type, SourceSpan span) implements Expr {}
    public record Unary(String operator, Expr operand, ValueType type, SourceSpan span) implements Expr {}
    public record SelectionLimit(int minimum, int maximum, SourceSpan span) {}
    public record Document(Expr expression, SelectionLimit selectionLimit, SourceSpan span) {}

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "kind")
    @JsonSubTypes({
            @JsonSubTypes.Type(value = SetTerm.class, name = "SetTerm"),
            @JsonSubTypes.Type(value = SetBinary.class, name = "SetBinary"),
            @JsonSubTypes.Type(value = SetUnary.class, name = "SetUnary")
    })
    public sealed interface SetExpr permits SetTerm, SetBinary, SetUnary {}
    public record SetTerm(String value) implements SetExpr {}
    public record SetBinary(String operator, SetExpr left, SetExpr right) implements SetExpr {}
    public record SetUnary(String operator, SetExpr operand) implements SetExpr {}

    public record CountExpression(String mode, String operator, String count, String unit) {}
    public record TimeOffset(String direction, int amount, String unit) {}
    public record TimeExpression(String raw, String reportPeriod, List<TimeOffset> offsets) {
        public TimeExpression { offsets = List.copyOf(offsets); }
    }
    public record IndicatorInstantiation(String value, String template, Map<String, String> parameters) {
        public IndicatorInstantiation { parameters = Map.copyOf(parameters); }
    }
    public record SlotSemantics(String name, String rawValue, Object structuredValue) {}
    public record CallSemantics(String function, SourceSpan span, List<SlotSemantics> slots) {
        public CallSemantics { slots = List.copyOf(slots); }
    }
    public record SemanticModel(Document document, List<CallSemantics> calls) {
        public SemanticModel { calls = List.copyOf(calls); }
    }
}
