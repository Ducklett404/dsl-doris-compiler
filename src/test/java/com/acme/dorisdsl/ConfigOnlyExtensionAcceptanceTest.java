package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompilationArtifact;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/** One reusable harness: future existing-lowering extensions add JSON vectors, not Java tests. */
class ConfigOnlyExtensionAcceptanceTest {
    @Test void acceptsAllConfigOnlyExtensionVectorsWithoutCoreChanges() throws Exception {
        Path manifestPath = Path.of(getClass().getResource("/config-only-extensions/manifest.json").toURI());
        Manifest manifest = JsonSupport.MAPPER.readValue(manifestPath.toFile(), Manifest.class);
        assertTrue(manifest.cases().size() >= 3);

        for (Case vector : manifest.cases()) {
            Path plugin = Path.of(vector.plugin()).normalize();
            assertTrue(plugin.startsWith(Path.of("config", "extensions")), vector.id() + " must use extension config");
            assertTrue(Files.isRegularFile(plugin), vector.id() + " plugin is missing");

            var base = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
            assertEquals(vector.baseErrorCode(), assertThrows(CompileException.class,
                    () -> base.compile(vector.dsl()), vector.id()).code());

            var extended = new DslCompiler(new RegistryLoader().loadDefault(List.of(plugin)));
            CompilationArtifact artifact = extended.compile(vector.dsl());
            assertEquals(vector.expectedLookback(), artifact.requiredLookbackTradingDays(), vector.id());
            vector.expectedSqlFragments().forEach(fragment -> assertTrue(artifact.sql().contains(fragment),
                    () -> vector.id() + " missing SQL fragment: " + fragment + "\n" + artifact.sql()));
            vector.forbiddenSqlFragments().forEach(fragment -> assertFalse(artifact.sql().contains(fragment),
                    () -> vector.id() + " leaked forbidden SQL fragment: " + fragment));

            String expected = JsonSupport.MAPPER.writeValueAsString(artifact);
            for (int i = 0; i < 10; i++) assertEquals(expected,
                    JsonSupport.MAPPER.writeValueAsString(extended.compile(vector.dsl())), vector.id());
        }
    }

    record Manifest(List<Case> cases) {
        Manifest { cases = cases == null ? List.of() : List.copyOf(cases); }
    }
    record Case(String id, String plugin, String dsl, String baseErrorCode,
                List<String> expectedSqlFragments, List<String> forbiddenSqlFragments, int expectedLookback) {
        Case {
            expectedSqlFragments = expectedSqlFragments == null ? List.of() : List.copyOf(expectedSqlFragments);
            forbiddenSqlFragments = forbiddenSqlFragments == null ? List.of() : List.copyOf(forbiddenSqlFragments);
        }
    }
}
