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
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;

public final class CompileHttpServer implements AutoCloseable {
    public static final int DEFAULT_MAX_BODY_BYTES = 1_048_576;
    public static final int DEFAULT_MAX_CONCURRENT_REQUESTS = 32;
    private final HttpServer server;
    private final ExecutorService workers = Executors.newVirtualThreadPerTaskExecutor();
    private final Semaphore admission;
    private final int maxBodyBytes;
    private final ObjectMapper requestMapper = JsonSupport.MAPPER.copy()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    public CompileHttpServer(DslCompiler compiler, String host, int port) throws IOException {
        this(compiler, null, host, port, RequestAuthenticator.REJECT_ALL, (userId, permission) -> false);
    }

    public CompileHttpServer(DslCompiler compiler, DorisExecutionEndpoint execution, String host, int port) throws IOException {
        this(compiler, execution, host, port, RequestAuthenticator.REJECT_ALL, (userId, permission) -> false);
    }

    public CompileHttpServer(DslCompiler compiler, String host, int port,
                             RequestAuthenticator authenticator, PermissionService permissionService) throws IOException {
        this(compiler, null, host, port, authenticator, permissionService);
    }

    public CompileHttpServer(DslCompiler compiler, DorisExecutionEndpoint execution, String host, int port,
                              RequestAuthenticator authenticator, PermissionService permissionService) throws IOException {
        this(compiler, execution, host, port, authenticator, permissionService,
                DEFAULT_MAX_BODY_BYTES, DEFAULT_MAX_CONCURRENT_REQUESTS);
    }

    public CompileHttpServer(DslCompiler compiler, DorisExecutionEndpoint execution, String host, int port,
                              RequestAuthenticator authenticator, PermissionService permissionService,
                              int maxBodyBytes, int maxConcurrentRequests) throws IOException {
        if (maxBodyBytes < 1 || maxBodyBytes > DEFAULT_MAX_BODY_BYTES || maxConcurrentRequests < 1 || maxConcurrentRequests > 256)
            throw new IllegalArgumentException("Invalid HTTP resource limits");
        this.maxBodyBytes = maxBodyBytes;
        this.admission = new Semaphore(maxConcurrentRequests);
        requestMapper.getFactory().setStreamReadConstraints(StreamReadConstraints.builder()
                .maxNestingDepth(32).maxStringLength(100_000).maxNumberLength(32).build());
        PermissionGate permissionGate = new PermissionGate(permissionService);
        server = HttpServer.create(new InetSocketAddress(host, port), 32);
        server.createContext("/health", exchange -> {
            try {
                if (!"/health".equals(exchange.getRequestURI().getPath())) respond(exchange, 404, Map.of("error", "not_found"));
                else if (!"GET".equals(exchange.getRequestMethod())) respond(exchange, 405, Map.of("error", "method_not_allowed"));
                else respond(exchange, 200, Map.of("status", "ok"));
            } finally { exchange.close(); }
        });
        server.createContext("/compile", exchange -> guard(exchange, "/compile", PermissionGate.COMPILE_PERMISSION,
                authenticator, permissionGate, () -> compile(exchange, compiler)));
        if (execution != null) server.createContext("/execute", exchange -> guard(exchange, "/execute", PermissionGate.EXECUTE_PERMISSION,
                authenticator, permissionGate, () -> execute(exchange, execution)));
        server.setExecutor(workers);
    }

    @FunctionalInterface private interface Handler { void run() throws IOException; }
    private void guard(HttpExchange exchange, String path, String permission, RequestAuthenticator authenticator,
                       PermissionGate gate, Handler handler) throws IOException {
        boolean admitted = false;
        try {
            if (!path.equals(exchange.getRequestURI().getPath())) { respond(exchange, 404, Map.of("error", "not_found")); return; }
            if (!"POST".equals(exchange.getRequestMethod())) { respond(exchange, 405, Map.of("error", "method_not_allowed")); return; }
            gate.authorize(authenticator.authenticate(exchange), permission);
            admitted = admission.tryAcquire();
            if (!admitted) { respond(exchange, 429, Map.of("error", "REQUEST_LIMIT", "category", "security_limit")); return; }
            handler.run();
        } catch (CompileException e) {
            respond(exchange, statusFor(e), Map.of("error", e.code(), "message", e.getMessage()));
        } catch (RuntimeException e) {
            respond(exchange, 500, Map.of("error", "internal_error", "message", "Unexpected server failure"));
        } finally {
            if (admitted) admission.release();
            exchange.close();
        }
    }

    private Map<String, Object> readInput(HttpExchange exchange, Set<String> allowed) throws IOException {
        String declared = exchange.getRequestHeaders().getFirst("Content-Length");
        if (declared != null) {
            try { if (Long.parseLong(declared) > maxBodyBytes) throw tooLarge(); }
            catch (NumberFormatException e) { throw invalid("Content-Length"); }
        }
        byte[] bytes = exchange.getRequestBody().readNBytes(maxBodyBytes + 1);
        if (bytes.length > maxBodyBytes) throw tooLarge();
        com.fasterxml.jackson.databind.JsonNode tree;
        try { tree = requestMapper.readTree(bytes); }
        catch (IOException e) { throw new CompileException("INVALID_JSON", "A valid bounded JSON object is required", 1, 1); }
        if (tree == null || !tree.isObject()) throw invalid("JSON object");
        @SuppressWarnings("unchecked") Map<String, Object> input = requestMapper.convertValue(tree, Map.class);
        rejectClientAuthorizationContext(input);
        if (!allowed.containsAll(input.keySet())) throw invalid("unknown field");
        return input;
    }
    private static CompileException tooLarge() { return new CompileException("REQUEST_TOO_LARGE", "Request body exceeds the byte limit", 1, 1); }
    private static CompileException invalid(String field) { return new CompileException("INVALID_REQUEST", "Invalid JSON field: " + field, 1, 1); }

    private void execute(HttpExchange exchange, DorisExecutionEndpoint execution) throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, Map.of("error", "method_not_allowed"));
            return;
        }
        try {
            Map<String, Object> input = readInput(exchange, Set.of("dsl", "snapshotId", "maxRows", "format"));
            Object dsl = input.get("dsl");
            if (!(dsl instanceof String source))
                throw new CompileException("MISSING_DSL", "JSON field 'dsl' is required", 1, 1);
            String snapshotId = input.get("snapshotId") instanceof String value
                    ? value : "stock-20060104-20260414-v1";
            if (input.containsKey("snapshotId") && (!(input.get("snapshotId") instanceof String) || snapshotId.isBlank() || snapshotId.length() > 128))
                throw invalid("snapshotId");
            int maxRows = 100;
            if (input.containsKey("maxRows")) {
                Object value = input.get("maxRows");
                if (!(value instanceof Integer rows) || rows < 1 || rows > 100_000) throw invalid("maxRows");
                maxRows = rows;
            }
            if (input.containsKey("format") && (!(input.get("format") instanceof String value)
                    || !Set.of("json", "markdown").contains(value.toLowerCase(java.util.Locale.ROOT)))) throw invalid("format");
            var result = execution.execute(source, snapshotId, maxRows);
            if ("markdown".equalsIgnoreCase(String.valueOf(input.getOrDefault("format", "json"))))
                respondText(exchange, 200, "text/markdown; charset=utf-8", DorisExecutionMarkdownRenderer.render(result));
            else respond(exchange, 200, result);
        } catch (CompileException e) {
            boolean syntax = isSyntax(e.code());
            respond(exchange, e.code().equals("REQUEST_TOO_LARGE") ? 413 : syntax ? 400 : 422, Map.of(
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
                    "message", "Unexpected server failure"));
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
            Map<String, Object> input = readInput(exchange, Set.of("dsl", "dslVersion"));
            Object dsl = input.get("dsl");
            if (!(dsl instanceof String source)) throw new CompileException("MISSING_DSL", "JSON field 'dsl' is required", 1, 1);
            Object dslVersion = input.get("dslVersion");
            if (input.containsKey("dslVersion") && !(dslVersion instanceof String))
                throw new CompileException("INVALID_DSL_VERSION", "JSON field 'dslVersion' must be a string", 1, 1);
            respond(exchange, 200, compiler.compile(source, (String) dslVersion));
        } catch (CompileException e) {
            respond(exchange, statusFor(e), Map.of("error", e.code(), "message", e.getMessage(), "line", e.line(),
                    "column", e.column(), "fragment", e.fragment(), "suggestion", e.suggestion()));
        } catch (Exception e) {
            respond(exchange, 500, Map.of("error", "internal_error", "message", "Unexpected server failure"));
        }
    }

    private int statusFor(CompileException exception) {
        return switch (exception.code()) {
            case "AUTH_REQUIRED" -> 401;
            case "AUTH_FORBIDDEN" -> 403;
            case "REQUEST_TOO_LARGE" -> 413;
            case "SCAN_LIMIT_EXCEEDED", "COST_LIMIT_EXCEEDED" -> 422;
            default -> 400;
        };
    }

    private void rejectClientAuthorizationContext(Map<String, Object> input) {
        if (input.containsKey("context") || input.containsKey("userId") || input.containsKey("permissions")) {
            throw new CompileException("CLIENT_AUTH_CONTEXT_FORBIDDEN",
                    "Identity and permissions must come from the trusted server authentication layer", 1, 1);
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
                || value.equals("EMPTY_DSL") || value.equals("DSL_TOO_LARGE") || value.equals("INVALID_JSON")
                || value.equals("INVALID_REQUEST") || value.equals("CLIENT_AUTH_CONTEXT_FORBIDDEN");
    }

    @Override public void close() { server.stop(0); workers.close(); }
}
