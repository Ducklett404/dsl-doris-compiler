package com.acme.dorisdsl.rewrite;

import com.acme.dorisdsl.compiler.CompileException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;

public final class RuleCatalogLoader {
    private final ObjectMapper mapper = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);

    public RuleCatalogManager loadDefault(String compilerVersion) {
        try (InputStream input = RuleCatalogLoader.class.getResourceAsStream("/rewrite-rules.json")) {
            if (input == null) throw invalid("Missing /rewrite-rules.json");
            return load(input, compilerVersion);
        } catch (IOException e) {
            throw invalid("Cannot read default rules: " + e.getMessage());
        }
    }

    public RuleCatalogManager load(Path path, String compilerVersion) {
        try (InputStream input = Files.newInputStream(path)) {
            return load(input, compilerVersion);
        } catch (IOException e) {
            throw invalid("Cannot read rules: " + e.getMessage());
        }
    }

    private RuleCatalogManager load(InputStream input, String compilerVersion) throws IOException {
        RuleCatalog catalog = mapper.readValue(input, RuleCatalog.class);
        validate(catalog);
        return new RuleCatalogManager(catalog, compilerVersion);
    }

    private void validate(RuleCatalog catalog) {
        if (catalog.schemaVersion() != 1) throw invalid("Unsupported rule schemaVersion: " + catalog.schemaVersion());
        if (blank(catalog.activeVersion())) throw invalid("activeVersion is required");
        if (catalog.versions().isEmpty()) throw invalid("At least one rule version is required");
        Set<String> versions = new HashSet<>();
        for (var set : catalog.versions()) {
            if (blank(set.version()) || !versions.add(set.version())) throw invalid("Duplicate or blank rule version: " + set.version());
            if (set.maxIterations() < 1 || set.maxIterations() > 1000)
                throw invalid("maxIterations must be between 1 and 1000 for " + set.version());
            if (set.conflictPolicy() == null) throw invalid("conflictPolicy is required for " + set.version());
            Set<String> ids = new HashSet<>();
            for (var rule : set.rules()) validate(rule, ids);
        }
        if (!versions.contains(catalog.activeVersion())) throw invalid("Unknown activeVersion: " + catalog.activeVersion());
    }

    private void validate(RuleCatalog.RuleDefinition rule, Set<String> ids) {
        if (blank(rule.id()) || !rule.id().matches("[A-Z][A-Z0-9_-]{1,63}") || !ids.add(rule.id()))
            throw invalid("Invalid or duplicate rule id: " + rule.id());
        if (rule.phase() == null || rule.matchNodeType() == null || rule.outputNodeType() == null || rule.action() == null)
            throw invalid("Missing phase, node type or action for " + rule.id());
        if (blank(rule.conflictGroup()) || blank(rule.equivalence()) || blank(rule.description()))
            throw invalid("Rule requires conflictGroup, equivalence and description: " + rule.id());
        if (rule.priority() < -1_000_000 || rule.priority() > 1_000_000)
            throw invalid("Priority out of range for " + rule.id());
        var when = rule.when() == null ? new RuleCatalog.RuleCondition(null, null, null, null) : rule.when();
        for (String operator : when.operators())
            if (!Set.of("+", "-", "*", "/").contains(operator)) throw invalid("Unknown operator in " + rule.id());
        switch (rule.action()) {
            case FOLD_NUMERIC_BINARY -> {
                if (rule.matchNodeType() != RuleCatalog.NodeType.BINARY || rule.outputNodeType() != RuleCatalog.NodeType.LITERAL
                        || !Boolean.TRUE.equals(when.numericLiteralOperands()))
                    throw invalid("FOLD_NUMERIC_BINARY requires BINARY -> LITERAL and numericLiteralOperands: " + rule.id());
            }
            case SWAP_COMMUTATIVE_OPERANDS -> {
                if (rule.matchNodeType() != RuleCatalog.NodeType.BINARY || rule.outputNodeType() != RuleCatalog.NodeType.BINARY
                        || !Boolean.TRUE.equals(when.commutativeOnly()))
                    throw invalid("SWAP_COMMUTATIVE_OPERANDS requires BINARY -> BINARY and commutativeOnly: " + rule.id());
            }
        }
    }

    private static boolean blank(String value) { return value == null || value.isBlank(); }
    private static CompileException invalid(String message) {
        return new CompileException("RULE_CONFIG_INVALID", message, 1, 1);
    }
}
