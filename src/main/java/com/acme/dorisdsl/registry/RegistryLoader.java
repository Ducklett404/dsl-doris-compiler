package com.acme.dorisdsl.registry;

import com.acme.dorisdsl.compiler.CompileException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

public final class RegistryLoader {
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);

    public Registry loadDefault(List<Path> plugins) {
        try (InputStream input = RegistryLoader.class.getResourceAsStream("/registry.json")) {
            if (input == null) throw new IllegalStateException("Missing /registry.json");
            return load(input, plugins);
        } catch (IOException e) {
            throw new CompileException("REGISTRY_IO", e.getMessage(), 1, 1);
        }
    }

    public Registry load(Path base, List<Path> plugins) {
        try (InputStream input = Files.newInputStream(base)) {
            return load(input, plugins);
        } catch (IOException e) {
            throw new CompileException("REGISTRY_IO", "Cannot read registry: " + e.getMessage(), 1, 1);
        }
    }

    private Registry load(InputStream baseInput, List<Path> pluginPaths) throws IOException {
        RegistryConfig base = mapper.readValue(baseInput, RegistryConfig.class);
        List<RegistryConfig> plugins = new ArrayList<>();
        for (Path path : pluginPaths) {
            try (InputStream input = Files.newInputStream(path)) {
                plugins.add(mapper.readValue(input, RegistryConfig.class));
            }
        }
        validate(base, true);
        plugins.forEach(plugin -> validate(plugin, false));
        return Registry.from(base, plugins);
    }

    private void validate(RegistryConfig config, boolean requireDatasets) {
        if (requireDatasets && config.datasets() == null)
            throw new CompileException("REGISTRY_INVALID", "Base registry requires datasets", 1, 1);
        for (var field : config.fields()) validateSqlFragment(field.sourceSql(), "field " + field.name());
        for (var function : config.functions()) {
            validatePluginContract(function);
            if (function.minArgs() < 0 || function.maxArgs() < function.minArgs())
                throw new CompileException("REGISTRY_INVALID", "Invalid arity for " + function.name(), 1, 1);
            if (function.loweringKind() == RegistryConfig.LoweringKind.TEMPLATE ||
                    function.loweringKind() == RegistryConfig.LoweringKind.COLUMN) {
                validateSqlFragment(function.sqlTemplate(), "function " + function.name());
            }
            if (function.sqlTemplate() != null && function.sqlTemplate().contains("f."))
                validateFinancialMetadata(function);
        }
    }

    private void validatePluginContract(RegistryConfig.FunctionDefinition function) {
        if (isBlank(function.name())) throw new CompileException("REGISTRY_INVALID", "Function requires name", 1, 1);
        if (function.id() != null && !function.id().matches("[a-zA-Z0-9_.-]+"))
            throw new CompileException("REGISTRY_INVALID", "Invalid function id: " + function.id(), 1, 1);
        if (function.version() != null && function.version().isBlank())
            throw new CompileException("REGISTRY_INVALID", "Invalid version for " + function.name(), 1, 1);
        if (function.signature() != null) {
            if (function.returnType() != null && function.returnType() != function.signature().returnType())
                throw new CompileException("REGISTRY_INVALID", "returnType must match signature for " + function.name(), 1, 1);
            if (function.signature().arguments().isEmpty())
                throw new CompileException("REGISTRY_INVALID", "Signature requires arguments for " + function.name(), 1, 1);
            for (var argument : function.signature().arguments()) {
                if (isBlank(argument.name()) || argument.type() == null)
                    throw new CompileException("REGISTRY_INVALID", "Invalid signature argument for " + function.name(), 1, 1);
            }
        }
        if (function.loweringKind() == null)
            throw new CompileException("REGISTRY_INVALID", "Function requires loweringKind: " + function.name(), 1, 1);
        if (function.loweringKind() == RegistryConfig.LoweringKind.TEMPLATE && function.irBuilder() != null)
            throw new CompileException("REGISTRY_INVALID", "TEMPLATE function cannot also declare irBuilder: " + function.name(), 1, 1);
        if (function.loweringKind() == RegistryConfig.LoweringKind.WINDOW_STDDEV) {
            if (!"WindowStddevBuilder".equals(function.irBuilder()))
                throw new CompileException("REGISTRY_INVALID", "WINDOW_STDDEV requires controlled irBuilder WindowStddevBuilder: " + function.name(), 1, 1);
            if (function.windowSpec() == null)
                throw new CompileException("REGISTRY_INVALID", "WINDOW_STDDEV requires windowSpec: " + function.name(), 1, 1);
            validateWindowSpec(function);
        }
        if (function.nullPolicy() == null && function.windowSpec() != null)
            throw new CompileException("REGISTRY_INVALID", "Window function requires nullPolicy: " + function.name(), 1, 1);
    }

    private void validateWindowSpec(RegistryConfig.FunctionDefinition function) {
        var spec = function.windowSpec();
        if (spec.lengthArg() < 0 || spec.lengthArg() >= function.maxArgs())
            throw new CompileException("REGISTRY_INVALID", "windowSpec lengthArg out of range for " + function.name(), 1, 1);
        if (!"TRADING_DAY".equals(spec.unit()))
            throw new CompileException("REGISTRY_INVALID", "Only TRADING_DAY window unit is supported for " + function.name(), 1, 1);
        for (String key : spec.partitionKeys()) validateIdentifier(key, "window partition key for " + function.name());
        for (String key : spec.orderKeys()) validateIdentifier(key, "window order key for " + function.name());
    }

    private void validateFinancialMetadata(RegistryConfig.FunctionDefinition function) {
        var metadata = function.financialMetadata();
        if (metadata == null)
            throw new CompileException("REGISTRY_INVALID", "Financial function requires PIT metadata: " + function.name(), 1, 1);
        if (isBlank(metadata.visibleFromColumn()) || isBlank(metadata.visibleToColumn()) || isBlank(metadata.reportPeriodColumn()))
            throw new CompileException("REGISTRY_INVALID", "Incomplete PIT metadata for " + function.name(), 1, 1);
        validateIdentifier(metadata.visibleFromColumn(), "visibleFromColumn for " + function.name());
        validateIdentifier(metadata.visibleToColumn(), "visibleToColumn for " + function.name());
        validateIdentifier(metadata.reportPeriodColumn(), "reportPeriodColumn for " + function.name());
    }

    private void validateSqlFragment(String sql, String owner) {
        if (sql == null || sql.isBlank()) throw new CompileException("REGISTRY_INVALID", "Missing SQL for " + owner, 1, 1);
        String lower = sql.toLowerCase();
        if (sql.contains(";") || sql.contains("--") || sql.contains("/*") || lower.contains(" select ")
                || lower.startsWith("select ") || lower.contains("(select")
                || sql.contains("$") || sql.contains("`"))
            throw new CompileException("REGISTRY_UNSAFE", "Unsafe SQL fragment in " + owner, 1, 1);
    }

    private void validateIdentifier(String value, String owner) {
        if (!value.matches("[a-zA-Z_][a-zA-Z0-9_]*"))
            throw new CompileException("REGISTRY_UNSAFE", "Unsafe identifier in " + owner, 1, 1);
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
