package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PluginTest {
    @TempDir Path tempDir;

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

    @Test void rejectsTemplatePlaceholderOutsideDeclaredArity() throws Exception {
        CompileException error = loadTemplateExpectingFailure("ABS({1})", requiredArguments("value"));
        assertEquals("REGISTRY_INVALID", error.code());
        assertTrue(error.getMessage().contains("{1}") && error.getMessage().contains("maxArgs=1"));
    }

    @Test void rejectsTemplateThatOmitsARequiredArgument() throws Exception {
        CompileException error = loadTemplateExpectingFailure("ABS({0})", requiredArguments("left", "right"));
        assertEquals("REGISTRY_INVALID", error.code());
        assertTrue(error.getMessage().contains("required argument 1"));
    }

    @Test void rejectsOptionalPlaceholderWithoutConditionalTemplateSupport() throws Exception {
        String arguments = """
                [{"name":"value","type":"ScalarNumber"},
                 {"name":"scale","type":"ScalarNumber","defaultValue":1}]
                """;
        CompileException error = loadTemplateExpectingFailure("ABS({0}) * {1}", arguments);
        assertEquals("REGISTRY_INVALID", error.code());
        assertTrue(error.getMessage().contains("optional argument"));
    }

    @Test void rejectsMalformedTemplatePlaceholder() throws Exception {
        CompileException error = loadTemplateExpectingFailure("ABS({value})", requiredArguments("value"));
        assertEquals("REGISTRY_INVALID", error.code());
        assertTrue(error.getMessage().contains("expected {n}"));
    }

    @Test void permitsRepeatedUseOfEveryRequiredArgument() throws Exception {
        Path plugin = writeTemplatePlugin("ABS({0}) + ABS({0})", requiredArguments("value"));
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of(plugin)));
        var artifact = compiler.compile("SCREEN ON 2026-08-07 WHERE TEMPLATE_TEST(1) > 0 LIMIT 1");
        assertTrue(artifact.sql().contains("ABS(?) + ABS(?) > ?"));
    }

    private void assertUnsafePlugin(String resource) throws Exception {
        Path plugin = Path.of(getClass().getResource(resource).toURI());
        CompileException error = assertThrows(CompileException.class,
                () -> new RegistryLoader().loadDefault(List.of(plugin)));
        assertTrue(error.code().equals("REGISTRY_UNSAFE") || error.code().equals("REGISTRY_INVALID"));
    }

    private CompileException loadTemplateExpectingFailure(String template, String arguments) throws Exception {
        Path plugin = writeTemplatePlugin(template, arguments);
        return assertThrows(CompileException.class, () -> new RegistryLoader().loadDefault(List.of(plugin)));
    }

    private Path writeTemplatePlugin(String template, String arguments) throws Exception {
        Path plugin = tempDir.resolve("template-plugin-" + Math.abs(template.hashCode()) + ".json");
        Files.writeString(plugin, """
                {"functions":[{
                  "name":"TEMPLATE_TEST",
                  "id":"test.template",
                  "version":"1.0.0",
                  "signature":{"arguments":%s,"returnType":"ScalarNumber"},
                  "returnType":"ScalarNumber",
                  "loweringKind":"TEMPLATE",
                  "sqlTemplate":"%s"
                }]}
                """.formatted(arguments, template));
        return plugin;
    }

    private String requiredArguments(String... names) {
        return java.util.Arrays.stream(names)
                .map(name -> "{\"name\":\"" + name + "\",\"type\":\"ScalarNumber\"}")
                .collect(java.util.stream.Collectors.joining(",", "[", "]"));
    }
}
