package com.acme.dorisdsl.stockslot;

import java.util.List;

/** Machine-readable execution contract for every emitted stock-slot window. */
public record StockSlotWindowContract(
        String function,
        List<String> partitionKeys,
        List<String> orderKeys,
        String unit,
        int lookback,
        String suspensionPolicy,
        String insufficientHistoryPolicy,
        String nullPolicy,
        boolean requireFullWindow
) {
    public StockSlotWindowContract {
        partitionKeys = List.copyOf(partitionKeys);
        orderKeys = List.copyOf(orderKeys);
        if (lookback < 0) throw new IllegalArgumentException("lookback must be non-negative (zero means unbounded)");
    }
}
