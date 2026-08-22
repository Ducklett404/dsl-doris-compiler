package com.acme.dorisdsl.registry;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

public final class PluginVerifier {
    private PluginVerifier() {}

    public static void verify(JsonNode source, ObjectMapper mapper) {
        String id = requiredText(source, "id");
        String version = requiredText(source, "version");
        String signature = requiredText(source, "signature");
        String minimum = requiredText(source, "minCompilerVersion");
        String maximum = requiredText(source, "maxCompilerVersion");
        parseVersion(version, "plugin version");
        if (compare(DslCompiler.VERSION, minimum) < 0 || compare(DslCompiler.VERSION, maximum) > 0) {
            throw new CompileException("PLUGIN_VERSION_INCOMPATIBLE",
                    "Plugin " + id + " requires compiler " + minimum + ".." + maximum
                            + ", current version is " + DslCompiler.VERSION, 1, 1);
        }
        String expected = signature(source, mapper);
        if (!MessageDigest.isEqual(expected.getBytes(StandardCharsets.US_ASCII),
                signature.getBytes(StandardCharsets.US_ASCII))) {
            throw new CompileException("PLUGIN_SIGNATURE_INVALID", "Invalid signature for plugin " + id, 1, 1);
        }
    }

    public static String signature(JsonNode source, ObjectMapper mapper) {
        if (!(source instanceof ObjectNode object))
            throw new CompileException("PLUGIN_INVALID", "Plugin root must be a JSON object", 1, 1);
        ObjectNode unsigned = object.deepCopy();
        unsigned.remove("signature");
        try {
            byte[] canonical = mapper.writer().without(SerializationFeature.INDENT_OUTPUT).writeValueAsBytes(unsigned);
            return "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        } catch (Exception e) {
            throw new CompileException("PLUGIN_INVALID", "Cannot canonicalize plugin: " + e.getMessage(), 1, 1);
        }
    }

    private static String requiredText(JsonNode source, String field) {
        JsonNode value = source.get(field);
        if (value == null || !value.isTextual() || value.textValue().isBlank())
            throw new CompileException("PLUGIN_METADATA_REQUIRED", "Plugin field " + field + " is required", 1, 1);
        return value.textValue();
    }

    private static int compare(String left, String right) {
        int[] a = parseVersion(left, "compiler version");
        int[] b = parseVersion(right, "compiler version");
        for (int i = 0; i < 3; i++) {
            int compared = Integer.compare(a[i], b[i]);
            if (compared != 0) return compared;
        }
        return 0;
    }

    private static int[] parseVersion(String value, String owner) {
        if (value == null || !value.matches("\\d+\\.\\d+\\.\\d+"))
            throw new CompileException("PLUGIN_VERSION_INVALID", owner + " must use major.minor.patch", 1, 1);
        String[] parts = value.split("\\.");
        return new int[]{Integer.parseInt(parts[0]), Integer.parseInt(parts[1]), Integer.parseInt(parts[2])};
    }
}
