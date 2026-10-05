# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-10-05T07:15:20.3417450+08:00`
- Completed: `2026-10-05T07:18:08.5699008+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.21 s |
| scope-line-ending-regressions | PASS | 0.272 s |
| maven-all-tests | PASS | 37.799 s |
| executor-module-tests | PASS | 3.588 s |
| corpus-python-tests | PASS | 0.714 s |
| doris-data-contract-tests | PASS | 0.096 s |
| review-sql-result-regressions | PASS | 0.179 s |
| versioned-golden-contract-tests | PASS | 0.175 s |
| project-matrix-reference-tests | PASS | 0.163 s |
| sentinel-window-boundaries | PASS | 3.68 s |
| historical-extrema-boundaries | PASS | 61.16 s |
| rolling-average-boundaries | PASS | 58.325 s |
| formal-compiler-p95 | PASS | 1.837 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
