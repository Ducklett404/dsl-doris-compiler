package com.acme.dorisdsl.stockslot;

import java.util.List;

public record StockSlotSqlArtifact(
        String dslVersion,
        StockSlotAst.SemanticModel semanticModel,
        List<PlanNode> logicalPlan,
        List<StockSlotWindowContract> windowContracts,
        String sql,
        List<Object> bindings,
        boolean ordered,
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        StockSlotCoveragePlan coveragePlan
) {
    public StockSlotSqlArtifact {
        logicalPlan = List.copyOf(logicalPlan);
        windowContracts = List.copyOf(windowContracts);
        bindings = List.copyOf(bindings);
    }
    public record PlanNode(String kind, String detail) {}
    public StockSlotSqlArtifact(String dslVersion, StockSlotAst.SemanticModel semanticModel,
                                List<PlanNode> logicalPlan, List<StockSlotWindowContract> windowContracts,
                                String sql, List<Object> bindings, boolean ordered) {
        this(dslVersion, semanticModel, logicalPlan, windowContracts, sql, bindings, ordered, null);
    }
}
