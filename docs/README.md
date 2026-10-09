# 文档索引

项目说明统一在 `docs/`，测量结果与验收证据放在 `reports/`。从 [交付清单](delivery/README.md)、[当前自测报告](delivery/self-test.md)和[目录说明](project-layout.md)开始阅读。

| 主题 | 文档入口 |
|---|---|
| 交付与当前验证 | [交付清单](delivery/README.md)、[当前自测](delivery/self-test.md) |
| 项目结构与运行 | [目录说明](project-layout.md)、[运行手册](runtime-guide.md)、[演示说明](final-demo.md) |
| 编译器设计 | [架构](compiler-architecture.md)、[规则引擎](declarative-rule-engine.md)、[执行链路](end-to-end-execution.md) |
| 指标与扩展 | [注册表](stock-slot-registry-v1.md)、[函数语义](stock-slot-function-semantics-v1.md)、[插件开发](registry-plugin-guide.md) |
| 项目范围与验收 | [能力范围](project-capabilities-v1.md)、[冻结范围](phase1-data-indicator-scope-v1.md)、[项目验证](project-scoped-validation.md)、[字段规则](project-field-rules.md) |
| 测试与性能 | [自动测试](automated-testing.md)、[编译性能](compiler-performance.md)、[配置扩展验收](config-only-extension-acceptance.md) |
| 数据与环境 | [独立参考数据库](independent-reference-duckdb.md)、[Doris 环境记录](recovered-doris-environment.md) |
| 后续事项 | [正式验收问题](正式验收问题解决路线图.md)、[项目待优化清单](项目待优化清单.md)、[V1 优化规划](V1_OPTIMIZATION_ROADMAP.md) |
| 历史记录 | [早期自测](history/self-test-2026-08-09.md)、[缺陷检查](history/bug-review-2026-08-12.md)、[实施路线图](history/implementation-roadmap.md)、[比赛演进记录](competition/WEEK1_BASELINE.md) |

## 文件归放约定

- 根目录只保留 `README.md` 项目入口与 `AGENTS.md` 自动工具协作约定。交付说明、自测说明不再放在根目录。
- 当前交付材料放在 `docs/delivery/`，历史规划与检查说明放在 `docs/history/`。
- 运行手册、架构和语义说明放在 `docs/`；该索引按主题组织阅读入口。
- 实测报告留在 `reports/` 对应批次，和同批 JSON、SQL、哈希证据一起保存。
- `executor-doris/`、`data/doris/`、`accuracy/` 等模块自己的 `README.md` 留在模块目录，便于单独使用。
- 本机日志、临时验证和构建记录放在 `build/`；编译输出放在 `target/`。
