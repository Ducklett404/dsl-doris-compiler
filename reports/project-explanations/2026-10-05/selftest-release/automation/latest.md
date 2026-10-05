# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T15:50:55.2793749+08:00`
- Completed: `2026-10-05T15:54:17.3095862+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.213 s |
| scope-line-ending-regressions | PASS | 0.318 s |
| maven-all-tests | PASS | 49.872 s |
| executor-module-tests | PASS | 3.763 s |
| corpus-python-tests | PASS | 0.683 s |
| doris-data-contract-tests | PASS | 0.105 s |
| review-sql-result-regressions | PASS | 0.214 s |
| versioned-golden-contract-tests | PASS | 0.202 s |
| project-matrix-reference-tests | PASS | 0.154 s |
| project-window-boundaries | PASS | 6.083 s |
| project-rsi-tail-boundaries | PASS | 2.995 s |
| project-availability-explanations | PASS | 6.362 s |
| sentinel-window-boundaries | PASS | 3.805 s |
| historical-extrema-boundaries | PASS | 63.298 s |
| rolling-average-boundaries | PASS | 61.813 s |
| formal-compiler-p95 | PASS | 2.109 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
