package com.acme.dorisdsl.reference;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class DifferentialCorpusTest {
    private final DslCompiler compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
    private final ReferenceExecutor reference = new ReferenceExecutor();
    private final LoweredPlanExecutor lowered = new LoweredPlanExecutor();
    private final ReferenceDataSet data = ReferenceFixtures.smallMarket();

    @Test void sixHundredDslCasesMatchReferenceExecution() {
        List<CorpusCase> corpus = corpus();
        assertTrue(corpus.size() >= 500);
        int passed = 0;
        List<String> failures = new ArrayList<>();
        for (CorpusCase test : corpus) {
            try {
                var artifact = compiler.compile(test.dsl());
                assertTrue(artifact.sql().contains("SELECT"), "case must produce SQL");
                assertEquals(reference.execute(artifact.ast(), data), lowered.execute(artifact, data), test.id());
                passed++;
            } catch (Throwable error) {
                failures.add(test.id() + ": " + error.getMessage());
            }
        }
        assertEquals(corpus.size(), passed, () -> String.join("\n", failures.subList(0, Math.min(10, failures.size()))));
        assertEquals(600, corpus.size());
    }

    @Test void p0FinancialPointInTimeCasesPassOneHundredPercent() {
        List<CorpusCase> p0 = corpus().stream().filter(CorpusCase::p0Financial).toList();
        int passed = 0;
        for (CorpusCase test : p0) {
            var artifact = compiler.compile(test.dsl());
            assertTrue(artifact.sql().contains("f.visible_from <= q.trade_date"));
            assertTrue(artifact.sql().contains("q.trade_date < f.visible_to"));
            assertFalse(artifact.sql().contains("report_period = q.trade_date"));
            assertEquals(reference.execute(artifact.ast(), data), lowered.execute(artifact, data), test.id());
            passed++;
        }
        assertEquals(200, p0.size());
        assertEquals(p0.size(), passed, "P0 financial semantics must pass 100%");
    }

    @Test void futureReportIsInvisibleBeforeAnnouncement() {
        var beforeAnnouncement = compiler.compile("SCREEN ON 2026-08-07 WHERE ROE_TTM() >= 15% LIMIT 10");
        var afterAnnouncement = compiler.compile("SCREEN ON 2026-08-21 WHERE ROE_TTM() >= 15% LIMIT 10");

        assertFalse(reference.execute(beforeAnnouncement.ast(), data).contains("BBB"));
        assertTrue(reference.execute(afterAnnouncement.ast(), data).contains("BBB"));
        assertEquals(reference.execute(beforeAnnouncement.ast(), data), lowered.execute(beforeAnnouncement, data));
        assertEquals(reference.execute(afterAnnouncement.ast(), data), lowered.execute(afterAnnouncement, data));
    }

    private List<CorpusCase> corpus() {
        List<CorpusCase> cases = new ArrayList<>(600);
        for (int i = 0; i < 600; i++) {
            int family = i % 12;
            String predicate = switch (family) {
                case 0 -> "CLOSE > " + (8 + i % 35);
                case 1 -> "MA(CLOSE, 5) >= " + (10 + i % 25);
                case 2 -> "MA(CLOSE, 20) < " + (18 + i % 20);
                case 3 -> "CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))";
                case 4 -> "MARKET IN ['SH', 'SZ'] AND TURNOVER_RATE > " + (1 + i % 3) + "%";
                case 5 -> "CLOSE BETWEEN " + (10 + i % 10) + " AND " + (30 + i % 15);
                case 6 -> "ABS(CLOSE - OPEN) >= " + (i % 4);
                case 7 -> "NOT (VOLUME < " + (900 + i * 3) + ")";
                case 8 -> "PE_TTM() BETWEEN " + (5 + i % 5) + " AND " + (20 + i % 25);
                case 9 -> "ROE_TTM() >= " + (5 + i % 18) + "%";
                case 10 -> "PE_TTM() < " + (15 + i % 25) + " AND ROE_TTM() >= " + (6 + i % 12) + "%";
                default -> "(ROE_TTM() >= " + (7 + i % 15) + "% OR PE_TTM() < " + (10 + i % 20) + ")";
            };
            boolean p0 = family >= 9 || family == 8;
            String order = i % 3 == 0 ? " ORDER BY CLOSE DESC" : i % 3 == 1 ? " ORDER BY TURNOVER_RATE ASC" : "";
            String date = i % 10 == 0 ? "2026-07-17" : "2026-08-07";
            cases.add(new CorpusCase("DSL-" + String.format("%03d", i + 1),
                    "SCREEN ON " + date + " WHERE " + predicate + order + " LIMIT " + (1 + i % 4), p0));
        }
        return List.copyOf(cases);
    }

    private record CorpusCase(String id, String dsl, boolean p0Financial) {}
}
