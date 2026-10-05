# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T09:45:05.8228737+08:00`
- Completed: `2026-10-05T09:48:03.3432324+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.208 s |
| scope-line-ending-regressions | PASS | 0.255 s |
| maven-all-tests | PASS | 37.397 s |
| executor-module-tests | PASS | 3.59 s |
| corpus-python-tests | PASS | 0.716 s |
| doris-data-contract-tests | PASS | 0.106 s |
| review-sql-result-regressions | PASS | 0.242 s |
| versioned-golden-contract-tests | PASS | 0.213 s |
| project-matrix-reference-tests | PASS | 0.173 s |
| project-window-boundaries | PASS | 6.188 s |
| project-rsi-tail-boundaries | PASS | 2.758 s |
| sentinel-window-boundaries | PASS | 3.746 s |
| historical-extrema-boundaries | PASS | 60.989 s |
| rolling-average-boundaries | PASS | 59.026 s |
| formal-compiler-p95 | PASS | 1.876 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
