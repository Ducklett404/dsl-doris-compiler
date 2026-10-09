# 项目演示与正式七步演示


更新：2026-10-10。当前数据没有满足正式 VALIDATED 门禁，默认 Live 七步演示不能作为已成功运行的承诺。统一状态见 [项目状态](project-status.md)。

## 当前可用的展示顺序

1. 运行 `java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/project-basic.dsl --format json`，展示 AST、计划、SQL 和绑定参数。
2. 运行 `java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/final-demo-complex.dsl --format sql`，展示复杂 DSL 的 SQL；编译成功不表示数据库结果已验证。
3. 无数据库时运行能力说明中的便携验收，展示本批 `PASS_OFFLINE_REAL_NOT_RUN` 和逐例结果。
4. 有真实环境时运行 `run_project_acceptance.py --with-doris --restart` 的完整命令，生成新来源证书；随后按 [能力说明](project-capabilities-v1.md)的执行示例展示当前股票结果和缺失解释。
5. 只展示实际取得的新批次性能；历史数据单独标注日期、JAR 和缓存状态。最后展示扩展配置、当前自测与交付 manifest。

上述步骤不要求把项目来源证书改为正式快照登记；完整真实命令和资源限制见能力说明。以下保留正式条件具备后的七步脚本及历史证据检查模式。


固定入口为 `scripts/run-final-demo.ps1`，默认使用实时 Doris；实时模式不会自动回退到历史数据，
缺少密码、快照或数据库连接时直接失败，防止把旧证据误当成本轮结果。

## 正式演示

先启动 Doris，确认 `stock-20060104-20260414-v1` 已登记为 `VALIDATED`，并在同一个
PowerShell 进程设置只读账号密码：

```powershell
$env:DORIS_PASSWORD = '<只读账号密码>'
& .\scripts\run-final-demo.ps1 `
  -DorisMode Live `
  -MavenExecutable 'mvn.cmd'
```

脚本依次执行：

1. 编译 `examples/final-demo-complex.dsl`；
2. 输出 Typed AST、真实规范化轨迹、逻辑计划、绑定参数和 SQL；
3. 使用只读账号在固定快照执行并显示股票；
4. 对相同结果集执行优化路径与全表扫描基线；
5. 强制检查优化 P95 不超过 10 秒、加速不低于 10 倍；
6. 加载一个仅含单指标的配置，执行 CI 白名单门禁并比较核心源码前后 SHA-256；
7. 刷新 5,000 次编译基准并显示黄金集正确率。

最终文件：

- `reports/demo/latest.md`：可直接展示的 Markdown；
- `reports/demo/latest.json`：机器可读摘要；
- `reports/demo/formal-complex-compilation.json`：正式 DSL 编译产物；
- `reports/demo/live-execution.json`、`live-execution.md`：本轮 Doris 结果；
- `reports/demo/live-performance.json`：本轮基线与优化结果。

## 无数据库环境下检查演示脚本

```powershell
& .\scripts\run-final-demo.ps1 `
  -DorisMode HistoricalEvidence `
  -SkipBuild
```

该模式只验证编译、报告生成、配置扩展、门禁和历史证据读取。报告会把实时 Doris 步骤标记
为 `NOT_RUN`，并注明历史股票样例不是复杂演示 DSL 的本轮执行结果。
