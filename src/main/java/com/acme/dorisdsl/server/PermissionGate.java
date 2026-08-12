package com.acme.dorisdsl.server;

import com.acme.dorisdsl.compiler.CompileException;

import java.util.Collection;
import java.util.Map;

public final class PermissionGate implements CompileAuthorizer {
    public static final String COMPILE_PERMISSION = "COMPILE_DSL";

    @Override
    public void authorize(Map<String, Object> context, String dsl) throws CompileException {
        if (!(context.get("userId") instanceof String userId) || userId.isBlank()) {
            throw new CompileException("AUTH_REQUIRED", "A non-empty context.userId is required", 1, 1);
        }
        Object value = context.get("permissions");
        if (!(value instanceof Collection<?> permissions) || !permissions.contains(COMPILE_PERMISSION)) {
            throw new CompileException("AUTH_FORBIDDEN", "Permission COMPILE_DSL is required", 1, 1);
        }
    }
}
