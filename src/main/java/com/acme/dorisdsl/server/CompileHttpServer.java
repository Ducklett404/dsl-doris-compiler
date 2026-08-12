package com.acme.dorisdsl.server;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.util.JsonSupport;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.Executors;

public final class CompileHttpServer implements AutoCloseable {
    private final HttpServer server;

    public CompileHttpServer(DslCompiler compiler, String host, int port) throws IOException {
        this(compiler, host, port, new PermissionGate());
    }

    public CompileHttpServer(DslCompiler compiler, String host, int port, CompileAuthorizer authorizer) throws IOException {
        server = HttpServer.create(new InetSocketAddress(host, port), 32);
        server.createContext("/health", exchange -> respond(exchange, 200, Map.of("status", "ok")));
        server.createContext("/compile", exchange -> compile(exchange, compiler, authorizer));
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
    }

    public void start() { server.start(); }
    public int port() { return server.getAddress().getPort(); }

    private void compile(HttpExchange exchange, DslCompiler compiler, CompileAuthorizer authorizer) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, Map.of("error", "method_not_allowed"));
            return;
        }
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> input = JsonSupport.MAPPER.readValue(exchange.getRequestBody(), Map.class);
            Object dsl = input.get("dsl");
            if (!(dsl instanceof String source)) throw new CompileException("MISSING_DSL", "JSON field 'dsl' is required", 1, 1);
            Map<String, Object> context = requestContext(input.get("context"));
            authorizer.authorize(context, source);
            respond(exchange, 200, compiler.compile(source));
        } catch (CompileException e) {
            respond(exchange, statusFor(e), Map.of("error", e.code(), "message", e.getMessage(), "line", e.line(), "column", e.column()));
        } catch (Exception e) {
            respond(exchange, 500, Map.of("error", "internal_error", "message", e.getMessage()));
        }
    }

    private int statusFor(CompileException exception) {
        return switch (exception.code()) {
            case "AUTH_REQUIRED" -> 401;
            case "AUTH_FORBIDDEN" -> 403;
            case "SCAN_LIMIT_EXCEEDED", "COST_LIMIT_EXCEEDED" -> 422;
            default -> 400;
        };
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> requestContext(Object value) {
        if (value == null) return Map.of();
        if (!(value instanceof Map<?, ?> map))
            throw new CompileException("INVALID_CONTEXT", "JSON field 'context' must be an object", 1, 1);
        return Map.copyOf((Map<String, Object>) map);
    }

    private static void respond(HttpExchange exchange, int status, Object body) throws IOException {
        byte[] bytes = JsonSupport.MAPPER.writeValueAsBytes(body);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) { output.write(bytes); }
    }

    @Override public void close() { server.stop(0); }
}
