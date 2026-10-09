# 从原 CSV 重建独立参考 DuckDB

独立参考库只存原始类型化数据：`newzl.hsj_stock_code_info`、`newzl.hsj_stock_hq_basic`、`newzl.hsj_stock_hq_ext` 和 `main.audit_source_lock`。证券代码保留字符串和前导零；日期为 DATE，DATETIME 对应 TIMESTAMP；价格 / 比率保留原整数，NULL、合法负数、`-999999` 哨兵和孤儿记录均不删除或归零。不从 Doris 导出，不复制语义视图、指标注册表达式或编译器 SQL 来产生预期结果。

后续正确性参考由既有 `project_field_reference.py`、`project_matrix_reference.py`、`project_combination_reference.py` 和 `project_rank_reference.py` 从 RAW 表读取真实观察记录，独立手工计算指标、窗口和排序。这仍是项目内部参考，不代替额外确认的官方口径或外部盲测。

## 安全重建

使用现有 `.tools/data-audit-venv`（DuckDB 1.4.3）运行新安全入口。输出目录、数据库、WAL、临时目录和构建占用标记必须全部为新路径；脚本不会替换旧库或清理失败库。不要直接对已有参考库运行旧 `audit_official_data.py`，它是内部审计实现，包含 CREATE OR REPLACE。

在项目根目录 PowerShell 执行，示例中的 NEW 改为未使用的版本名：

```powershell
& .\.tools\data-audit-venv\Scripts\python.exe -X utf8 scripts/doris/build_reference_duckdb.py `
  --data-root 'D:\xwechat_files\wxid_wf4vvow8t34722_dca8\msg\file\2026-09\DorisSQL的自动化编译系统资料\DorisSQL的自动化编译系统资料\Doris A股行情数据集' `
  --database 'D:\DorisProjectRuntime\reference\stock-20060104-20260414-v1\raw-NEW.duckdb' `
  --output-dir 'reports/reference-rebuild/NEW/build' `
  --memory-limit 1GB --threads 1
```

资源上限适合本机原 Doris 和新专用环境并存的情况；不会停止任何 Doris、修改 WSL 内存或把库迁回 C 盘。临时溢写目录紧邻 D 盘库文件，DuckDB 的内存上限不是整个进程 RSS 的严格上限。新环境使用者如无该 Python 环境，应在隔离虚拟环境安装 `scripts/doris/requirements-data-audit.txt`。

流程为：

1. 按 manifest 相对路径定位三份原文件；验证完整表集合、大小、SHA256、字段顺序和 DDL 类型集合。路径越界、重名副本、未知 schema 或任意不一致在连接库前拒绝。
2. 直接严格读取 CSV，全量审计后构建 RAW typed 表，不忽略坏行或通过删除记录提高覆盖率。
3. 再次验证三份源文件及 manifest、DDL、历史异常定义未变化；要求完整 23 项审计门禁全部执行。
4. CHECKPOINT 并关闭，再以 `read_only=True` 独立重开；复核全部持久化字段类型、行数、日期、NULL 和哨兵计数、空键、重复键及唯一审计锁。
5. 关闭所有连接后记录主文件 SHA256 / bytes，要求无非空 WAL。报告绑定该文件内容，而不只是路径。

失败返回非零，保留部分数据库与失败证据，不产生可用状态；下一次重建使用新的版本路径，不自动清库。

## 区分参考库可用和原始审计通过

当前冻结源文件的历史全量审计有 `extensionWithoutBasic=249480` 的 FAIL，以及 `close_price_range=3487` 的 WARN。默认引用已保留的 `reports/data-inspection/2026-10-04/全量数据检查.json`；只允许相同 source SHA / bytes / rows 且同一检查名称、状态和数量的这两类既有异常。未知失败、遗漏检查、异常被假装标为 PASS 或任何源身份变化都会阻断。

因此，正常重建状态是 `REFERENCE_READY_WITH_SOURCE_LIMITATIONS`、`buildStatus=PASS`、`auditStatus=FAIL`。`audit_source_lock.status` 继续保持真实 FAIL；既有差分工具要求此状态，不能手工改成 PASS。它表达全量来源存在关联问题，不是编译器 SQL 错误，也不是参考库构建失败。

报告为新目录下的 `reference-build.json`、`REPORT.md` 和 `raw-audit/全量数据检查.json`。不要覆盖历史 FAIL 报告，也不要将本轮状态替换成正式 `VALIDATED`。

## 后续差分使用

本轮库位置以 [本轮构建报告](../reports/reference-rebuild/2026-10-06/build-v1/REPORT.md) 为准。显式传给项目工具：

```powershell
--reference-database 'D:\DorisProjectRuntime\reference\stock-20060104-20260414-v1\raw-20261006-v1.duckdb'
```

`run_project_acceptance.py` 会对关闭的库文件计算内容哈希，并拒绝非空 WAL 和验收期间变化；需要正式执行矩阵时仍须新建运行目录、发布新鲜 Doris 项目来源证书并保留各阶段结果。重建参考库本身不执行整个正式黄金集、性能矩阵或 30 次重复测试。

日常以 `duckdb.connect(path, read_only=True)` 打开参考库，不在其中写临时结果或建立生产物化视图。新安全重建回归和原始审计回归已加入统一 PowerShell 自测及离线 CI；本轮本机执行结果见 `reports/reference-rebuild/2026-10-06/offline-selftest.json`。

请上传脚本、配置和脱敏报告到 GitHub，不上传 CSV、DuckDB 主文件 / WAL、密码、镜像归档或 VHDX。

实现依据：[DuckDB CSV 严格读取选项](https://duckdb.org/docs/stable/data/csv/overview.html)、[资源与临时目录配置](https://duckdb.org/docs/stable/configuration/overview.html)、[CHECKPOINT 持久化](https://duckdb.org/docs/stable/sql/statements/checkpoint.html)。本机实际版本固定为 1.4.3，不因文档最新版本变化升级库文件。
