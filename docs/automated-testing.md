# 自动化测试与验收

## 覆盖矩阵

| 要求 | 自动化入口 | 失败条件 |
|---|---|---|
| 文法、类型、单位、枚举 | `StockSlotDslTest`、`StockSlotLanguageContractTest`、`StockSlotRegistryTest` | AST 类型、单位/倍率或枚举诊断不一致 |
| 12 类函数语义 | `StockSlotFunctionSqlTest`、`StockSlotFunctionEdgeCaseTest` | 正常、边界、空值、停牌、新股或错误输入任一失败 |
| 注入、越权、窗口和资源 | `StockSlotSecurityResourceTest`、`DorisExecutionPolicyTest` | 用户值进入 SQL、未知字段被接受或资源上限失效 |
| 停牌、新股、复权、空值、哨兵 | `MarketDataSemanticsContractTest`、`WindowSemanticsTest` | 语义视图公式、完整窗口策略或 `NULLIF` 变化 |
| 黄金 SQL 快照 | `GoldenSqlSnapshotTest` | SQL 与 bindings 的冻结 SHA-256 发生变化 |
| Doris 结果差分 | `scripts/accuracy/run_correctness.py`、`run_function_smoke.py` | 固定快照不匹配、结果集合/顺序不一致或盲测低于 95% |
| 19 年性能 | `benchmark-matrix` | 参考/优化结果不一致；保留 30 次冷热数据和 EXPLAIN/Profile |
| 编译性能 | `StockSlotCompilerPerformanceTest` | 正式复杂语料 5,000 次 P95 ≥ 50ms |
| 插件零核心改动 | `ConfigOnlyExtensionAcceptanceTest`、`verify-config-only-extension.ps1` | 配置扩展修改核心目录或向量不通过 |

## 一键执行

仅运行不依赖数据库的完整自动化套件：

```powershell
./scripts/test-all.ps1 -MavenExecutable mvn.cmd
```

连接已恢复且登记为 `VALIDATED` 的固定 Doris 快照，增加黄金结果差分和 12 类函数烟测：

```powershell
$env:DORIS_PASSWORD = '<只读验收账号密码>'
./scripts/test-all.ps1 -MavenExecutable mvn.cmd -WithDoris
```

增加完整 19 年冷热基准：

```powershell
./scripts/test-all.ps1 -MavenExecutable mvn.cmd -WithDoris -RunNineteenYearBenchmark
```

最后一种模式会进行 12 类查询 × 2 种缓存模式 × 30 次测量，并为 process-cold 样本重启
Doris 容器，共约 720 次重启。它适合发布前或专用夜间机器，不应放进普通 PR 的快速门禁。

脚本输出 `reports/automation/latest.json` 和 `latest.md`。没有提供 Doris 凭据时，数据库项目明确记录为
`NOT_RUN`，不会伪装为通过。普通 GitHub CI 执行全部离线合同；真实 Doris 差分通过带固定
快照标签的 Windows 自托管 runner 手工触发，并上传结果、SQL、EXPLAIN 和 Profile 证据。
