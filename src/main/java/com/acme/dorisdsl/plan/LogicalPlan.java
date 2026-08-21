package com.acme.dorisdsl.plan;

import java.util.List;

public record LogicalPlan(List<PlanNode> nodes, AccessPathDecision accessPath) {
    public LogicalPlan { nodes = List.copyOf(nodes); }
    public record PlanNode(String kind, String detail) {}
    public record AccessPathDecision(String selected, List<Candidate> candidates, String reason) {
        public AccessPathDecision { candidates = List.copyOf(candidates); }
    }
    public record Candidate(String path, CostBreakdown costs, boolean eligible,
                            List<String> eliminationReasons, String reason) {
        public Candidate { eliminationReasons = List.copyOf(eliminationReasons); }
        public double cost() { return costs.total(); }
    }
    public record CostBreakdown(double estimatedScanBytes, double windowComputeCost, double joinCost,
                                double freshnessPenalty, double unsupportedRiskPenalty) {
        public double total() {
            return estimatedScanBytes + windowComputeCost + joinCost + freshnessPenalty + unsupportedRiskPenalty;
        }
    }
}
