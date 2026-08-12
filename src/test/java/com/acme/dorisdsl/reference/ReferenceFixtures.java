package com.acme.dorisdsl.reference;

import java.math.BigDecimal;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

final class ReferenceFixtures {
    private ReferenceFixtures() {}

    static ReferenceDataSet smallMarket() {
        List<LocalDate> days = new ArrayList<>();
        for (LocalDate date = LocalDate.parse("2026-06-15"); !date.isAfter(LocalDate.parse("2026-08-21")); date = date.plusDays(1))
            if (date.getDayOfWeek() != DayOfWeek.SATURDAY && date.getDayOfWeek() != DayOfWeek.SUNDAY) days.add(date);
        List<ReferenceDataSet.QuoteRow> quotes = new ArrayList<>();
        String[] symbols = {"AAA", "BBB", "CCC", "DDD"};
        for (int symbolIndex = 0; symbolIndex < symbols.length; symbolIndex++) {
            for (int day = 0; day < days.size(); day++) {
                if (symbols[symbolIndex].equals("CCC") && day == days.size() - 3) continue;
                BigDecimal close = decimal(8 + symbolIndex * 7 + day * (symbolIndex % 2 == 0 ? 0.45 : -0.08)
                        + (day % 6 == 0 ? 1.2 : 0));
                quotes.add(new ReferenceDataSet.QuoteRow(symbols[symbolIndex], days.get(day),
                        symbolIndex % 2 == 0 ? "SH" : "SZ", close.subtract(BigDecimal.ONE),
                        close.add(BigDecimal.ONE), close.subtract(BigDecimal.valueOf(2)), close,
                        decimal(1000 + symbolIndex * 500 + day * 17), decimal(100_000 + day * 1000),
                        decimal(0.01 + symbolIndex * 0.004 + day * 0.0001)));
            }
        }
        LocalDate farFuture = LocalDate.parse("9999-12-31");
        List<ReferenceDataSet.FinancialRow> financials = List.of(
                financial("AAA", "2025-12-31", "2026-03-20", "2026-07-20", "12", "0.14"),
                financial("AAA", "2026-03-31", "2026-07-20", "9999-12-31", "10", "0.18"),
                financial("BBB", "2025-12-31", "2026-03-25", "2026-08-20", "24", "0.09"),
                financial("BBB", "2026-06-30", "2026-08-20", "9999-12-31", "18", "0.16"),
                financial("CCC", "2025-12-31", "2026-04-01", "9999-12-31", "35", "0.21"),
                financial("DDD", "2025-12-31", "2026-03-15", "9999-12-31", "8", "0.05"));
        return new ReferenceDataSet(quotes, financials, days);
    }

    private static ReferenceDataSet.FinancialRow financial(String symbol, String report, String from,
                                                            String to, String pe, String roe) {
        return new ReferenceDataSet.FinancialRow(symbol, LocalDate.parse(report), LocalDate.parse(from),
                LocalDate.parse(to), new BigDecimal(pe), new BigDecimal(roe));
    }

    private static BigDecimal decimal(double value) { return BigDecimal.valueOf(value).setScale(6, java.math.RoundingMode.HALF_UP); }
}
