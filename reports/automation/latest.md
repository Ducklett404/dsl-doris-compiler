# 自动化验收结果

- Suite: `automated-acceptance-v2-project-combinations`
- Started: `2026-10-10T00:17:13.4274776+08:00`
- Completed: `2026-10-10T00:25:33.7171788+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.2 s |
| scope-line-ending-regressions | PASS | 0.247 s |
| maven-all-tests | PASS | 26.043 s |
| executor-module-tests | PASS | 2.196 s |
| corpus-python-tests | PASS | 0.391 s |
| doris-data-contract-tests | PASS | 0.062 s |
| raw-csv-audit-regressions | PASS | 1.424 s |
| independent-reference-rebuild-contracts | PASS | 10.739 s |
| exact-eight-junit-report-contracts | PASS | 0.644 s |
| review-sql-result-regressions | PASS | 0.131 s |
| versioned-golden-contract-tests | PASS | 0.139 s |
| project-matrix-reference-tests | PASS | 0.107 s |
| project-field-reference-tests | PASS | 0.184 s |
| project-reference-loading-regressions | PASS | 4.723 s |
| project-combination-reference-tests | PASS | 0.391 s |
| project-numeric-comparison-contract-tests | PASS | 0.237 s |
| project-portable-decimal-adapter-tests | PASS | 0.648 s |
| project-be-memory-configuration-tests | PASS | 0.352 s |
| project-be-bounded-runtime-tests | PASS | 0.471 s |
| project-runtime-evidence-tests | PASS | 0.554 s |
| project-ma-precision-tests | PASS | 0.462 s |
| project-rsi-precision-tests | PASS | 7.326 s |
| project-rank-reference-tests | PASS | 0.235 s |
| project-acceptance-contract-tests | PASS | 1.667 s |
| project-performance-evidence-tests | PASS | 0.549 s |
| project-resource-stability-contract-tests | PASS | 0.208 s |
| project-delivery-integrity-tests | PASS | 1.359 s |
| project-window-boundaries | PASS | 11.193 s |
| project-rsi-tail-boundaries | PASS | 1.319 s |
| project-availability-explanations | PASS | 6.502 s |
| project-field-boundaries | PASS | 15.484 s |
| project-combination-boundaries | PASS | 206.713 s |
| project-rank-combination-boundaries | PASS | 115.638 s |
| sentinel-window-boundaries | PASS | 2.257 s |
| historical-extrema-boundaries | PASS | 37.762 s |
| rolling-average-boundaries | PASS | 40.24 s |
| formal-compiler-p95 | PASS | 1.468 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |
| project-real-acceptance | NOT_RUN | Use -WithProjectDoris with immutable source files, raw reference database and the explicit WSL/Doris environment |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
