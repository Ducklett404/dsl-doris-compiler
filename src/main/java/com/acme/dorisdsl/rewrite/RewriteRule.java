package com.acme.dorisdsl.rewrite;

import java.util.List;

public record RewriteRule(
        String ruleId,
        String pattern,
        String precondition,
        String transform,
        String semanticProofTag,
        int priority,
        String version,
        List<TestVector> testVectors
) {
    public RewriteRule {
        testVectors = testVectors == null ? List.of() : List.copyOf(testVectors);
    }

    public record TestVector(String inputDsl, String expectedDslHint) {}
}
