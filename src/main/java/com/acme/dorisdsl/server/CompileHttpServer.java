package com.acme.dorisdsl.server;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.stockslot.DorisExecutionException;
import com.acme.dorisdsl.stockslot.DorisExecutionMarkdownRenderer;
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
        this(compiler, null, host, port);
    }

    public CompileHttpServer(DslCompiler compiler, DorisExecutionEndpoint execution, String host, int port) throws IOException {
        server = HttpServer.create(new InetSocketAddress(host, port), 32);
        server.createContext("/health", exchange -> respond(exchange, 200, Map.of("status", "ok")));
        server.createContext("/compile", exchange -> compile(exchange, compiler));
        if (execution != null) server.createContext("/execute", exchange -> execute(exchange, execution));
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
    }

    private void execute(HttpExchange exchange, DorisExecutionEndpoint execution) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, Map.of("error", "method_not_allowed"));
            return;
        }
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> input = JsonSupport.MAPPER.readValue(exchange.getRequestBody(), Map.class);
            Object dsl = input.get("dsl");
            if (!(dsl instanceof String source))
                throw new CompileException("MISSING_DSL", "JSON field 'dsl' is required", 1, 1);
            String snapshotId = input.get("snapshotId") instanceof String value
                    ? value : "stock-20060104-20260414-v1";
            int maxRows = input.get("maxRows") instanceof Number value ? value.intValue() : 100;
            var result = execution.execute(source, snapshotId, maxRows);
            if ("markdown".equalsIgnoreCase(String.valueOf(input.getOrDefault("format", "json"))))
                respondText(exchange, 200, "text/markdown; charset=utf-8", DorisExecutionMarkdownRenderer.render(result));
            else respond(exchange, 200, result);
        } catch (CompileException e) {
            boolean syntax = isSyntax(e.code());
            respond(exchange, syntax ? 400 : 422, Map.of(
                    "category", syntax ? "syntax_error" : "semantic_error",
                    "error", e.code(), "message", e.getMessage(), "line", e.line(), "column", e.column()));
        } catch (DorisExecutionException e) {
            String category = switch (e.category()) {
                case DATA_UNAVAILABLE -> "data_unavailable";
                case TIMEOUT -> "timeout";
                case DORIS_ERROR -> "doris_error";
                case SECURITY_LIMIT -> "security_limit";
            };
            int status = switch (e.category()) {
                case DATA_UNAVAILABLE -> 503;
                case TIMEOUT -> 504;
                case DORIS_ERROR -> 502;
                case SECURITY_LIMIT -> 429;
            };
            respond(exchange, status, Map.of("category", category, "error", e.category().name(), "message", e.getMessage()));
        } catch (Exception e) {
            respond(exchange, 500, Map.of("category", "internal_error", "error", "internal_error",
                    "message", e.getMessage() == null ? "Unexpected failure" : e.getMessage()));
        }
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
            Object dslVersion = input.get("dslVersion");
            if (dslVersion != null && !(dslVersion instanceof String))
                throw new CompileException("INVALID_DSL_VERSION", "JSON field 'dslVersion' must be a string", 1, 1);
            respond(exchange, 200, compiler.compile(source, (String) dslVersion));
        } catch (CompileException e) {
            boolean syntax = isSyntax(e.code());
            respond(exchange, syntax ? 400 : 422, Map.of(
                    "category", syntax ? "syntax_error" : "semantic_error",
                    "error", e.code(), "message", e.getMessage(), "line", e.line(), "column", e.column()));
        } catch (Exception e) {
            respond(exchange, 500, Map.of("error", "internal_error", "message", e.getMessage()));
        }
    }

    private static void respond(HttpExchange exchange, int status, Object body) throws IOException {
        byte[] bytes = JsonSupport.MAPPER.writeValueAsBytes(body);
        respondBytes(exchange, status, "application/json; charset=utf-8", bytes);
    }

    private static void respondText(HttpExchange exchange, int status, String contentType, String body) throws IOException {
        respondBytes(exchange, status, contentType, body.getBytes(StandardCharsets.UTF_8));
    }

    private static void respondBytes(HttpExchange exchange, int status, String contentType, byte[] bytes) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", contentType);
        exchange.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) { output.write(bytes); }
    }

    private static boolean isSyntax(String code) {
        String value = code == null ? "" : code.toUpperCase(java.util.Locale.ROOT);
        return value.contains("SYNTAX") || value.contains("LEX") || value.equals("MISSING_DSL")
                || value.equals("EMPTY_DSL") || value.equals("DSL_TOO_LARGE");
    }

    @Override public void close() { server.stop(0); }
}
