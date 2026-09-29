package com.acme.dorisdsl.rewrite;

import java.util.List;

/** Strict, data-only declaration of the supported rewrite rules. */
public record RuleCatalog(int schemaVersion, String activeVersion, List<RuleSet> versions) {
    public RuleCatalog { versions = versions == null ? List.of() : List.copyOf(versions); }

    public record RuleSet(String version, String minCompilerVersion, String maxCompilerVersionExclusive,
                          int maxIterations, ConflictPolicy conflictPolicy, List<RuleDefinition> rules) {
        public RuleSet { rules = rules == null ? List.of() : List.copyOf(rules); }
    }

    public record RuleDefinition(String id, boolean enabled, Phase phase, int priority,
                                 NodeType matchNodeType, NodeType outputNodeType,
                                 String conflictGroup, RuleCondition when, Action action,
                                 String equivalence, String description) {}

    public record RuleCondition(List<String> operators, Boolean numericLiteralOperands,
                                Boolean nonZeroRightOperand, Boolean commutativeOnly) {
        public RuleCondition { operators = operators == null ? List.of() : List.copyOf(operators); }
    }

    public enum Phase { NORMALIZE, SIMPLIFY, CANONICALIZE }
    public enum ConflictPolicy { HIGHEST_PRIORITY, ERROR }
    public enum NodeType { LITERAL, IDENTIFIER, FUNCTION_CALL, BINARY, UNARY, BETWEEN, IN_LIST, IS_NULL, NAMED_ARGUMENT }
    public enum Action { FOLD_NUMERIC_BINARY, SWAP_COMMUTATIVE_OPERANDS }
}
