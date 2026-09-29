package com.acme.dorisdsl.competition;

import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;

import java.util.List;

/** Syntax-only AST for the organizer's slot DSL. No expression here is executable SQL. */
public final class SlotAst {
    private SlotAst() {}

    public record Span(int line, int column, int endLine, int endColumn) {}
    public record Query(Expr filter, ResultBounds resultBounds, Span span) {}

    /** Organizer-defined count bounds, not SQL OFFSET/LIMIT. Negative sentinel meaning is unresolved. */
    public record ResultBounds(int minimum, int maximum, Span span) {}

    public enum LiteralKind { NUMBER, PERCENT, STRING, BOOLEAN }

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "kind")
    @JsonSubTypes({
            @JsonSubTypes.Type(value = Call.class, name = "Call"),
            @JsonSubTypes.Type(value = Literal.class, name = "Literal"),
            @JsonSubTypes.Type(value = Binary.class, name = "Binary"),
            @JsonSubTypes.Type(value = Unary.class, name = "Unary"),
            @JsonSubTypes.Type(value = Comparison.class, name = "Comparison"),
            @JsonSubTypes.Type(value = Interval.class, name = "Interval"),
            @JsonSubTypes.Type(value = Then.class, name = "Then")
    })
    public sealed interface Expr permits Call, Literal, Binary, Unary, Comparison, Interval, Then {
        Span span();
    }

    /** A lexical token stream only; no precedence or market-set meaning is assumed yet. */
    public enum SetTokenKind { ATOM, PIPE, AMPERSAND, CARET, LPAREN, RPAREN }
    public record SetToken(SetTokenKind kind, String text, int startOffset, int endOffset) {}

    /** raw retains exact quoting; value decodes doubled apostrophes only. */
    public record Slot(String raw, String value, List<SetToken> setTokens, Span span) {
        public Slot { setTokens = List.copyOf(setTokens); }
    }

    public record Call(String function, List<Slot> slots, Span span) implements Expr {
        public Call { slots = List.copyOf(slots); }
    }
    public record Literal(String raw, String value, LiteralKind literalKind, Span span) implements Expr {}
    public record Binary(String operator, Expr left, Expr right, Span span) implements Expr {}
    public record Unary(String operator, Expr operand, Span span) implements Expr {}
    public record Comparison(String operator, Expr left, Expr right, Span span) implements Expr {}
    /** The interval string is preserved until endpoint and unit semantics are confirmed. */
    public record Interval(Expr value, Slot bounds, Span span) implements Expr {}
    /** Explicit candidate-set boundary; never rewritten to ordinary AND. */
    public record Then(Expr candidateFilter, Expr rankingStage, Span span) implements Expr {}
}
