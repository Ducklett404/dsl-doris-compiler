# EXPLAIN / Profile 证据入口

## 本轮状态

`NOT_RUN`。本轮文档交付时 Docker daemon 未运行，且当前进程未设置
`DORIS_PASSWORD`，因此没有生成新的 Doris EXPLAIN、Query Profile 或冷热缓存
30 次基准证据。这里不使用模拟数据代替真实执行结果。

仓库中可复核的历史固定快照证据位于：

- `reports/performance/PERFORMANCE_REPORT.md`
- `reports/performance/doris-execution-smoke.json`
- `reports/accuracy/stock-slot-executable-v1/REPORT.md`

这些文件记录的是 2026-09-18 的 `stock-20060104-20260414-v1` 固定快照，不能替代
本轮复测。

## 生成本轮证据

启动 Doris 并设置只读账号密码后，在项目根目录执行：

```powershell
$env:DORIS_PASSWORD = '<只读账号密码>'
& .\scripts\test-all.ps1 -WithDoris -RunNineteenYearBenchmark
```

基准必须使用同一快照、相同过滤条件和相同结果集；脚本会把可用的 EXPLAIN、
Profile 摘要及统计结果写入基准报告目录。只有生成文件且验收脚本返回成功后，才可将
本状态改为 `PASS`。
