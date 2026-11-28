# 测试报告与验收证据

评审本次参赛版本，先读 [2026-11-29 参赛验收总览](competition-review/2026-11-29/README.md)。五项赛题指标各有对应的受测版本、数据快照和测量口径。正式门禁在该快照上执行了 0 例，赛事正确率待评。[正式门禁记录](competition-review/2026-11-29/正式门禁.json)

## 复核 11 月 29 日验收

| 要核对的结果 | 从哪里开始 | 如何复核 |
|---|---|---|
| 4、8 并发的正确返回数、耗时与吞吐 | [单节点工作台并发验收](competition-review/2026-11-29/concurrency/验收报告.md) | [并发样本](competition-review/2026-11-29/concurrency/accepted/) · [复现命令](competition-review/2026-11-29/concurrency/复现说明.md) |
| 112 条复杂 DSL 的完整名单与 10 秒时限 | [跨证券取值与窗口组合](competition-review/2026-11-29/lookup-window/验收报告.md) | [逐次判定](competition-review/2026-11-29/lookup-window/samples.jsonl) · [复现命令](competition-review/2026-11-29/lookup-window/复现说明.md) |
| 随包版的长周期加速比、编译 P95、配置扩展及失败用例 | [随包版原生 Doris 验收](competition-review/2026-11-29/验收报告.md) | [证据索引](competition-review/2026-11-29/证据索引.md) · [复现命令](competition-review/2026-11-29/复现说明.md) |

## 查找历史报告

以下按读者要核查的问题，直接链接到各归档目录的报告或构建记录。复现历史数值时，使用对应提交、JAR 和数据快照。在当前版本试跑早期 Doris 性能报告的命令时，示例路径已由 `examples/performance-long-cycle.dsl` 移至 [examples/stock-slot/performance-long-cycle.dsl](../examples/stock-slot/performance-long-cycle.dsl)，现行运行参数见[执行手册](../docs/end-to-end-execution.md)。独立归档的 9 月自测与 10 月构建记录也可[按日期浏览](history/README.md)。

### 数据、正确性与诊断

| 核查问题 | 历史报告 |
|---|---|
| 原始行情包含哪些字段、缺失和关联问题？ | [三份行情数据说明](data-inspection/2026-10-04/数据说明与用途.md) · [官方数据复验与剩余问题](official-acceptance/2026-10-04/a0f7260/官方数据复验与剩余问题.md) |
| 哪些能力有数据来源，如何冻结验收范围？ | [冻结范围校验](scope/phase1-scope-validation.md) · [按能力验收](project-scoped/2026-10-05/分能力验收与自测报告.md) |
| 字段和组合查询如何逐项核对？ | [内部黄金集](accuracy/stock-slot-executable-v1/REPORT.md) · [逐字段核对](project-fields/2026-10-05/逐字段验证与自测报告.md) · [扩展矩阵](project-expanded/2026-10-05/扩展官方数据验证与自测报告.md) |
| 窗口为何返回 NULL，阈值相等时如何处理？ | [窗口缺失原因与样本](project-explanations/2026-10-05/窗口缺失解释与自测报告.md) · [数值精度回归](precision-fix/2026-10-04/数值问题修复与自测报告.md) |

### 编译与查询性能

| 核查问题 | 历史报告 |
|---|---|
| 如何测量编译延迟与 Doris 执行耗时？ | [正式 DSL 编译基准](compiler-performance/latest.md) · [Doris 性能报告](performance/PERFORMANCE_REPORT.md) · [基准矩阵自测与适用条件](benchmark-matrix/SELF_TEST_REPORT.md) |
| 明细扫描、聚合和预计算各花多少时间？ | [热缓存性能诊断](performance-diagnostic/2026-10-04/hot-30/性能诊断与下一步.md) · [历史极值聚合优化](history-optimization/2026-10-04/历史极值优化与自测报告.md) · [历史极值特征](history-features/2026-10-04/历史极值特征与自测报告.md) |
| 窗口加速在官方数据上怎样验证？ | [官方数据执行路线](official-route/2026-10-04/final/官方数据路线执行与自测报告.md) · [窗口性能实测](project-performance/2026-10-05/窗口性能优化与自测报告.md) |

### 语言、执行与交付

| 核查问题 | 历史报告 |
|---|---|
| DSL 和函数如何转换为 SQL？ | [解析与 AST 自测](stock-slot-v1/SELF_TEST_REPORT.md) · [注册表与类型系统](stock-slot-v1/REGISTRY_SELF_TEST_REPORT.md) · [函数 SQL 语义](history/stock-slot-functions-v1/SELF_TEST_REPORT.md) |
| 哪些业务规则支持由配置接入？ | [规则引擎自测](history/rules/SELF_TEST_REPORT.md) · [零核心代码改动的扩展测试](config-only-extensions/SELF_TEST_REPORT.md) |
| 如何查看端到端执行、演示产物与当次交付？ | [端到端自测](e2e/SELF_TEST_REPORT.md) · [演示编译记录](demo/latest.md) · [阶段交付报告](final/FINAL_DELIVERY.md) · [10 月 10 日构建验证](history/build/2026-10-10/build-verification.json) |
| 如何追溯 10 月 4 日的发现和修复？ | [代码检查](code-review/2026-10-04/代码检查报告.md) · [修复自测](code-review/2026-10-04/修复与自测报告.md) · [路线实施](route-implementation/2026-10-04/路线实施与自测报告.md) · [后续自测](continuation/2026-10-04/继续推进与自测报告.md) |
