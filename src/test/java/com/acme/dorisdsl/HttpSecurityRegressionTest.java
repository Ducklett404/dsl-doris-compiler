package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.server.*;
import com.acme.dorisdsl.stockslot.DorisExecutionException;
import org.junit.jupiter.api.Test;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.io.ByteArrayInputStream;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class HttpSecurityRegressionTest {
    private static final String TOKEN = "test-only-token-0123456789abcdef0123456789";
    private static final String BODY = "{\"dsl\":\"SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5\"}";
    private DslCompiler compiler() { return new DslCompiler(new RegistryLoader().loadDefault(List.of())); }
    private HttpResponse<String> post(HttpClient client, CompileHttpServer server, String path, String body, String token) throws Exception {
        return client.send(request(server, path, body, token, false), HttpResponse.BodyHandlers.ofString());
    }
    private HttpRequest request(CompileHttpServer server, String path, String body, String token, boolean chunked) {
        var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+server.port()+path)).timeout(Duration.ofSeconds(10));
        if (token != null) builder.header("Authorization", "Bearer "+token);
        return builder.POST(chunked ? HttpRequest.BodyPublishers.ofInputStream(() -> new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8)))
                : HttpRequest.BodyPublishers.ofString(body)).build();
    }
    @Test void anonymousExecutionNeverReachesBackend() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        try (var client = HttpClient.newHttpClient(); var server = new CompileHttpServer(compiler(), (dsl,snapshot,rows) -> {
            calls.incrementAndGet(); throw new IllegalStateException("backend must not run");
        }, "127.0.0.1",0)) {
            server.start();
            assertEquals(401,post(client,server,"/execute","{\"dsl\":\"anything\"}",null).statusCode());
            assertEquals(0,calls.get());
        }
    }
    @Test void bearerTokenAndSeparateExecutionPermissionAreEnforced() throws Exception {
        var access = new BearerTokenAccess(TOKEN,Set.of(PermissionGate.COMPILE_PERMISSION));
        AtomicInteger calls = new AtomicInteger();
        try (var client = HttpClient.newHttpClient(); var server = new CompileHttpServer(compiler(),(dsl,snapshot,rows) -> {
            calls.incrementAndGet(); throw new IllegalStateException("backend must not run");
        },"127.0.0.1",0,access,access)) {
            server.start();
            assertEquals(401,post(client,server,"/compile",BODY,"wrong").statusCode());
            assertEquals(200,post(client,server,"/compile",BODY,TOKEN).statusCode());
            assertEquals(403,post(client,server,"/execute","{\"dsl\":\"anything\"}",TOKEN).statusCode());
            var duplicate=request(server,"/compile",BODY,TOKEN,false);
            var forged=HttpRequest.newBuilder(duplicate.uri()).header("Authorization","Bearer "+TOKEN)
                    .header("Authorization","Bearer "+TOKEN).POST(HttpRequest.BodyPublishers.ofString(BODY)).build();
            assertEquals(401,client.send(forged,HttpResponse.BodyHandlers.ofString()).statusCode());
            assertEquals(0,calls.get());
        }
    }
    @Test void executionWithPermissionReachesBackendAndRejectsForgedBody() throws Exception {
        var access=new BearerTokenAccess(TOKEN,Set.of(PermissionGate.COMPILE_PERMISSION,PermissionGate.EXECUTE_PERMISSION));
        AtomicInteger calls=new AtomicInteger();
        try(var client=HttpClient.newHttpClient();var server=new CompileHttpServer(compiler(),(dsl,snapshot,rows)->{
            calls.incrementAndGet(); throw new DorisExecutionException(DorisExecutionException.Category.DATA_UNAVAILABLE,"snapshot missing");
        },"127.0.0.1",0,access,access)){
            server.start();
            assertEquals(400,post(client,server,"/execute","{\"dsl\":\"x\",\"permissions\":[\"EXECUTE_DSL\"]}",TOKEN).statusCode());
            for(String value:List.of("0","-1","1.5","100001","null","\"2\"","999999999999999999"))
                assertEquals(400,post(client,server,"/execute","{\"dsl\":\"x\",\"maxRows\":"+value+"}",TOKEN).statusCode());
            assertEquals(503,post(client,server,"/execute","{\"dsl\":\"x\",\"maxRows\":1}",TOKEN).statusCode());
            assertEquals(1,calls.get());
        }
    }
    @Test void byteLimitsAlsoApplyToChunkedAndMultibyteBodies() throws Exception {
        var access=new BearerTokenAccess(TOKEN,Set.of(PermissionGate.COMPILE_PERMISSION));
        try(var client=HttpClient.newHttpClient();var server=new CompileHttpServer(compiler(),null,"127.0.0.1",0,access,access,128,2)){
            server.start();
            for(String body:List.of("x".repeat(129),"中".repeat(50))){
                assertEquals(413,post(client,server,"/compile",body,TOKEN).statusCode());
                assertEquals(413,client.send(request(server,"/compile",body,TOKEN,true),HttpResponse.BodyHandlers.ofString()).statusCode());
            }
            assertEquals(200,post(client,server,"/compile",BODY,TOKEN).statusCode());
        }
    }
    @Test void malformedJsonAndPrefixRoutesAreRejectedWithoutLeakingInternals() throws Exception {
        var access=new BearerTokenAccess(TOKEN,Set.of(PermissionGate.COMPILE_PERMISSION));
        try(var client=HttpClient.newHttpClient();var server=new CompileHttpServer(compiler(),"127.0.0.1",0,access,access)){
            server.start();
            for(String body:List.of("{", "[]", "null", "{\"dsl\":\"a\",\"dsl\":\"b\"}",BODY+" {}", "[".repeat(33)+"0"+"]".repeat(33),"{\"dsl\":null}","{\"dsl\":5}","{\"dsl\":\"x\",\"dslVersion\":null}")){
                var response=post(client,server,"/compile",body,TOKEN);
                assertEquals(400,response.statusCode(),response.body());
                assertFalse(response.body().contains("com.fasterxml"));
            }
            assertEquals(404,post(client,server,"/compile/extra",BODY,TOKEN).statusCode());
            assertEquals(405,client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+server.port()+"/compile")).GET().build(),HttpResponse.BodyHandlers.ofString()).statusCode());
            assertEquals(404,client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+server.port()+"/healthz")).GET().build(),HttpResponse.BodyHandlers.ofString()).statusCode());
        }
    }
    @Test void concurrentRequestLimitIsSharedAndPermitIsReleasedAfterFailure() throws Exception {
        var access=new BearerTokenAccess(TOKEN,Set.of(PermissionGate.COMPILE_PERMISSION,PermissionGate.EXECUTE_PERMISSION));
        var entered=new CountDownLatch(1); var release=new CountDownLatch(1);
        try(var client=HttpClient.newHttpClient();var server=new CompileHttpServer(compiler(),(dsl,snapshot,rows)->{
            entered.countDown();
            try { if(!release.await(8,TimeUnit.SECONDS)) throw new IllegalStateException("test timeout"); }
            catch(InterruptedException e){Thread.currentThread().interrupt();throw new IllegalStateException(e);}
            throw new IllegalStateException("sensitive backend details");
        },"127.0.0.1",0,access,access,1024,1)){
            server.start();
            var pending=client.sendAsync(request(server,"/execute","{\"dsl\":\"x\"}",TOKEN,false),HttpResponse.BodyHandlers.ofString());
            try {
                assertTrue(entered.await(5,TimeUnit.SECONDS));
                assertEquals(429,post(client,server,"/compile",BODY,TOKEN).statusCode());
            } finally { release.countDown(); }
            var response=pending.get(5,TimeUnit.SECONDS);
            assertEquals(500,response.statusCode());
            assertFalse(response.body().contains("sensitive"));
            assertEquals(200,post(client,server,"/compile",BODY,TOKEN).statusCode());
        }
    }
    @Test void authenticatorFailuresReturnGenericServerError() throws Exception {
        try(var client=HttpClient.newHttpClient();var server=new CompileHttpServer(compiler(),"127.0.0.1",0,
                exchange->{throw new IllegalStateException("secret provider failure");},(user,permission)->true)){
            server.start(); var response=post(client,server,"/compile",BODY,null);
            assertEquals(500,response.statusCode()); assertFalse(response.body().contains("secret"));
        }
    }
}
