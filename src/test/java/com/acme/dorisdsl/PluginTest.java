package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PluginTest {
    @Test void addsIndicatorWithoutChangingCompilerCore() throws Exception {
        Path plugin = Path.of(getClass().getResource("/custom-plugin.json").toURI());
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of(plugin)));
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE ABS_CHANGE(CLOSE, OPEN) > 1
                ADJUST FORWARD
                LIMIT 10
                """);
        assertTrue(artifact.sql().contains("ABS(`close` - `open`) > ?"));
        assertTrue(artifact.sql().contains("q.close_qfq AS `close`"));
        assertTrue(artifact.sql().contains("q.open_qfq AS `open`"));
    }

    @Test void addsControlledWindowIndicatorWithoutChangingCompilerCore() throws Exception {
        Path plugin = Path.of(getClass().getResource("/custom-plugin.json").toURI());
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of(plugin)));
        var artifact = compiler.compile("""
                SCREEN ON 2026-08-07
                WHERE VOLATILITY(CLOSE, 20) > 1
                ADJUST FORWARD
                LIMIT 10
                """);
        assertTrue(artifact.sql().contains("STDDEV_SAMP(`close`) OVER"));
        assertTrue(artifact.sql().contains("ROWS BETWEEN 19 PRECEDING AND CURRENT ROW"));
        assertEquals(20, artifact.requiredLookbackTradingDays());
    }

    @Test void rejectsUnsafePluginSqlFragments() throws Exception {
        assertUnsafePlugin("/unsafe-plugin-semicolon.json");
        assertUnsafePlugin("/unsafe-plugin-comment.json");
        assertUnsafePlugin("/unsafe-plugin-subquery.json");
        assertUnsafePlugin("/unsafe-plugin-dynamic-table.json");
    }

    @Test void rejectsUncontrolledWindowBuilder() {
        Path plugin = Path.of("src/test/resources/unsafe-plugin-irbuilder.json");
        CompileException error = assertThrows(CompileException.class,
                () -> new RegistryLoader().loadDefault(List.of(plugin)));
        assertEquals("REGISTRY_INVALID", error.code());
        assertTrue(error.getMessage().contains("WindowStddevBuilder") || error.getMessage().contains("nullPolicy"));
    }

    private void assertUnsafePlugin(String resource) throws Exception {
        Path plugin = Path.of(getClass().getResource(resource).toURI());
        CompileException error = assertThrows(CompileException.class,
                () -> new RegistryLoader().loadDefault(List.of(plugin)));
        assertTrue(error.code().equals("REGISTRY_UNSAFE") || error.code().equals("REGISTRY_INVALID"));
    }
}
