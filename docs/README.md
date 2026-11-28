# 文档索引

首次运行可从[运行手册](runtime-guide.md)开始。核对赛题指标时，[参赛验收总览](../reports/competition-review/2026-11-29/README.md)列出受测版本、样本、测量条件和原始证据。

| 主题 | 文档入口 |
|---|---|
| 五项指标、受测版本与原始样本 | [参赛验收总览](../reports/competition-review/2026-11-29/README.md) |
| 当前状态与比赛要求 | [项目状态](project-status.md)、[赛题对照](delivery/competition-readiness.md) |
| 交付与当前验证 | [交付清单](delivery/README.md)、[10 月构建自测](delivery/self-test.md) |
| 项目结构与运行 | [目录说明](project-layout.md)、[运行手册](runtime-guide.md)、[演示说明](final-demo.md) |
| 编译器设计 | [架构](architecture/compiler-architecture.md)、[规则引擎](architecture/declarative-rule-engine.md)、[执行链路](end-to-end-execution.md) |
| 指标与扩展 | [注册表](architecture/stock-slot-registry-v1.md)、[函数语义](architecture/stock-slot-function-semantics-v1.md)、[插件开发](architecture/registry-plugin-guide.md) |
| 项目范围与验收 | [能力范围](project-capabilities-v1.md)、[冻结范围](phase1-data-indicator-scope-v1.md)、[项目验证](project-scoped-validation.md)、[字段规则](project-field-rules.md) |
| 测试与性能 | [自动测试](testing/automated-testing.md)、[编译性能](compiler-performance.md)、[配置扩展验收](testing/config-only-extension-acceptance.md) |
| 数据与环境 | [独立参考数据库](testing/independent-reference-duckdb.md)、[Doris 环境记录](recovered-doris-environment.md) |
| 历史规划与待办 | [正式验收问题路线图](正式验收问题解决路线图.md)、[10 月收尾清单](history/项目待优化清单.md)、[11 月工作台待办](history/workbench-optimization-backlog.md)、[早期 V1 路线图](history/V1_OPTIMIZATION_ROADMAP.md) |
| 历史依据与检查 | [9 月指标盘点工作簿](../reports/history/indicator-inventory/DSL指标数据契约.xlsx)、[早期自测](history/self-test-2026-08-09.md)、[缺陷检查](history/bug-review-2026-08-12.md)、[实施路线图](history/implementation-roadmap.md)、[比赛早期演进记录](competition/WEEK1_BASELINE.md) |

## 文档放在哪里

- `docs/architecture/` 收纳编译器架构、声明式规则、函数语义与指标注册说明。
- `docs/testing/` 收纳自动化测试、独立参考库重建和配置扩展验收方法。实测数字、执行记录及哈希清单归入 `reports/` 对应批次。
- `docs/delivery/` 收纳交付材料和赛题对照。`docs/history/` 保留历史规划和早期检查，`docs/competition/` 保留赛题早期的文法、映射和语义草案。
- `docs/` 根层保留运行手册、项目状态、冻结范围，以及脚本或历史报告使用的稳定入口。模块专用说明随代码放在各模块的 `README.md`。
