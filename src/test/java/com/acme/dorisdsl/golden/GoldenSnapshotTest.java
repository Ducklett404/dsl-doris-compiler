package com.acme.dorisdsl.golden;

import com.acme.dorisdsl.ast.AstSnapshot;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.sql.StableSqlFormatter;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class GoldenSnapshotTest {
    private final DslCompiler compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));

    @Test void sqlAndAstSnapshotsRemainStable() throws Exception {
        verify("constant_fold", """
                SCREEN ON 2026-08-07
                WHERE CLOSE > 10 + 5 AND MARKET IN ['SH', 'SZ']
                ORDER BY TURNOVER_RATE DESC
                LIMIT 20
                """);
        verify("financial_window", """
                SCREEN ON 2026-08-07
                WHERE PE_TTM() BETWEEN 0 AND 20
                  AND ROE_TTM() >= 15%
                  AND CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
                ADJUST FORWARD
                LIMIT 100
                """);
    }

    @Test void astSnapshotDeclaresSchemaVersion() throws Exception {
        String snapshot = resource("constant_fold.json");
        assertTrue(snapshot.contains("\"schemaVersion\" : \"" + AstSnapshot.SCHEMA_VERSION + "\""));
    }

    private void verify(String name, String dsl) throws Exception {
        var artifact = compiler.compile(dsl);
        String actualSql = StableSqlFormatter.format(artifact.sql());
        String actualAst = normalizeLines(
                JsonSupport.MAPPER.writeValueAsString(AstSnapshot.from(artifact.ast()))) + "\n";
        if (Boolean.getBoolean("updateGolden")) {
            writeGolden(name + ".sql", actualSql);
            writeGolden(name + ".json", actualAst);
            return;
        }
        assertGolden("golden/" + name + ".sql", resource(name + ".sql"), actualSql);
        assertGolden("golden/" + name + ".json", resource(name + ".json"), actualAst);
    }

    private void writeGolden(String name, String value) throws IOException {
        Path directory = Path.of(System.getProperty("user.dir"), "src", "test", "resources", "golden");
        Files.createDirectories(directory);
        Files.writeString(directory.resolve(name), value, StandardCharsets.UTF_8);
    }

    private String resource(String name) throws IOException {
        try (var input = getClass().getResourceAsStream("/golden/" + name)) {
            if (input == null) throw new IOException("Missing golden snapshot: src/test/resources/golden/" + name);
            return normalizeLines(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
    }

    private String normalizeLines(String value) {
        return value.replace("\r\n", "\n").replace('\r', '\n');
    }

    private void assertGolden(String path, String expected, String actual) {
        if (expected.equals(actual)) return;
        int line = firstDifferentLine(expected, actual);
        String expectedLine = line(expected, line);
        String actualLine = line(actual, line);
        assertEquals(expected, actual, () -> "Golden snapshot changed: " + path + " at line " + line
                + "\nexpected: " + expectedLine + "\nactual:   " + actualLine
                + "\nExplain the compiler rule/schema change before updating this snapshot.");
    }

    private int firstDifferentLine(String expected, String actual) {
        String[] left = expected.split("\n", -1);
        String[] right = actual.split("\n", -1);
        int length = Math.min(left.length, right.length);
        for (int i = 0; i < length; i++) if (!left[i].equals(right[i])) return i + 1;
        return length + 1;
    }

    private String line(String value, int number) {
        String[] lines = value.split("\n", -1);
        return number <= lines.length ? lines[number - 1] : "<EOF>";
    }
}
