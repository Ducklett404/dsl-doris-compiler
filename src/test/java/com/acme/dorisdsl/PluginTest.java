package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.List;

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
}
