package com.acme.dorisdsl.stockslot;

import java.util.List;

public record StockSlotCompilationArtifact(
        String compilerVersion,
        String dslVersion,
        String status,
        StockSlotAst.SemanticModel semanticModel,
        List<StockSlotDiagnostic> diagnostics
) {
    public StockSlotCompilationArtifact { diagnostics = List.copyOf(diagnostics); }
}
