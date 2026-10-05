# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T15:57:01.4173846+08:00`
- Completed: `2026-10-05T16:00:20.9874393+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.217 s |
| scope-line-ending-regressions | PASS | 0.282 s |
| maven-all-tests | PASS | 49.497 s |
| executor-module-tests | PASS | 3.64 s |
| corpus-python-tests | PASS | 0.679 s |
| doris-data-contract-tests | PASS | 0.095 s |
| review-sql-result-regressions | PASS | 0.185 s |
| versioned-golden-contract-tests | PASS | 0.195 s |
| project-matrix-reference-tests | PASS | 0.165 s |
| project-window-boundaries | PASS | 5.741 s |
| project-rsi-tail-boundaries | PASS | 2.806 s |
| project-availability-explanations | PASS | 6.678 s |
| sentinel-window-boundaries | PASS | 3.814 s |
| historical-extrema-boundaries | PASS | 62.56 s |
| rolling-average-boundaries | PASS | 60.894 s |
| formal-compiler-p95 | PASS | 2.085 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
