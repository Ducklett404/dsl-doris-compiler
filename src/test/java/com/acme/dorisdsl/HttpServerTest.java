package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.server.CompileHttpServer;
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
            assertEquals(400, error.statusCode());
            assertTrue(error.body().contains("UNKNOWN_FUNCTION"));
        }
    }
}
