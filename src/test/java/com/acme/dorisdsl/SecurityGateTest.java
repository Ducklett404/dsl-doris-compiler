package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompilationCache;
import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.CompilerVersions;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.PluginVerifier;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.security.ReadOnlyExecutionAccount;
import com.acme.dorisdsl.security.SecurityPolicy;
import com.acme.dorisdsl.server.PermissionGate;
import com.acme.dorisdsl.server.AuthenticatedIdentity;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SecurityGateTest {
    @TempDir Path temporaryDirectory;

    @Test void permissionGateRequiresIdentityAndCompilePermission() {
        PermissionGate gate = new PermissionGate((userId, permission) -> false);
        assertEquals("AUTH_FORBIDDEN", assertThrows(CompileException.class,
                () -> gate.authorize(new AuthenticatedIdentity("u1"))).code());
        new PermissionGate((userId, permission) -> userId.equals("u1") && permission.equals("COMPILE_DSL"))
                .authorize(new AuthenticatedIdentity("u1"));
    }

    @Test void scanAndCostGatesRejectExpensivePlans() {
        var registry = new RegistryLoader().loadDefault(List.of());
        var versions = new CompilerVersions("rules-test", registry.catalogVersion(), "doris-test");
        var scanLimited = new DslCompiler(registry, versions, new CompilationCache(8),
                new SecurityPolicy(1, 10_000, 6_000_000, 128));
        assertEquals("SCAN_LIMIT_EXCEEDED", assertThrows(CompileException.class,
                () -> scanLimited.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5")).code());

        var costLimited = new DslCompiler(registry, versions, new CompilationCache(8),
                new SecurityPolicy(Long.MAX_VALUE, 1, 6_000_000, 128));
        assertEquals("COST_LIMIT_EXCEEDED", assertThrows(CompileException.class,
                () -> costLimited.compile("SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5")).code());
    }

    @Test void auditHashesSqlAndNeverContainsSensitiveBindingValues() {
        DslCompiler compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        compiler.compile("SCREEN ON 2026-08-07 WHERE MARKET IN ['PRIVATE_POOL'] AND CLOSE > 987654 LIMIT 5");
        compiler.compile("SCREEN ON 2026-08-08 WHERE MARKET IN ['SECOND_SECRET'] AND CLOSE > 123456 LIMIT 5");

        var audit = compiler.securityAudits().getLast();
        assertEquals(2, compiler.securityAudits().size(), "cache hits must produce their own audit entry");
        assertEquals(1, compiler.cacheStats().hits());
        assertTrue(audit.sqlHash().matches("sha256:[0-9a-f]{64}"));
        assertTrue(audit.estimatedScanBytes() > 0);
        assertTrue(audit.estimatedPlanCost() > 0);
        String auditText = audit.toString();
        assertFalse(auditText.contains("PRIVATE_POOL"));
        assertFalse(auditText.contains("987654"));
        assertFalse(auditText.contains("SECOND_SECRET"));
        assertFalse(auditText.contains("123456"));
        assertTrue(audit.redactedBindings().contains("<string:redacted>"));
    }

    @Test void executionAccountRejectsWritePrivileges() {
        new ReadOnlyExecutionAccount("dsl_reader", Set.of("SELECT", "SHOW", "EXPLAIN"));
        assertThrows(IllegalArgumentException.class,
                () -> new ReadOnlyExecutionAccount("dsl_writer", Set.of("SELECT", "INSERT")));
    }

    @Test void dslCannotPassSqlCommentsSubqueriesSemicolonsOrDynamicIdentifiers() {
        DslCompiler compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        for (String attack : List.of(
                "SCREEN ON 2026-08-07 WHERE CLOSE > 1; DROP TABLE x",
                "SCREEN ON 2026-08-07 WHERE CLOSE > 1 -- bypass",
                "SCREEN ON 2026-08-07 WHERE CLOSE > (SELECT 1) LIMIT 5",
                "SCREEN ON 2026-08-07 WHERE CLOSE > 1 /* bypass */ LIMIT 5")) {
            assertEquals("DSL_UNSAFE_TOKEN", assertThrows(CompileException.class,
                    () -> compiler.compile(attack)).code());
        }
        CompileException dynamicColumn = assertThrows(CompileException.class,
                () -> compiler.compile("SCREEN ON 2026-08-07 WHERE USER_COLUMN > 1 LIMIT 5"));
        assertEquals("UNKNOWN_FIELD", dynamicColumn.code());
        assertFalse(compiler.compile("SCREEN ON 2026-08-07 WHERE MARKET = 'db.table.column' LIMIT 5")
                .sql().contains("db.table.column"));
    }

    @Test void pluginSignatureVersionAndSqlFragmentsAreEnforced() throws Exception {
        String valid = Files.readString(Path.of(getClass().getResource("/custom-plugin.json").toURI()));
        assertPluginRejected(valid.replace("ABS({0} - {1})", "ABS({0} + {1})"), "PLUGIN_SIGNATURE_INVALID");

        String incompatibleUnsigned = valid.replace("\"maxCompilerVersion\": \"0.1.0\"",
                "\"maxCompilerVersion\": \"0.0.9\"");
        assertPluginRejected(resign(incompatibleUnsigned), "PLUGIN_VERSION_INCOMPATIBLE");

        String unsafeUnsigned = valid.replace("ABS({0} - {1})", "(SELECT secret FROM admin.users)");
        assertPluginRejected(resign(unsafeUnsigned), "REGISTRY_UNSAFE");
    }

    private String resign(String json) throws Exception {
        var node = (com.fasterxml.jackson.databind.node.ObjectNode) JsonSupport.MAPPER.readTree(json);
        node.put("signature", PluginVerifier.signature(node, JsonSupport.MAPPER));
        return JsonSupport.MAPPER.writeValueAsString(node);
    }

    private void assertPluginRejected(String content, String code) throws Exception {
        Path plugin = temporaryDirectory.resolve(code + ".json");
        Files.writeString(plugin, content, StandardCharsets.UTF_8);
        CompileException exception = assertThrows(CompileException.class,
                () -> new RegistryLoader().loadDefault(List.of(plugin)));
        assertEquals(code, exception.code());
    }
}
