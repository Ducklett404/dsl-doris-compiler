# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T06:59:30.7533473+08:00`
- Completed: `2026-10-05T07:02:20.1274669+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.351 s |
| scope-line-ending-regressions | PASS | 0.333 s |
| maven-all-tests | PASS | 38.481 s |
| executor-module-tests | PASS | 3.772 s |
| corpus-python-tests | PASS | 1.141 s |
| doris-data-contract-tests | PASS | 0.168 s |
| review-sql-result-regressions | PASS | 0.211 s |
| versioned-golden-contract-tests | PASS | 0.236 s |
| sentinel-window-boundaries | PASS | 3.694 s |
| historical-extrema-boundaries | PASS | 60.722 s |
| rolling-average-boundaries | PASS | 58.421 s |
| formal-compiler-p95 | PASS | 1.815 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
