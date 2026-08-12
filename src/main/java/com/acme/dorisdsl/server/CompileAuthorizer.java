package com.acme.dorisdsl.server;

import com.acme.dorisdsl.compiler.CompileException;

import java.util.Map;

@FunctionalInterface
public interface CompileAuthorizer {
    CompileAuthorizer ALLOW_ALL = (context, dsl) -> { };

    /** Called for every request before compilation cache lookup. */
    void authorize(Map<String, Object> context, String dsl) throws CompileException;
}
