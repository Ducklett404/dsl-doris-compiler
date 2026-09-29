# Doris 基准矩阵自测报告

日期：2026-09-27

## 当前结论

基准框架、矩阵、等价性门禁和证据输出已实现并通过离线回归。当前未生成或伪造真实
P50/P95 数值：本机 Docker Desktop 服务未运行，Doris 的 9030/8030 端口未监听，因此
无法在同一数据快照上完成本轮 30 次冷热实测。只有实测报告中全部
`resultsEqual=true` 后，才允许按报告建议选择优化路径。

## 已完成检查

| 检查项 | 结果 |
|---|---|
| 12 类典型查询矩阵 | 通过定义与双路径编译测试 |
| 每类至少 30 次 | 运行器强制 `iterations >= 30` |
| 热缓存协议 | 预热后交替执行基线/优化，降低顺序偏差 |
| 进程冷缓存协议 | 每条计时 SQL 前重启 Doris 容器并等待 FE/BE 可查询 |
| 相同快照 | 执行前强制快照为唯一 `VALIDATED` 状态 |
| 相同过滤条件 | 基线与优化绑定参数逐项保持一致 |
| 相同结果集及排序 | 每次逐行、逐列、按顺序比较；不一致立即终止 |
| P50/P95 与加速比 | 通过 30 点最近秩百分位单元测试 |
| EXPLAIN/Profile 证据 | 每个查询和缓存模式分别保存 |
| 自动 Markdown/JSON 对比表 | 通过渲染测试 |
| 完整 Java 回归 | 137/137 通过 |

## 本轮发现并修正的问题

1. `benchmark-matrix --help` 原先被当作未知参数；现已为该子命令启用标准帮助选项。
2. 不能把“第一次运行”简单称为冷缓存；现采用每条计时 SQL 前重启 FE/BE 的
   `PROCESS_COLD` 协议，并在报告中明确不声称清除了宿主机操作系统页缓存。
3. 为避免基线和优化查询互相污染，热缓存样本交替执行顺序，冷缓存样本分别重启后执行。
4. 为避免只比较耗时却返回不同答案，执行器在记录样本前先做完整结果及排序等价检查。

## 恢复实测命令

管理员启动 Docker Desktop，并确认 `docker ps` 中 `doris` 为 healthy 后，使用只读基准账号运行：

```powershell
$env:DORIS_BENCHMARK_PASSWORD = '<只读基准账号密码>'
java -jar target/dsl-doris-compiler.jar benchmark-matrix `
  --matrix benchmarks/doris-matrix-v1.json `
  --iterations 30 `
  --cold-restart-container doris `
  --user dsl_benchmark_reader `
  --password-env DORIS_BENCHMARK_PASSWORD
```

完整 12 类矩阵需要执行 720 次进程冷启动测量，属于长时间任务。最终产物为
`reports/benchmark-matrix/report.md`、`report.json` 和 `evidence/`。
