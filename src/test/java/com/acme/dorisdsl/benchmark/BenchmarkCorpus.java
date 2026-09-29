package com.acme.dorisdsl.benchmark;

public final class BenchmarkCorpus {
    public static final String SIMPLE = "SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 20";

    public static final String MEDIUM = """
            SCREEN ON 2026-08-07
            WHERE CLOSE > MA(CLOSE, 20) AND MARKET IN ['SH', 'SZ']
            ORDER BY TURNOVER_RATE DESC
            LIMIT 100
            """;

    public static final String COMPLEX = """
            SCREEN ON 2026-08-07
            WHERE PE_TTM() BETWEEN 0 AND 20
              AND ROE_TTM() >= 15%
              AND CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
              AND MARKET IN ['SH', 'SZ']
            ADJUST FORWARD
            ORDER BY TURNOVER_RATE DESC
            LIMIT 100
            """;

    public static final String ERROR = "SCREEN ON 2026-08-07 WHERE CLOSE > LIMIT 20";
    public static final String MALICIOUS_BOUNDARY = "SCREEN ON 2026-08-07 WHERE CLOSE > 1 " + " ".repeat(100_001);

    private BenchmarkCorpus() {}
}
