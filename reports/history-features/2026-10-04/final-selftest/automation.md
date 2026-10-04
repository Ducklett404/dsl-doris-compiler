# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-04T18:41:57.3137889+08:00`
- Completed: `2026-10-04T18:43:56.8016874+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.28 s |
| scope-line-ending-regressions | PASS | 0.331 s |
| maven-all-tests | PASS | 39.64 s |
| executor-module-tests | PASS | 3.794 s |
| corpus-python-tests | PASS | 0.759 s |
| doris-data-contract-tests | PASS | 0.131 s |
| review-sql-result-regressions | PASS | 0.206 s |
| versioned-golden-contract-tests | PASS | 0.211 s |
| sentinel-window-boundaries | PASS | 4.382 s |
| historical-extrema-boundaries | PASS | 67.781 s |
| formal-compiler-p95 | PASS | 1.93 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
