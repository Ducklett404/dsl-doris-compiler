package com.acme.dorisdsl;

import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;

class CliSnapshotContextTest {
    @Test void referenceCompilationRetainsHistoricalWindows(@TempDir Path temp) throws Exception {
        Path input=temp.resolve("history.dsl");
        Files.writeString(input,"record_high('', '', '收盘价', '历史', '2026-04-14', '', '', '') = True");
        for (String mode:List.of("OPTIMIZED","FULL_SCAN_REFERENCE")) {
            Path output=temp.resolve(mode+".json");
            var process=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                    "-Dfile.encoding=UTF-8","-Dsun.stdout.encoding=UTF-8","-Dsun.stderr.encoding=UTF-8",
                    "-cp",System.getProperty("surefire.test.class.path"),"com.acme.dorisdsl.cli.Main",
                    "compile-stock-slot-sql",input.toString(),"--access-path",mode)
                    .redirectErrorStream(true).redirectOutput(output.toFile()).start();
            try {
                assertTrue(process.waitFor(10,TimeUnit.SECONDS));
                String text=Files.readString(output,StandardCharsets.UTF_8);
                assertEquals(0,process.exitValue(),text);
                String sql=JsonSupport.MAPPER.readTree(text).get("sql").asText();
                assertEquals(mode.equals("OPTIMIZED"),sql.contains("historical_extrema AS"));
                assertEquals(mode.equals("FULL_SCAN_REFERENCE"),sql.contains("UNBOUNDED PRECEDING"));
            } finally {process.destroyForcibly();}
        }
    }
    @Test void anotherSnapshotUsesHistoricalRowsInsteadOfTheFrozenFeature(@TempDir Path temp) throws Exception {
        Path input=temp.resolve("case.dsl");
        Files.writeString(input,"indicator('', '', '60日均线', '2026-04-14', '', '', '') > 1");
        for (String snapshot:List.of("stock-20060104-20260414-v1","different-snapshot")) {
            var command=new ArrayList<>(List.of(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                    "-Dfile.encoding=UTF-8","-Dsun.stdout.encoding=UTF-8","-Dsun.stderr.encoding=UTF-8",
                    "-cp",System.getProperty("surefire.test.class.path"),
                    "com.acme.dorisdsl.cli.Main","compile-stock-slot-sql",input.toString(),"--snapshot-id",snapshot));
            Path output=temp.resolve(snapshot+".json");
            var process=new ProcessBuilder(command).redirectErrorStream(true).redirectOutput(output.toFile()).start();
            try {
                assertTrue(process.waitFor(10,TimeUnit.SECONDS));
                String text=Files.readString(output,StandardCharsets.UTF_8);
                assertEquals(0,process.exitValue(),text);
                String sql=JsonSupport.MAPPER.readTree(text).get("sql").asText();
                if(snapshot.equals("different-snapshot")) {
                    assertFalse(sql.contains("stock_daily_features"));
                    assertTrue(sql.contains("ROWS BETWEEN 59 PRECEDING"));
                } else assertTrue(sql.contains("stock_daily_features_v2"));
            } finally {process.destroyForcibly();}
        }
    }
}
