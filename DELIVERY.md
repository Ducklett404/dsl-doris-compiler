# 固定交付清单

| 交付物 | 固定入口 | 状态 |
|---|---|---|
| 一键建表、导入、校验、登记快照 | `scripts/doris/setup-load-validate.ps1` | 已完成 |
| 一键构建、测试和启动 | `scripts/build-test-start.ps1` | 已完成 |
| CLI、HTTP、Docker 运行说明 | `docs/runtime-guide.md` | 已完成 |
| 文法、AST、类型、规则、计划、访问路径 | `docs/compiler-architecture.md` | 已完成 |
| 指标注册与插件开发 | `docs/registry-plugin-guide.md` | 已完成 |
| 首期数据指标范围冻结书 | `docs/phase1-data-indicator-scope-v1.md`、`config/acceptance/stock-slot-phase1-scope-v1.json` | 已直接批准并冻结，无需签字 |
| 正确率报告 | `reports/accuracy/stock-slot-executable-v1/REPORT.md` | 固定快照历史实测 |
| 编译性能报告 | `reports/compiler-performance/latest.md` | 本轮实测 |
| Doris 性能及 EXPLAIN/Profile 证据 | `reports/performance/`、`reports/benchmark-matrix/evidence/` | 已有历史实测；本轮矩阵未运行 |
| 自动化测试样例和结果 | `src/test/`、`reports/automation/latest.md` | 147/147 通过 |
| Markdown 最终编译和查询结果 | `reports/final/compilation-and-query.md` | 可重复生成 |
| 最终七步演示脚本和报告 | `scripts/run-final-demo.ps1`、`reports/demo/latest.md` | 脚本已自测；实时 Doris 待环境复测 |

统一验收流程：先运行 `scripts/test-all.ps1`，需要真实数据库时追加 `-WithDoris`，发布前专用
机器追加 `-RunNineteenYearBenchmark`。最终结果用 `scripts/generate-final-output.ps1` 重新生成。

交付物中的历史 Doris 数字保留执行日期、快照和原始 JSON，不得作为当前环境复测结果冒用。
