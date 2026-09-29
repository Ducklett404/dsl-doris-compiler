# Doris 执行与性能验收报告

## 结论

`stock-20060104-20260414-v1` 冻结快照上的正式 5 轮验收通过：

| 指标 | 实测 | 门槛 | 结果 |
|---|---:|---:|---|
| 编译链路 P95 | 1.6377 ms | < 50 ms | 通过 |
| 加速查询 P95 | 52.5262 ms | <= 10,000 ms | 通过 |
| 等价全周期基线 P95 | 4,070.1145 ms | 仅作对照 | - |
| P95 加速倍数 | 77.4873x | >= 10x | 通过 |
| 加速/基线结果 | 100 行及顺序完全一致 | 完全一致 | 通过 |

机器可读原始结果：[`doris-benchmark-long-cycle-v1.json`](doris-benchmark-long-cycle-v1.json)。

## 测试口径

- Doris：本机 Docker 单节点 `apache/doris:all-in-one-4.1.3`。
- 数据快照：`stock-20060104-20260414-v1`，状态必须为 `VALIDATED`。
- 明细行情：13,650,347 行，日期 `2006-01-04` 至 `2026-04-14`。
- 基准范围：沪市（`mktcode=1`）全部上述历史，按证券和交易日计算严格 60 个有效观测行的均价。
- 加速范围：同一验收日、同一市场、同一谓词、同一排序和 `LIMIT 100`，读取冻结特征表
  `newzl.stock_daily_features_v1`。
- 停牌/空值语义：剔除 `closePrice IS NULL` 的观测；不足 60 个有效交易行时结果为 `NULL`。
- SQL Cache：连接后执行 `SET enable_sql_cache=false`，避免把 Doris SQL 结果缓存当成结构优化。
- 运行方式：同一 JDBC 连接预热 1 轮、正式 5 轮；每轮分别执行加速 SQL和等价基线 SQL。
- 正确性门禁：逐轮比较 `(mktcode,tgtcode)` 结果及顺序，不一致时基准命令直接失败，不产生
  “通过”报告。
- 加速倍数：`基线 P95 / 加速查询 P95`。

## 可复现步骤

先执行真实表、语义视图、快照门禁和性能特征脚本；其中性能特征脚本可重复执行，唯一键会
覆盖同一快照键：

```text
data/doris/ddl/001_rebuild_tables.sql
data/doris/ddl/002_semantic_view.sql
data/doris/ddl/004_validation_gate.sql
data/doris/ddl/005_performance_features.sql
```

然后运行：

```powershell
java -jar target/dsl-doris-compiler.jar benchmark-doris `
  examples/performance-long-cycle.dsl `
  --user root --allow-empty-password --warmup 1 --iterations 5 `
  --timeout-seconds 10 --baseline-timeout-seconds 120 `
  -o reports/performance/doris-benchmark-long-cycle-v1.json
```

共享环境必须通过 `DORIS_PASSWORD` 提供非空密码，不应使用 `--allow-empty-password`。

## 实现边界

本次物化的是冻结验收日 `2026-04-14` 的 `MA60`，不是对任意指标、日期和窗口作虚假性能
承诺。非 60 日均线或非冻结日期继续使用历史明细计算；特征指标与明细/扩展表指标混用会被
显式拒绝。扩展覆盖时应先在注册表登记特征的新鲜度和字段契约，再生成并校验相应特征数据。
