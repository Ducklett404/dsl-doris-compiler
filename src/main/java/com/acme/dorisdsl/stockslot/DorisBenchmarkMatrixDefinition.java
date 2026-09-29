package com.acme.dorisdsl.stockslot;

import java.util.List;

public record DorisBenchmarkMatrixDefinition(String matrixVersion, String snapshotId, List<CaseDefinition> cases) {
    public DorisBenchmarkMatrixDefinition { cases = List.copyOf(cases); }
    public record CaseDefinition(String id, String category, String dsl) {}
}
