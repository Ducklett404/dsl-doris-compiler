# 端到端 Doris 执行闭环

统一状态见 [项目状态](project-status.md)。以下说明执行机制，不表示当前快照已经通过正式门禁；当前演示入口见 [演示说明](final-demo.md)。

## 执行顺序

```text
DSL
  → stock-slot-v1 解析/语义/lowering
  → 仅 SELECT 的参数化 SQL
  → 等待单连接执行槽（有超时）
  → 正式 VALIDATED 门禁，或显式可信本地项目来源证书
  → 参数化 EXPLAIN 与估算扫描行门禁
  → Doris Workload Policy 实际扫描量/时间门禁
  → 参数化 PreparedStatement
  → 股票列表 + 分阶段计时 + 指纹 + EXPLAIN + Profile 摘要
  → JSON 或 Markdown
```

客户端扫描量门禁是执行前保护，数据库 Workload Policy 是执行中保护。两者不能互相替代。
如果 EXPLAIN 不提供可识别的行数估算，受控执行会拒绝查询，而不是绕过门禁。

## 安全约束

- 启动时通过 `SHOW GRANTS` 检查执行身份，发现管理、授权、装载、建表、修改或删除权限即拒绝。
- 只执行编译器产生的单条 `SELECT/WITH`，拒绝注释、多语句及非查询语句。
- DSL 字面量只进入 JDBC bindings；EXPLAIN 和正式执行使用相同 bindings。
- 查询超时、估算扫描行、执行内存、排队等待和最大返回行数均有服务端上限。
- 默认严格入口要求快照在基础来源所在数据库的 `data_snapshot_registry` 中唯一且为 `VALIDATED`（默认 `newzl`）。
- 显式可信本地 `--project-validation` 使用按查询依赖的项目来源证书；不登记正式快照，HTTP 请求不能自行选择证书。详见 [项目验证](project-scoped-validation.md)。
- SQL 指纹基于规范化的带 `?` SQL，不包含用户参数。

## 时间口径

- `compileMillis`：DSL 到 SQL 编译。
- `queueMillis`：等待本服务单连接执行槽；不是伪造的 Doris 内部排队时间。
- `explainMillis`：快照确认后的 EXPLAIN 及扫描量门禁。
- `dorisExecutionMillis`：`executeQuery` 提交到结果集可读取。
- `returnMillis`：读取、限流和构造返回股票列表。
- `totalMillis`：从收到执行调用到 Profile 摘要采集完成。

Doris 内部排队/算子信息由 Query Profile 负责。Profile 异步生成或无权限时，返回对象明确
标记 `available=false` 和原因，不填造数值。

## HTTP 错误契约

| 类别 | HTTP | 例子 |
|---|---:|---|
| `syntax_error` | 400 | 文法不合法、缺少 DSL |
| `semantic_error` | 422 | 指标无映射、日期/窗口不支持 |
| `security_limit` | 429 | 非只读账号、扫描量或排队超限 |
| `doris_error` | 502 | FE/BE 或 SQL 执行错误 |
| `data_unavailable` | 503 | 快照未登记或未验证 |
| `timeout` | 504 | 排队或 Doris 查询超时 |

## 自测

```powershell
mvn test

$env:DORIS_PASSWORD = '<只读账号密码>'
java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql `
  examples/performance-long-cycle.dsl --user dsl_runtime_reader `
  --format json -o reports/e2e/doris-execution.json

java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql `
  examples/performance-long-cycle.dsl --user dsl_runtime_reader `
  --format markdown -o reports/e2e/doris-execution.md
```
