package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.server.CompileHttpServer;
import com.acme.dorisdsl.stockslot.DorisExecutionException;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class HttpServerTest {
    @Test void servesHealthCompileAndStructuredErrors() throws Exception {
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        try (var server = new CompileHttpServer(compiler, "127.0.0.1", 0)) {
            server.start();
            var client = HttpClient.newHttpClient();
            var health = client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + server.port() + "/health")).GET().build(),
                    HttpResponse.BodyHandlers.ofString());
            assertEquals(200, health.statusCode());

            String body = JsonSupport.MAPPER.writeValueAsString(Map.of("dsl", "SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5"));
            var response = client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + server.port() + "/compile"))
                            .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body)).build(),
                    HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode());
            assertTrue(response.body().contains("market.dwd_quote_daily"));

            String bad = JsonSupport.MAPPER.writeValueAsString(Map.of("dsl", "SCREEN ON 2026-08-07 WHERE UNKNOWN()"));
            var error = client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + server.port() + "/compile"))
                            .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(bad)).build(),
                    HttpResponse.BodyHandlers.ofString());
            assertEquals(422, error.statusCode());
            assertTrue(error.body().contains("UNKNOWN_FUNCTION"));
            assertTrue(error.body().contains("semantic_error"));
        }
    }

    @Test void routesStockSlotDslByExplicitVersion() throws Exception {
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        try (var server = new CompileHttpServer(compiler, "127.0.0.1", 0)) {
            server.start();
            String body = JsonSupport.MAPPER.writeValueAsString(Map.of(
                    "dslVersion", "stock-slot-v1",
                    "dsl", "indicator('', '', '10日均线', '今天', '', '', '') > 5 limit 0,10"));
            var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + server.port() + "/compile"))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body)).build();
            var response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode());
            assertTrue(response.body().contains("stock-slot-v1"));
            assertTrue(response.body().contains("PARSED"));
        }
    }

    @Test void executionEndpointDistinguishesSyntaxSemanticDataTimeoutAndDorisFailures() throws Exception {
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        try (var server = new CompileHttpServer(compiler, (dsl, snapshot, rows) -> {
            switch (dsl) {
                case "syntax" -> throw new CompileException("STOCK_SLOT_SYNTAX", "bad syntax", 2, 3);
                case "semantic" -> throw new CompileException("EXECUTION_INDICATOR_UNSUPPORTED", "bad meaning", 1, 1);
                case "data" -> throw new DorisExecutionException(DorisExecutionException.Category.DATA_UNAVAILABLE, "snapshot missing");
                case "timeout" -> throw new DorisExecutionException(DorisExecutionException.Category.TIMEOUT, "too slow");
                default -> throw new DorisExecutionException(DorisExecutionException.Category.DORIS_ERROR, "backend unavailable");
            }
        }, "127.0.0.1", 0)) {
            server.start();
            var client = HttpClient.newHttpClient();
            assertExecuteError(client, server.port(), "syntax", 400, "syntax_error");
            assertExecuteError(client, server.port(), "semantic", 422, "semantic_error");
            assertExecuteError(client, server.port(), "data", 503, "data_unavailable");
            assertExecuteError(client, server.port(), "timeout", 504, "timeout");
            assertExecuteError(client, server.port(), "doris", 502, "doris_error");
        }
    }

    private static void assertExecuteError(HttpClient client, int port, String dsl, int status, String category) throws Exception {
        String body = JsonSupport.MAPPER.writeValueAsString(Map.of("dsl", dsl));
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/execute"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var response = client.send(request, HttpResponse.BodyHandlers.ofString());
        assertEquals(status, response.statusCode(), response.body());
        assertEquals(category, JsonSupport.MAPPER.readTree(response.body()).path("category").asText(), response.body());
    }
}
