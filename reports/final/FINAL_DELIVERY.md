# 项目最终交付报告

## 验收摘要

| 项目 | 结果 | 证据 |
|---|---|---|
| 完整自动化回归 | PASS：147/147 | `reports/automation/latest.md` |
| 正式复杂 DSL 编译 | PASS：5,000 次，P95 < 50 ms | `reports/compiler-performance/latest.md`（以最新运行值为准） |
| 黄金 SQL 快照 | PASS：5/5 | `GoldenSqlSnapshotTest` |
| 插件零核心改动 | PASS：3 类 | `reports/config-only-extensions/SELF_TEST_REPORT.md` |
| 三层黄金集正确率 | HISTORICAL PASS：24/24，100% | 2026-09-18 固定快照报告 |
| 19 年 MA60 加速 | HISTORICAL PASS：P95 77.4873x | 2026-09-18 固定快照报告 |
| 本轮 Doris 差分/完整冷热矩阵 | NOT_RUN | Docker daemon 未运行且无 `DORIS_PASSWORD` |

`HISTORICAL PASS` 是仓库中保留的固定快照原始证据，不替代本轮复测。`NOT_RUN` 不计为通过。

## 固定输出

| 输出 | 路径 |
|---|---|
| 正确率 Markdown/JSON | `reports/accuracy/stock-slot-executable-v1/` |
| 编译性能 Markdown/JSON | `reports/compiler-performance/` |
| Doris 性能 Markdown/JSON | `reports/performance/` |
| EXPLAIN/Profile 矩阵 | `reports/benchmark-matrix/evidence/` |
| 自动化汇总 | `reports/automation/` |
| 编译和查询结果 | `reports/final/compilation-and-query.md` |

## 复现顺序

1. `scripts/doris/setup-load-validate.ps1`：装载并登记固定快照。
2. `scripts/test-all.ps1 -WithDoris`：执行测试和结果差分。
3. 发布前按需追加 `-RunNineteenYearBenchmark`。
4. `scripts/generate-final-output.ps1`：生成最终 Markdown 表格。
