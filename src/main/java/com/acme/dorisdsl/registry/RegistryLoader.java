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
            if (function.minArgs() < 0 || function.maxArgs() < function.minArgs())
                throw new CompileException("REGISTRY_INVALID", "Invalid arity for " + function.name(), 1, 1);
            if (function.loweringKind() == RegistryConfig.LoweringKind.TEMPLATE ||
                    function.loweringKind() == RegistryConfig.LoweringKind.COLUMN) {
                validateSqlFragment(function.sqlTemplate(), "function " + function.name());
            }
        }
    }

    private void validateSqlFragment(String sql, String owner) {
        if (sql == null || sql.isBlank()) throw new CompileException("REGISTRY_INVALID", "Missing SQL for " + owner, 1, 1);
        String lower = sql.toLowerCase();
        if (sql.contains(";") || sql.contains("--") || sql.contains("/*") || lower.contains(" select ") || lower.startsWith("select "))
            throw new CompileException("REGISTRY_UNSAFE", "Unsafe SQL fragment in " + owner, 1, 1);
    }
}
