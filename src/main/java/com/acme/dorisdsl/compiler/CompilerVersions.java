package com.acme.dorisdsl.compiler;

public record CompilerVersions(
        String ruleSetVersion,
        String catalogVersion,
        String dorisCapabilityVersion
) {
    public CompilerVersions {
        requireVersion(ruleSetVersion, "ruleSetVersion");
        requireVersion(catalogVersion, "catalogVersion");
        requireVersion(dorisCapabilityVersion, "dorisCapabilityVersion");
    }

    private static void requireVersion(String value, String name) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException(name + " is required");
    }
}
