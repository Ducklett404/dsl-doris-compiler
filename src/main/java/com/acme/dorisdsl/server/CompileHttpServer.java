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
        server = HttpServer.create(new InetSocketAddress(host, port), 32);
        server.createContext("/health", exchange -> respond(exchange, 200, Map.of("status", "ok")));
        server.createContext("/compile", exchange -> compile(exchange, compiler));
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
    }

    public void start() { server.start(); }
    public int port() { return server.getAddress().getPort(); }

    private void compile(HttpExchange exchange, DslCompiler compiler) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, Map.of("error", "method_not_allowed"));
            return;
        }
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> input = JsonSupport.MAPPER.readValue(exchange.getRequestBody(), Map.class);
            Object dsl = input.get("dsl");
            if (!(dsl instanceof String source)) throw new CompileException("MISSING_DSL", "JSON field 'dsl' is required", 1, 1);
            respond(exchange, 200, compiler.compile(source));
        } catch (CompileException e) {
            respond(exchange, 400, Map.of("error", e.code(), "message", e.getMessage(), "line", e.line(), "column", e.column()));
        } catch (Exception e) {
            respond(exchange, 500, Map.of("error", "internal_error", "message", e.getMessage()));
        }
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
