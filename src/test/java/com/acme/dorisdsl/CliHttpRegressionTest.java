package com.acme.dorisdsl;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.net.URI;
import java.net.http.*;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;

class CliHttpRegressionTest {
    private static final String TOKEN="test-only-token-0123456789abcdef0123456789";
    private Process start(Path temp,String token,String... args) throws Exception {
        var command=new ArrayList<String>();
        command.add(Path.of(System.getProperty("java.home"),"bin","java").toString());
        // Use the parent runtime's explicitly selected socket setting in the child.
        String socketDir=System.getProperty("jdk.net.unixdomain.tmpdir");
        if(socketDir!=null) command.add("-Djdk.net.unixdomain.tmpdir="+socketDir);
        command.addAll(List.of("-cp",System.getProperty("surefire.test.class.path",System.getProperty("java.class.path")),"com.acme.dorisdsl.cli.Main"));
        command.addAll(Arrays.asList(args));
        command.addAll(List.of("--auth-token-env","REVIEW_HTTP_TOKEN"));
        var builder=new ProcessBuilder(command).redirectErrorStream(true);
        if(token==null)builder.environment().remove("REVIEW_HTTP_TOKEN"); else builder.environment().put("REVIEW_HTTP_TOKEN",token);
        return builder.start();
    }
    @Test void bothServerCommandsRequireConfiguredAuthenticationBeforeStartup(@TempDir Path temp) throws Exception {
        for(String command:List.of("serve","serve-doris")){
            Process process=start(temp,null,command);
            try {
                assertTrue(process.waitFor(10,TimeUnit.SECONDS));
                String output=new String(process.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
                assertNotEquals(0,process.exitValue());
                assertTrue(output.contains("Set HTTP authentication environment variable: REVIEW_HTTP_TOKEN"),output);
                assertFalse(output.contains("Listening on"));
            }finally{process.destroyForcibly();}
        }
    }
    @Test void weakConfiguredTokenIsRejected(@TempDir Path temp) throws Exception {
        Process process=start(temp,"short","serve");
        try{
            assertTrue(process.waitFor(10,TimeUnit.SECONDS));
            assertNotEquals(0,process.exitValue());
            assertTrue(new String(process.getInputStream().readAllBytes(),StandardCharsets.UTF_8).contains("32..4096"));
        }finally{process.destroyForcibly();}
    }
    @Test void cliServerStartsAndValidTokenCanCompile(@TempDir Path temp) throws Exception {
        Process process=start(temp,TOKEN,"serve","--host","127.0.0.1","--port","0");
        try(var reader=new BufferedReader(new InputStreamReader(process.getInputStream(),StandardCharsets.UTF_8));var client=HttpClient.newHttpClient()){
            String address=null;
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
            while(System.nanoTime()<deadline&&process.isAlive()){
                if(reader.ready()){
                    String line=reader.readLine();
                    if(line!=null&&line.startsWith("Listening on ")){address=line.substring("Listening on ".length()).split(" ")[0];break;}
                }else Thread.sleep(20);
            }
            assertNotNull(address,"CLI did not report its listening address");
            assertEquals(200,client.send(HttpRequest.newBuilder(URI.create(address+"/health")).timeout(Duration.ofSeconds(5)).GET().build(),HttpResponse.BodyHandlers.ofString()).statusCode());
            for(boolean authorized:List.of(false,true)){
                var builder=HttpRequest.newBuilder(URI.create(address+"/compile")).timeout(Duration.ofSeconds(5));
                if(authorized)builder.header("Authorization","Bearer "+TOKEN);
                var response=client.send(builder.POST(HttpRequest.BodyPublishers.ofString("{\"dsl\":\"SCREEN ON 2026-08-07 WHERE CLOSE>10 LIMIT 5\"}")).build(),HttpResponse.BodyHandlers.ofString());
                assertEquals(authorized?200:401,response.statusCode(),response.body());
            }
        }finally{process.destroyForcibly();assertTrue(process.waitFor(5,TimeUnit.SECONDS));}
    }
}
