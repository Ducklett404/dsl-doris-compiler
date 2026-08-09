package com.acme.dorisdsl.compiler;

public class CompileException extends RuntimeException {
    private final String code;
    private final int line;
    private final int column;

    public CompileException(String code, String message, int line, int column) {
        super(message);
        this.code = code;
        this.line = line;
        this.column = column;
    }

    public String code() { return code; }
    public int line() { return line; }
    public int column() { return column; }
}
