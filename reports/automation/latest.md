# 自动化验收结果

- Suite: `automated-acceptance-v1`
- Started: `2026-09-29T12:39:22.5064361+08:00`
- Completed: `2026-09-29T12:39:37.4038790+08:00`

| Check | Status | Detail |
|---|---|---|
| phase1-scope-freeze | PASS | 0.154 s |
| maven-all-tests | PASS | 13.629 s |
| formal-compiler-p95 | PASS | 1.098 s |
| doris-golden-result-differential | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-12-function-smoke | NOT_RUN | Use -WithDoris and set DORIS_PASSWORD |
| doris-19-year-matrix | NOT_RUN | Use -RunNineteenYearBenchmark (long-running: 720 container restarts) |

> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。
