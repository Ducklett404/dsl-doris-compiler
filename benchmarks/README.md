# Doris 基准矩阵

矩阵文件 [`doris-matrix-v1.json`](doris-matrix-v1.json) 固定 12 个案例，覆盖：

- 单日简单过滤；
- 多指标跨基础表/扩展表过滤；
- 20/60/120/250 日窗口；
- 交叉、创新高、创新低、连续出现和排名；
- 2006-01-04 至 2026-04-14 的完整历史窗口。

每个 DSL 使用同一编译器生成两个访问路径：

- `FULL_SCAN_REFERENCE`：禁用特征表；单日查询还使用不可分区裁剪的等价日期表达式。
- `OPTIMIZED`：允许注册表声明的特征表、直接日期谓词和后续新增的安全访问路径。

两条查询共享 DSL、快照、bindings、过滤条件、排序和返回上限。每次测量都逐行比较结果及
顺序；任意不一致会立即终止，不会输出加速结论。

## 冷热缓存口径

- `HOT`：同一 Doris 进程和 JDBC 会话，先各预热一次，再交替执行参考/优化查询 30 次。
- `PROCESS_COLD`：每一条被计时的 SQL 前都执行 `docker restart doris`，等待 Doris 恢复后使用
  新连接。它会清除 FE/BE 进程内的 Query Cache 和 Page Cache；报告明确说明不声称清除
  Windows/Linux 主机 OS Page Cache。
- 两种模式都关闭 SQL Cache 和 Query Cache，避免把最终结果缓存命中误算为结构优化。

Doris 官方说明 Query Cache 位于 BE 内存并在 BE 重启后清空，因此进程重启是本项目当前
单节点 Docker 环境可审计、可重复的冷缓存边界。完整 12 类、两种模式、30 次测量需要
重启容器 720 次，耗时可能达到数小时，运行期间不要装载或修改快照。

## 执行

```powershell
$env:DORIS_PASSWORD = '<基准只读账号密码>'
java -jar target/dsl-doris-compiler.jar benchmark-matrix `
  --matrix benchmarks/doris-matrix-v1.json `
  --user dsl_benchmark_reader `
  --iterations 30 `
  --cold-restart-container doris `
  --evidence-dir reports/benchmark-matrix/evidence `
  --json-output reports/benchmark-matrix/report.json `
  --markdown-output reports/benchmark-matrix/report.md
```

程序拒绝少于 30 次的配置。输出包括：

- 自动生成的 Markdown 对比表；
- JSON 原始报告；
- 每个案例/缓存模式的参考 SQL、优化 SQL及参数；
- 两侧 EXPLAIN；
- 30 轮延迟与两侧 Query ID/Profile 摘要；
- P50/P95、结果行数、SQL 指纹和自动优化建议。

计算口径：

```text
P50 加速比 = 参考查询 P50 / 优化查询 P50
P95 加速比 = 参考查询 P95 / 优化查询 P95
```

只有报告生成完毕且所有 `resultsEqual=true` 后，才应据此选择特征表、物化视图、宽表、
分区裁剪或排名预计算等优化路径。
