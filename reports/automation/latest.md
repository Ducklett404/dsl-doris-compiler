# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-04T19:31:06.5852965+08:00`
- Completed: `2026-10-04T19:34:04.5302662+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.221 s |
| scope-line-ending-regressions | PASS | 0.279 s |
| maven-all-tests | PASS | 37.786 s |
| executor-module-tests | PASS | 3.756 s |
| corpus-python-tests | PASS | 0.832 s |
| doris-data-contract-tests | PASS | 0.099 s |
| review-sql-result-regressions | PASS | 0.177 s |
| versioned-golden-contract-tests | PASS | 0.181 s |
| sentinel-window-boundaries | PASS | 3.94 s |
| historical-extrema-boundaries | PASS | 65.754 s |
| rolling-average-boundaries | PASS | 63.158 s |
| formal-compiler-p95 | PASS | 1.726 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
