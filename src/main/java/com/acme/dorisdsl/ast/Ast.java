package com.acme.dorisdsl.ast;

import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

public final class Ast {
    private Ast() {}

    public enum DataType {
        UNKNOWN, BOOLEAN, NUMBER, PRICE, RATIO, PERCENT, VOLUME, STRING, TRADE_DATE, SECURITY_ID, NULL
    }

    public enum Adjustment { FORWARD, BACKWARD, NONE }
    public enum Direction { ASC, DESC }

    public record SourceSpan(int line, int column, int endLine, int endColumn) {}

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "kind")
    @JsonSubTypes({
            @JsonSubTypes.Type(value = Literal.class, name = "Literal"),
            @JsonSubTypes.Type(value = Identifier.class, name = "Identifier"),
            @JsonSubTypes.Type(value = FunctionCall.class, name = "FunctionCall"),
            @JsonSubTypes.Type(value = Binary.class, name = "Binary"),
            @JsonSubTypes.Type(value = Unary.class, name = "Unary"),
            @JsonSubTypes.Type(value = Between.class, name = "Between"),
            @JsonSubTypes.Type(value = InList.class, name = "InList")
    })
    public sealed interface Expr permits Literal, Identifier, FunctionCall, Binary, Unary, Between, InList {
        DataType type();
        SourceSpan span();
    }

    public record Literal(Object value, DataType type, SourceSpan span) implements Expr {
        public static Literal number(BigDecimal value, SourceSpan span) {
            return new Literal(value, DataType.NUMBER, span);
        }
    }

    public record Identifier(String name, DataType type, SourceSpan span) implements Expr {}
    public record FunctionCall(String name, List<Expr> arguments, DataType type, SourceSpan span) implements Expr {
        public FunctionCall {
            arguments = List.copyOf(arguments);
        }
    }
    public record Binary(String operator, Expr left, Expr right, DataType type, SourceSpan span) implements Expr {}
    public record Unary(String operator, Expr operand, DataType type, SourceSpan span) implements Expr {}
    public record Between(Expr value, Expr lower, Expr upper, DataType type, SourceSpan span) implements Expr {}
    public record InList(Expr value, List<Expr> options, DataType type, SourceSpan span) implements Expr {
        public InList { options = List.copyOf(options); }
    }

    public record OrderBy(Expr expression, Direction direction) {}
    public record Query(LocalDate asOf, Expr where, Adjustment adjustment, OrderBy orderBy, int limit, SourceSpan span) {}
}
