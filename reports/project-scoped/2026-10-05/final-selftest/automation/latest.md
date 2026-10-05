# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T01:30:40.9470453+08:00`
- Completed: `2026-10-05T01:33:48.5369601+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.276 s |
| scope-line-ending-regressions | PASS | 0.317 s |
| maven-all-tests | PASS | 42.256 s |
| executor-module-tests | PASS | 3.92 s |
| corpus-python-tests | PASS | 0.858 s |
| doris-data-contract-tests | PASS | 0.11 s |
| review-sql-result-regressions | PASS | 0.194 s |
| versioned-golden-contract-tests | PASS | 0.198 s |
| sentinel-window-boundaries | PASS | 4.27 s |
| historical-extrema-boundaries | PASS | 67.56 s |
| rolling-average-boundaries | PASS | 65.702 s |
| formal-compiler-p95 | PASS | 1.901 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
