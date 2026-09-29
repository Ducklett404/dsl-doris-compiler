package com.acme.dorisdsl.server;

@FunctionalInterface
public interface PermissionService {
    boolean hasPermission(String userId, String permission);
}
