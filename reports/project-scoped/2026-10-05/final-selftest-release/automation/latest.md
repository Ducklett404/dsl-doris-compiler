# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T01:50:18.0277438+08:00`
- Completed: `2026-10-05T01:53:27.5209564+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.208 s |
| scope-line-ending-regressions | PASS | 0.289 s |
| maven-all-tests | PASS | 38.025 s |
| executor-module-tests | PASS | 3.778 s |
| corpus-python-tests | PASS | 0.72 s |
| doris-data-contract-tests | PASS | 0.095 s |
| review-sql-result-regressions | PASS | 0.186 s |
| versioned-golden-contract-tests | PASS | 0.177 s |
| sentinel-window-boundaries | PASS | 4.117 s |
| historical-extrema-boundaries | PASS | 72.351 s |
| rolling-average-boundaries | PASS | 67.631 s |
| formal-compiler-p95 | PASS | 1.885 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
