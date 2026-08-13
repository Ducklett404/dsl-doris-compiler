package com.acme.dorisdsl.server;

import com.acme.dorisdsl.compiler.CompileException;
import com.sun.net.httpserver.HttpExchange;

@FunctionalInterface
public interface RequestAuthenticator {
    RequestAuthenticator REJECT_ALL = exchange -> {
        throw new CompileException("AUTH_REQUIRED", "Trusted authentication is not configured", 1, 1);
    };

    AuthenticatedIdentity authenticate(HttpExchange exchange) throws CompileException;
}
