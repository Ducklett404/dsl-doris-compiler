# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-04T23:45:45.9922836+08:00`
- Completed: `2026-10-04T23:48:43.8301875+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.212 s |
| scope-line-ending-regressions | PASS | 0.269 s |
| maven-all-tests | PASS | 36.73 s |
| executor-module-tests | PASS | 3.923 s |
| corpus-python-tests | PASS | 0.693 s |
| doris-data-contract-tests | PASS | 0.096 s |
| review-sql-result-regressions | PASS | 0.174 s |
| versioned-golden-contract-tests | PASS | 0.175 s |
| sentinel-window-boundaries | PASS | 4.169 s |
| historical-extrema-boundaries | PASS | 66.258 s |
| rolling-average-boundaries | PASS | 63.391 s |
| formal-compiler-p95 | PASS | 1.72 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
