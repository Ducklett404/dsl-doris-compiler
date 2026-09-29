package com.acme.dorisdsl.server;

import com.acme.dorisdsl.stockslot.DorisExecutionArtifact;

@FunctionalInterface
public interface DorisExecutionEndpoint {
    DorisExecutionArtifact execute(String dsl, String snapshotId, int maxRows);
}
