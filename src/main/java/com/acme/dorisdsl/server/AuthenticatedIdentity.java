package com.acme.dorisdsl.server;

public record AuthenticatedIdentity(String userId) {
    public AuthenticatedIdentity {
        if (userId == null || userId.isBlank()) {
            throw new IllegalArgumentException("Authenticated userId is required");
        }
    }
}
