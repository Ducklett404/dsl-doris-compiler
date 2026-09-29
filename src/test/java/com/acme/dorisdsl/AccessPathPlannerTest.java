package com.acme.dorisdsl;

import com.acme.dorisdsl.catalog.CatalogSnapshot;
import com.acme.dorisdsl.catalog.CatalogSnapshotLoader;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.plan.LogicalPlan;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.util.JsonSupport;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class AccessPathPlannerTest {
    @Test void emitsAllCandidatesWithCostsAndEliminationReasons() throws Exception {
        var artifact = compiler(new CatalogSnapshotLoader().loadDefault()).compile(CompilerTest.sampleDsl());
        var decision = artifact.logicalPlan().accessPath();

        assertEquals(List.of("DETAIL_TABLE", "PARTITION_BUCKET_INDEX", "PREFIX_DAILY", "FEATURE_DAILY",
                        "MATERIALIZED_VIEW", "QUERY_CACHE_FRIENDLY"),
                decision.candidates().stream().map(LogicalPlan.Candidate::path).toList());
        decision.candidates().forEach(candidate -> {
            var costs = candidate.costs();
            assertEquals(costs.estimatedScanBytes() + costs.windowComputeCost() + costs.joinCost()
                    + costs.freshnessPenalty() + costs.unsupportedRiskPenalty(), candidate.cost());
            if (!candidate.eligible()) assertFalse(candidate.eliminationReasons().isEmpty());
        });
        String json = JsonSupport.MAPPER.writeValueAsString(artifact);
        assertTrue(json.contains("estimatedScanBytes"));
        assertTrue(json.contains("eliminationReasons"));
        assertTrue(json.contains("QUERY_CACHE_FRIENDLY"));
        assertFalse(decision.reason().isBlank());
    }

    @Test void staleMetadataForcesDetailTableFallback() {
        var current = new CatalogSnapshotLoader().loadDefault();
        var stale = new CatalogSnapshot("stale-v1", current.capturedAt(), current.tables(), current.tableMetadata(), current.prefixDaily(),
                new CatalogSnapshot.FeatureMetadata(current.feature().version(), current.feature().adjustmentVersion(),
                        current.feature().sourceSnapshot(), current.feature().sourceSnapshotAsOf(),
                        Instant.parse("2026-08-06T23:59:59Z"), current.feature().indicatorColumns()),
                current.doris());

        var decision = compiler(stale).compile(CompilerTest.sampleDsl()).logicalPlan().accessPath();

        assertEquals("DETAIL_TABLE", decision.selected());
        assertTrue(decision.reason().contains("mandatory fallback"));
        var feature = decision.candidates().stream().filter(candidate -> candidate.path().equals("FEATURE_DAILY"))
                .findFirst().orElseThrow();
        assertFalse(feature.eligible());
        assertTrue(feature.costs().freshnessPenalty() > 0);
        assertTrue(feature.eliminationReasons().stream().anyMatch(reason -> reason.contains("stale")));
    }

    private DslCompiler compiler(CatalogSnapshot snapshot) {
        return new DslCompiler(new RegistryLoader().loadDefault(List.of()), snapshot);
    }
}
