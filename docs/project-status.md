# 项目统一状态与证据口径

更新：2026-10-10。文档整理基线：`c67ca4dbd4a2bbc00b0b9ed0cf6e3e818137f138`；本轮仅更新配套说明。版本号、源码提交、JAR 哈希、配置和数据身份应分别记录，不能只用“V1 最新版”替代。

## 当前实现与验证

| 项目 | 统一结论 | 依据 |
|---|---|---|
| 源码 | `competition-v1.0` 已合入 `main`；应用版本 `0.1.0` | 构建配置与提交记录 |
| 执行范围 | DSL `stock-slot-v1`；冻结范围 `stock-slot-phase1-scope-v1.0.4`；注册表 `stock-slot-registry-v1.0.2` | [机器冻结清单](../config/acceptance/stock-slot-phase1-scope-v1.json)、[能力说明](project-capabilities-v1.md) |
| 本机 Java 重建 | 342 项：334 通过、8 项真实 Doris 测试跳过，0 失败／错误 | [2026-10-10 自测](delivery/self-test.md)、[机器记录](../reports/build/2026-10-10/build-verification.json) |
| 上传前项目复核 | 主模块334通过／8跳过、执行器3通过；428项Python覆盖，Bash跳过项已补跑；便携字段／组合／排名94／79／172组全部通过；正式DSL P95 0.2933ms | [当前自测](delivery/self-test.md)的上传前章节；真实Doris未运行 |
| 本机 JAR | SHA-256 `da6daa3e577f2fd9519c9fbf06d9307643794513c6c35e7ef804d4e58f7afe1d`；被测 Java 源码为合并提交 `8c202a1` | 本机重建报告；不代表其他 CI JAR |
| 字段、组合与排名矩阵 | 94／79／172 组便携验证本轮通过，检查脚本及便携 CI 入口已存在 | 本轮为合成夹具；真实官方数据上的本批通过数尚未取得 |
| 当前 JAR 真实项目验收 | 本轮重建未执行；没有新的完整真实项目通过结论 | 最新自测与本批报告状态；历史结果另列 |
| 正式验收 | 保留 BLOCKED 边界；最新历史正式门禁执行 0 组、准确率 null | [2026-10-05 门禁](../reports/project-fields/2026-10-05/formal-gate/result.json) |
| 交付 | 自动构建、便携验收、源码／JAR／证据打包与逐文件校验已实现 | [交付说明](delivery/README.md) |

已核验的远程基线 `c67ca4d`：[自动验收](https://github.com/Ducklett404/dsl-doris-compiler/actions/runs/37974690785)、[编译性能](https://github.com/Ducklett404/dsl-doris-compiler/actions/runs/37974690888)、[交付打包](https://github.com/Ducklett404/dsl-doris-compiler/actions/runs/37974690775)均成功。该结论不自动覆盖后续提交；最终提交应查看自身 Actions 和 manifest。本机中断或未完成的报告即使仍写 RUNNING，也不能计为通过。

## 历史证据的适用范围

| 批次 | 已记录的结果 | 使用限制 |
|---|---|---|
| 2026-10-05 逐字段 | 19 指标、94 次真实查询、403,104 个字段值核对通过 | 项目字段规则、当时 JAR；不是当前 v1.0.4 全量复测 |
| 2026-10-04 特征路线 | 28 组共 1,680 次计时；19 年代表查询热缓存 P95 比值 86.74x | 特征预计算成本不在查询计时内；不证明正式冷缓存、集群或最新 JAR |
| 正式 DSL 编译基准归档 | `reports/compiler-performance/latest.md` 记录缓存旁路 P95 0.206ms | 文件名 latest 不等于已绑定当前提交；以运行工件身份为准 |
| 2026-10-10 本机编译基准 | 复杂 SCREEN JMH P95 约 0.365ms | 兼容方言结果，不代替正式 DSL 的新批次门禁 |

历史报告入口：[逐字段](../reports/project-fields/2026-10-05/逐字段验证与自测报告.md)、[特征路线](../reports/official-route/2026-10-04/final/官方数据路线执行与自测报告.md)。原始测量文件保留原数字、日期和哈希。

## 状态术语

| 状态 | 含义 |
|---|---|
| `PASS_OFFLINE_REAL_NOT_RUN` | 本批便携校验通过，真实数据未运行 |
| `PROJECT_PASS_FORMAL_BLOCKED` | 本批完整真实项目验收通过，正式认可条件仍未满足 |
| `DIAGNOSTIC_PASS_FORMAL_BLOCKED` | 对应历史计算／性能诊断通过，不能升级为完整项目或正式通过 |
| `BLOCKED` | 对应验收前置门禁未满足；不是官方已作出失败判定 |
| `NOT_RUN` | 相关步骤未运行或缺环境 |
| `RUNNING` | 未取得完成结论，不能计为通过 |
| `FAIL` | 对应检查实际失败，需保留原因与修复后的新证据 |

## 下一步与文档维护

1. 以最终 JAR、v1.0.4 语义视图和新来源证书完成当前矩阵的真实验证，核对完整结果、顺序与缺失解释。
2. 根据评测认可范围补正确率分母、外部参考及最终性能证据；不以项目内部范围批准代替比赛认可。
3. 上传最终修改后检查该提交 CI，重新生成匹配身份的交付包；新文档也参与源码身份，旧验收包不能直接改名复用。

当前状态以本页为摘要；能力定义以机器清单／源码为准；是否通过以指定批次 JSON 为准。历史规划仅供追溯，未完成事项见 [收尾清单](项目待优化清单.md)，比赛材料见 [要求对照](delivery/competition-readiness.md)。
