# 赛题要求、实现与提交证据对照

2026 年 11 月 29 日已归档两个批次。五项指标的数值、测试范围、正式门禁状态及逐次证据可从验收总览核对。[验收总览](../../reports/competition-review/2026-11-29/README.md)

## 评审材料选择

- **演示编译和选股。** 项目提供 AST、参数化 Doris SQL 和只读执行入口。随包版保留了在真实行情上生成的 Markdown 结果。[执行样例](../../reports/competition-review/2026-11-29/选股结果样例.md) · [运行手册](../runtime-guide.md)
- **回答复杂查询的正确性和时限。** 使用跨证券窗口修订版的 112 条固定用例、21 条困难组合重复测试和新增边界用例。并发请求的排队失败单列。[修订版专项报告](../../reports/competition-review/2026-11-29/lookup-window/验收报告.md)
- **回答长周期加速、编译延迟和配置扩展。** 使用随包版的双基线计时、缓存旁路编译样本与同一 JAR 的配置扩展示例，并注明其工件身份。[随包版报告](../../reports/competition-review/2026-11-29/验收报告.md)
- **说明官方验收状态。** 当前项目测试按冻结语义和来源证书执行；正式门禁执行 0 例，准确率为空。[门禁记录](../../reports/competition-review/2026-11-29/正式门禁.json)

## 提交附件建议

| 附件 | 入口／生成方式 |
|---|---|
| 源码与可执行 JAR | 对应提交的 `project-delivery` 工作流成功后可下载 Artifacts，并按 manifest 和 SHA-256 核对身份 |
| 运行与恢复说明 | [运行手册](../runtime-guide.md)、[能力与恢复](../project-capabilities-v1.md) |
| 核心模块说明 | [编译架构](../architecture/compiler-architecture.md)、[执行链路](../end-to-end-execution.md)、[扩展契约](../testing/config-only-extension-acceptance.md) |
| 支持范围与限制 | [冻结范围](../phase1-data-indicator-scope-v1.md)、[能力表](../project-capabilities-v1.md) |
| 示例与展示 | `examples/project-basic.dsl`、`examples/final-demo-complex.dsl`；[演示步骤](../final-demo.md) |
| 实测结果与复核 | [验收总览及复核命令](../../reports/competition-review/2026-11-29/README.md)、[专项逐次样本](../../reports/competition-review/2026-11-29/lookup-window/samples.jsonl)、[SQL 与参数](../../reports/competition-review/2026-11-29/lookup-window/plans.json) |
| 性能说明 | 最终 JAR 编译门禁；同批真实查询计时、基线／优化结果、缓存状态和特征成本 |
| 数据与异常披露 | 原始 manifest、单位假设、未关联衍生行、价格警告、缺失来源及排除项 |

引用测量结果时请同时注明 JAR、数据快照、测试入口和分母。赛事正式正确率待认可快照完成门禁后计算。
