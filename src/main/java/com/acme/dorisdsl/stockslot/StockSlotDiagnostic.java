package com.acme.dorisdsl.stockslot;

public record StockSlotDiagnostic(String severity, String code, String message, int line, int column) {}
