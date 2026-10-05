# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T16:55:53.7181809+08:00`
- Completed: `2026-10-05T16:59:12.9260004+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.282 s |
| scope-line-ending-regressions | PASS | 0.316 s |
| maven-all-tests | PASS | 40.212 s |
| executor-module-tests | PASS | 3.646 s |
| corpus-python-tests | PASS | 0.686 s |
| doris-data-contract-tests | PASS | 0.111 s |
| review-sql-result-regressions | PASS | 0.258 s |
| versioned-golden-contract-tests | PASS | 0.205 s |
| project-matrix-reference-tests | PASS | 0.152 s |
| project-field-reference-tests | PASS | 0.303 s |
| project-window-boundaries | PASS | 6.008 s |
| project-rsi-tail-boundaries | PASS | 2.762 s |
| project-availability-explanations | PASS | 6.314 s |
| project-field-boundaries | PASS | 7.42 s |
| sentinel-window-boundaries | PASS | 4.177 s |
| historical-extrema-boundaries | PASS | 63.236 s |
| rolling-average-boundaries | PASS | 60.903 s |
| formal-compiler-p95 | PASS | 2.175 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
