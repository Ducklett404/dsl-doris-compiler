package com.acme.dorisdsl.server;

import com.acme.dorisdsl.compiler.CompileException;

import java.util.Objects;

public final class PermissionGate {
    public static final String COMPILE_PERMISSION = "COMPILE_DSL";
    public static final String EXECUTE_PERMISSION = "EXECUTE_DSL";
    private final PermissionService permissionService;

    public PermissionGate(PermissionService permissionService) {
        this.permissionService = Objects.requireNonNull(permissionService, "permissionService");
    }

    public void authorize(AuthenticatedIdentity identity) throws CompileException {
        authorize(identity, COMPILE_PERMISSION);
    }

    public void authorize(AuthenticatedIdentity identity, String permission) {
        if (identity == null) throw new CompileException("AUTH_REQUIRED", "Authentication is required", 1, 1);
        if (!permissionService.hasPermission(identity.userId(), permission)) {
            throw new CompileException("AUTH_FORBIDDEN", "Permission " + permission + " is required", 1, 1);
        }
    }
}
