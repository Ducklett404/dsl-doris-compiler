package com.acme.dorisdsl.server;

import com.acme.dorisdsl.compiler.CompileException;
import com.sun.net.httpserver.HttpExchange;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;

/** Server-configured credentials and permissions; identity never comes from request JSON. */
public final class BearerTokenAccess implements RequestAuthenticator, PermissionService {
    private static final String USER_ID = "http-client";
    private final byte[] token;
    private final Set<String> permissions;
    public BearerTokenAccess(String token, Set<String> permissions) {
        if (token == null || token.length() < 32 || token.length() > 4096 || !token.matches("[A-Za-z0-9._~+/-]+={0,2}"))
            throw new IllegalArgumentException("HTTP token must contain 32..4096 printable token characters");
        this.token = token.getBytes(StandardCharsets.UTF_8);
        this.permissions = Set.copyOf(permissions);
    }
    public static BearerTokenAccess fromEnvironment(String variable, boolean execution) {
        if (variable == null || !variable.matches("[A-Za-z_][A-Za-z0-9_]*"))
            throw new IllegalArgumentException("Invalid HTTP token environment variable name");
        String value = System.getenv(variable);
        if (value == null || value.isBlank())
            throw new IllegalArgumentException("Set HTTP authentication environment variable: " + variable);
        return new BearerTokenAccess(value, execution ? Set.of(PermissionGate.COMPILE_PERMISSION, PermissionGate.EXECUTE_PERMISSION)
                : Set.of(PermissionGate.COMPILE_PERMISSION));
    }
    @Override public AuthenticatedIdentity authenticate(HttpExchange exchange) {
        var values = exchange.getRequestHeaders().get("Authorization");
        if (values == null || values.size() != 1) throw required();
        String header = values.getFirst();
        if (!header.startsWith("Bearer ") || header.length() > 4103
                || !MessageDigest.isEqual(token, header.substring(7).getBytes(StandardCharsets.UTF_8))) throw required();
        return new AuthenticatedIdentity(USER_ID);
    }
    @Override public boolean hasPermission(String userId, String permission) {
        return USER_ID.equals(userId) && permissions.contains(permission);
    }
    private static CompileException required() {
        return new CompileException("AUTH_REQUIRED", "Valid bearer credentials are required", 1, 1);
    }
}
