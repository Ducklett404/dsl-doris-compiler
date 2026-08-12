package com.acme.dorisdsl.plan;

import java.util.List;

public record WindowSpec(
        String alias,
        String function,
        int length,
        Unit unit,
        List<String> partitionKeys,
        List<String> orderKeys,
        NullPolicy nullPolicy,
        boolean requireFullWindow
) {
    public WindowSpec {
        partitionKeys = List.copyOf(partitionKeys);
        orderKeys = List.copyOf(orderKeys);
    }

    public enum Unit { TRADING_DAY }
    public enum NullPolicy { STRICT_FULL_WINDOW, ALLOW_PARTIAL_WINDOW }

    public int requiredLookbackTradingDays() {
        return switch (function) {
            case "MA" -> requireFullWindow ? length : Math.max(1, length);
            case "LAG" -> length;
            default -> length;
        };
    }
}
