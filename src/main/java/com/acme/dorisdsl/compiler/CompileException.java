package com.acme.dorisdsl.compiler;

public class CompileException extends RuntimeException {
    private final String code;
    private final int line;
    private final int column;
    private final String fragment;
    private final String suggestion;

    public CompileException(String code, String message, int line, int column) {
        this(code, message, line, column, "", "");
    }

    public CompileException(String code, String message, int line, int column, String fragment, String suggestion) {
        super(message);
        this.code = code;
        this.line = line;
        this.column = column;
        this.fragment = fragment == null ? "" : fragment;
        this.suggestion = suggestion == null ? "" : suggestion;
    }

    public String code() { return code; }
    public int line() { return line; }
    public int column() { return column; }
    public String fragment() { return fragment; }
    public String suggestion() { return suggestion; }
}
