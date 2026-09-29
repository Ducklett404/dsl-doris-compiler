package com.acme.dorisdsl.stockslot;

public final class DorisExecutionException extends RuntimeException {
    public enum Category { DATA_UNAVAILABLE, TIMEOUT, DORIS_ERROR, SECURITY_LIMIT }

    private final Category category;

    public DorisExecutionException(Category category, String message) {
        super(message);
        this.category = category;
    }

    public DorisExecutionException(Category category, String message, Throwable cause) {
        super(message, cause);
        this.category = category;
    }

    public Category category() { return category; }
}
