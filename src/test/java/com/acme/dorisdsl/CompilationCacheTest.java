package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompilationCache;
import com.acme.dorisdsl.compiler.CompilerVersions;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class CompilationCacheTest {
    @TempDir Path temporaryDirectory;

    @Test void cachesOnlyStructureAndRebindsSensitiveParametersForEveryRequest() {
        DslCompiler compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));

        var first = compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 10 AND MARKET IN ['SH'] LIMIT 5");
        var second = compiler.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 99 AND MARKET IN ['SECRET'] LIMIT 5");

        assertEquals(1, compiler.cacheStats().size());
        assertEquals(1, compiler.cacheStats().hits());
        assertEquals(List.of(LocalDate.parse("2026-08-07"), LocalDate.parse("2026-08-07"),
                new java.math.BigDecimal("10"), "SH"), first.bindings());
        assertEquals(List.of(LocalDate.parse("2026-08-07"), LocalDate.parse("2026-08-07"),
                new java.math.BigDecimal("99"), "SECRET"), second.bindings());
        assertFalse(CompilationCache.CachedCompilation.class.getRecordComponents().length == 0);
        for (var component : CompilationCache.CachedCompilation.class.getRecordComponents()) {
            assertFalse(component.getName().equals("bindings") || component.getName().equals("ast")
                    || component.getName().equals("context") || component.getName().equals("permission"));
        }
    }

    @Test void everyCompilerEnvironmentVersionNaturallyInvalidatesSharedCache() {
        var registry = new RegistryLoader().loadDefault(List.of());
        var cache = new CompilationCache(16);
        String dsl = "SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5";

        new DslCompiler(registry, new CompilerVersions("rules-1", "catalog-1", "doris-1"), cache).compile(dsl);
        new DslCompiler(registry, new CompilerVersions("rules-2", "catalog-1", "doris-1"), cache).compile(dsl);
        new DslCompiler(registry, new CompilerVersions("rules-1", "catalog-2", "doris-1"), cache).compile(dsl);
        new DslCompiler(registry, new CompilerVersions("rules-1", "catalog-1", "doris-2"), cache).compile(dsl);

        assertEquals(4, cache.stats().size());
        assertEquals(0, cache.stats().hits());
        assertEquals(4, cache.stats().misses());
    }

    @Test void tableMappingChangeProducesNewCatalogVersionAndCacheEntry() throws Exception {
        var loader = new RegistryLoader();
        var original = loader.loadDefault(List.of());
        String registryJson;
        try (var input = getClass().getResourceAsStream("/registry.json")) {
            if (input == null) throw new IllegalStateException("Missing registry.json");
            registryJson = new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
        Path changedFile = temporaryDirectory.resolve("changed-registry.json");
        Files.writeString(changedFile, registryJson.replace("market.dwd_quote_daily",
                "market.dwd_quote_daily_v2"), StandardCharsets.UTF_8);
        var changed = loader.load(changedFile, List.of());
        var cache = new CompilationCache(16);
        String dsl = "SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5";

        DslCompiler first = new DslCompiler(original, new CompilerVersions("rules-1",
                original.catalogVersion(), "doris-1"), cache);
        DslCompiler second = new DslCompiler(changed, new CompilerVersions("rules-1",
                changed.catalogVersion(), "doris-1"), cache);
        first.compile(dsl);
        second.compile(dsl);

        assertFalse(original.catalogVersion().equals(changed.catalogVersion()));
        assertEquals(2, cache.stats().size());
        assertEquals(0, cache.stats().hits());
    }
}
