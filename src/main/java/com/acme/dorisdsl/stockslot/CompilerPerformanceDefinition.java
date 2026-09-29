package com.acme.dorisdsl.stockslot;

import java.util.List;

public record CompilerPerformanceDefinition(String corpusVersion, List<CaseDefinition> cases) {
    public CompilerPerformanceDefinition { cases = cases == null ? List.of() : List.copyOf(cases); }
    public record CaseDefinition(String id, String category, String dsl) {}
}
