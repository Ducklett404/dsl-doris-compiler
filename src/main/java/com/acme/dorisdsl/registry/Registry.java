package com.acme.dorisdsl.registry;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.registry.RegistryConfig.FieldDefinition;
import com.acme.dorisdsl.registry.RegistryConfig.FunctionDefinition;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

public final class Registry {
    private final RegistryConfig.Datasets datasets;
    private final Map<String, FieldDefinition> fields;
    private final Map<String, FunctionDefinition> functions;

    Registry(RegistryConfig.Datasets datasets, Map<String, FieldDefinition> fields,
             Map<String, FunctionDefinition> functions) {
        this.datasets = datasets;
        this.fields = Map.copyOf(fields);
        this.functions = Map.copyOf(functions);
    }

    public RegistryConfig.Datasets datasets() { return datasets; }
    public Map<String, FieldDefinition> fields() { return fields; }
    public Map<String, FunctionDefinition> functions() { return functions; }

    public FieldDefinition field(String name, int line, int column) {
        var value = fields.get(name.toUpperCase(Locale.ROOT));
        if (value == null) throw new CompileException("UNKNOWN_FIELD", "Unknown or disallowed field: " + name, line, column);
        return value;
    }

    public FunctionDefinition function(String name, int line, int column) {
        var value = functions.get(name.toUpperCase(Locale.ROOT));
        if (value == null) throw new CompileException("UNKNOWN_FUNCTION", "Unknown or disallowed function: " + name, line, column);
        return value;
    }

    static Registry from(RegistryConfig base, Iterable<RegistryConfig> plugins) {
        Map<String, FieldDefinition> fields = new LinkedHashMap<>();
        Map<String, FunctionDefinition> functions = new LinkedHashMap<>();
        merge(base, fields, functions);
        for (var plugin : plugins) merge(plugin, fields, functions);
        return new Registry(base.datasets(), fields, functions);
    }

    private static void merge(RegistryConfig config, Map<String, FieldDefinition> fields,
                              Map<String, FunctionDefinition> functions) {
        for (var field : config.fields()) fields.put(field.name().toUpperCase(Locale.ROOT), field);
        for (var function : config.functions()) functions.put(function.name().toUpperCase(Locale.ROOT), function);
    }
}
