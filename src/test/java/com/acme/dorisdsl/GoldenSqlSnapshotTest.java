package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.HexFormat;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

final class GoldenSqlSnapshotTest {
    @Test void generatedSqlAndBindingsMatchFrozenFingerprints() throws Exception {
        Snapshot snapshot = JsonSupport.MAPPER.readValue(
                Path.of("src/test/resources/golden-sql/stock-slot-v1.json").toFile(), Snapshot.class);
        assertEquals("stock-slot-sql-v1", snapshot.snapshotVersion());
        assertTrue(snapshot.cases().size() >= 5);
        var compiler = new StockSlotSqlCompiler();
        Map<String, String> expected = new LinkedHashMap<>();
        Map<String, String> actual = new LinkedHashMap<>();
        for (Case item : snapshot.cases()) {
            var artifact = compiler.compile(item.dsl());
            String material = artifact.sql().replace("\r\n", "\n") + "\n"
                    + JsonSupport.MAPPER.writeValueAsString(artifact.bindings());
            expected.put(item.id(), item.expectedSha256());
            actual.put(item.id(), HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(material.getBytes(StandardCharsets.UTF_8))));
        }
        assertEquals(expected, actual);
    }

    record Snapshot(String snapshotVersion, List<Case> cases) {}
    record Case(String id, String dsl, String expectedSha256) {}
}
