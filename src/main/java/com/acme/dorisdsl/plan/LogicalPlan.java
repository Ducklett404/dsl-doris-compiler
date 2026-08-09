package com.acme.dorisdsl.plan;

import java.util.List;

public record LogicalPlan(List<PlanNode> nodes, AccessPathDecision accessPath) {
    public LogicalPlan { nodes = List.copyOf(nodes); }
    public record PlanNode(String kind, String detail) {}
    public record AccessPathDecision(String selected, List<Candidate> candidates, String reason) {
        public AccessPathDecision { candidates = List.copyOf(candidates); }
    }
    public record Candidate(String path, double cost, boolean eligible, String reason) {}
}
