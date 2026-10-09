# Doris 行情数据装载与快照

当前执行范围为 v1.0.4，需应用现行语义视图后重新验证来源；当前收到的原始数据关联门禁仍受限制。状态和新批次运行方式见 [项目状态](../../docs/project-status.md)、[运行手册](../../docs/runtime-guide.md)。固定 manifest 不在本轮文档更新中重新生成。

本目录把原始 CSV、Doris 物理表和查询语义分成三层：

1. `raw` 表逐列接收 CSV，列名以 CSV 为准（`quantRatio`、`ahFlag`）。空字符串装载为 `NULL`。
2. `v_hsj_stock_hq_basic` 统一价格、金额和比率倍率，并提供文档中的派生指标。
3. 快照清单用 SHA-256、行数和日期范围锁定输入；Doris 装载后必须通过 `validate_snapshot.sql`。

## 已解决的结构差异

| 差异 | 最终口径 |
|---|---|
| `quanRatio` / `quantRatio` | 物理列采用 CSV 的 `quantRatio`；语义视图额外提供兼容别名 `quanRatio` |
| 缺少 `marketValue` 等列 | 不伪造 CSV 列，在语义视图中计算 `marketValue`、`listedMarketValue`、`risePct`、`avgPx` |
| 整数倍率 | 价格 `/10000`，金额 `/100`，比率 `/10000`，股数/量不缩放；依据见 `config/data-contract-v1.json` |
| 文档 `TIME` / CSV `DATETIME` | CSV 实值含日期，物理列使用 `DATETIME` |
| 复权价 | `原始价格/10000 * multi + add`；不引用不存在的 `open_qfq` 等物理列 |

注意：当前快照中 `qfqMulti/qfqAdd/hfqMulti/hfqAdd` 全部为 `1/0/1/0`，只能验证恒等情形。上线前必须补充至少一条非默认因子的权威样例，确认 `add` 的单位为“元”；校验脚本会报告这一风险。

## 一次性执行

依赖：Python 3.11+、MySQL 命令行客户端、`curl.exe`，以及可连接的 Doris FE（MySQL 端口通常 9030，HTTP 端口通常 8030）。密码只从 `DORIS_PASSWORD` 环境变量读取。

```powershell
$env:DORIS_PASSWORD = '<password>'
# 仅在准备新来源快照时生成候选清单；不覆盖当前冻结清单
python scripts/doris/snapshot_tool.py profile --data-root '<Doris A股行情数据集目录>' --output build/candidate-snapshot-manifest-new.json
pwsh scripts/doris/load-csv.ps1 -DataRoot '<Doris A股行情数据集目录>' -SnapshotId 'stock-20060104-20260414-v1' -FeHost localhost
pwsh scripts/doris/validate-snapshot.ps1 -Manifest data/doris/snapshots/stock-20060104-20260414-v1/manifest.json -FeHost localhost
```

`load-csv.ps1` 默认重建三张表，以保证旧的错误结构不会残留。每次运行的 Stream Load JSON 响应、失败记录和 SQL 输出保存在 `data/doris/runs/<snapshot>/<UTC时间>/`。任何过滤行都会使装载失败。

Windows Docker Desktop 使用 all-in-one 镜像时，应追加 `-HttpPort 8040`，直接访问映射到宿主机的 BE Stream Load 端口，避免 FE 返回的容器内地址无法从 Windows 跟随。

如果 Windows 没有安装 `mysql.exe`，可直接复用 all-in-one 镜像内的客户端：为装载和验收命令追加 `-MySqlContainer doris`。脚本会动态解析容器 IP，因此容器重启后仍可使用。

装载脚本按 ASCII CSV 文件名递归定位三个源文件，不依赖中文子目录字面量，兼容 Windows PowerShell 5.1 对无 BOM UTF-8 脚本的读取行为。

CSV 的连续分隔符表示空字符串，而 Doris 默认只把 `\\N` 当作 `NULL`。脚本逐表生成临时规范化 CSV，把空字段写成 `\\N`，导入完成后删除临时文件；严格模式和 `max_filter_ratio=0` 仍然生效，非空脏值不会被静默吞掉。采用客户端规范化是为了绕开 Doris 4.1.3 在本数据集复杂 Stream Load 列表达式下发生的 BE 重启。

## 重复恢复

恢复同一快照时必须使用同一份清单和 SHA-256 完全相同的三个 CSV。重新执行 `load-csv.ps1` 即可重建并恢复；它会在上传前校验文件。若配置了 Doris Repository，可在装载校验完成后执行 `ddl/006_backup_snapshot.template.sql` 创建原生 Doris 备份。

## 验收条件

- 三张表行数与清单一致；行情表最小/最大日期一致。
- `(mktcode,tgtcode[,bizdate])` 无重复。
- 扩展表每一行都能关联基础表；基础表允许没有扩展行（扩展数据从 2018 年才开始）。
- 关键字段抽样计算误差在 SQL 中设定阈值内。
- 空值率和 `-999999` 哨兵值有报表；哨兵值在语义视图中转为 `NULL`。
- 任何 Stream Load 过滤行、清单哈希不符或校验失败都阻止快照登记为 `VALIDATED`。
