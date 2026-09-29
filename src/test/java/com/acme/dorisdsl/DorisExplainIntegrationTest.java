package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.Types;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class DorisExplainIntegrationTest {
    @Test void dorisExplainsLayeredRsiSql() throws Exception {
        String jdbcUrl = System.getenv("DORIS_JDBC_URL");
        assumeTrue(jdbcUrl != null && !jdbcUrl.isBlank(),
                "Set DORIS_JDBC_URL to run the real Doris EXPLAIN integration test");
        String driver = System.getenv().getOrDefault("DORIS_JDBC_DRIVER", "com.mysql.cj.jdbc.Driver");
        Class.forName(driver);

        var artifact = new DslCompiler(new RegistryLoader().loadDefault(List.of())).compile(
                "SCREEN ON 2026-08-07 WHERE RSI(CLOSE, 14) > 50 LIMIT 5");
        String user = System.getenv().getOrDefault("DORIS_JDBC_USER", "root");
        String password = System.getenv().getOrDefault("DORIS_JDBC_PASSWORD", "");
        try (var connection = DriverManager.getConnection(jdbcUrl, user, password);
             PreparedStatement statement = connection.prepareStatement("EXPLAIN " + artifact.sql())) {
            for (int index = 0; index < artifact.bindings().size(); index++) {
                Object value = artifact.bindings().get(index);
                if (value instanceof LocalDate date) statement.setObject(index + 1, date);
                else if (value == null) statement.setNull(index + 1, Types.NULL);
                else statement.setObject(index + 1, value);
            }
            try (var rows = statement.executeQuery()) {
                assertTrue(rows.next(), "Doris EXPLAIN must return a query plan");
            }
        }
    }
}
