package com.acme.dorisdsl.reference;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

public record ReferenceDataSet(List<QuoteRow> quotes, List<FinancialRow> financials,
                               List<LocalDate> tradingDays) {
    public ReferenceDataSet {
        quotes = quotes.stream().sorted(Comparator.comparing(QuoteRow::symbol).thenComparing(QuoteRow::tradeDate)).toList();
        financials = financials.stream().sorted(Comparator.comparing(FinancialRow::symbol)
                .thenComparing(FinancialRow::visibleFrom)).toList();
        tradingDays = tradingDays.stream().sorted().distinct().toList();
    }

    public record QuoteRow(String symbol, LocalDate tradeDate, String market, BigDecimal open,
                           BigDecimal high, BigDecimal low, BigDecimal close, BigDecimal volume,
                           BigDecimal amount, BigDecimal turnoverRate) {
        public Map<String, Object> fields() {
            return Map.of("SYMBOL", symbol, "TRADE_DATE", tradeDate, "MARKET", market,
                    "OPEN", open, "HIGH", high, "LOW", low, "CLOSE", close,
                    "VOLUME", volume, "AMOUNT", amount, "TURNOVER_RATE", turnoverRate);
        }
    }

    public record FinancialRow(String symbol, LocalDate reportPeriod, LocalDate visibleFrom,
                               LocalDate visibleTo, BigDecimal peTtm, BigDecimal roeTtm) {
        public BigDecimal value(String function) {
            return switch (function) { case "PE_TTM" -> peTtm; case "ROE_TTM" -> roeTtm;
                default -> throw new IllegalArgumentException("Unknown financial metric: " + function); };
        }
    }
}
