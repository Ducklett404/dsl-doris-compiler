# 专用 Doris 环境恢复（2026-10-06）

此环境与原 Docker Desktop 的 `doris` 分开。原容器、`doris-fe-meta`、`doris-be-storage` 和原数据库不重建、不删除、不改密码；没有进行工厂重置、prune、unregister 或全局 WSL shutdown。

| 项目 | 专用环境 |
|---|---|
| WSL 发行版 | `dsl-doris-official-01a104f9`，Ubuntu 24.04、WSL2 |
| Windows 文件位置 | `D:\DorisProjectRuntime\wsl\ext4.vhdx` |
| 独立 Docker 数据根 | `/var/lib/dsl-doris/docker` |
| 容器与所有权标记 | `dsl-doris-official` / `official-data-diagnostic` |
| 镜像 | `apache/doris:all-in-one-4.1.3`，复用原本机镜像 |
| SQL / FE HTTP / BE HTTP | `19030` / `18030` / `18040` |
| 持久数据 | `/var/lib/dsl-doris/fe-meta`、`/var/lib/dsl-doris/be-storage` |
| 当前资源 | 容器 5GiB、4CPU；FE heap 768MiB、BE JNI heap 128MiB；BE mem_limit 60%（3GiB），实际应用及保留数据核验见 `reports/project-acceptance/2026-10-07/memory-fix/apply-v2/result.json` |
| CSV 装载副本 | `D:\DorisProjectRuntime\normalized`；原文件完全保留 |
| 数据身份 | `stock-20060104-20260414-v1`，不可变原 CSV SHA256 |

当前机器共约 15.28GiB RAM，WSL VM 上限约 7.39GiB，原库继续运行。因此不复用历史 10GiB / 6CPU 的性能环境，不声称这次恢复证明 19 年查询 10 倍加速或性能验收通过。更改全局 WSL 内存并重启原环境需另行确认。

2026-10-07 的 `run-v3` 在 `position-last` 被 BE 进程总内存门禁取消：查询约 429–527MiB，低于 2GiB 查询上限，但进程约 2.03–2.12GiB 超过 40%（2GiB）总额。这不是数值溢出。专用 entrypoint 将 BE 总额设为 60%，不增大 5GiB 容器、4CPU 或 SQL 的 2GiB/10 秒/一亿扫描行/10000 返回行限制。

容器内 `/run/dsl-be-memory-percent` 只接受 `40` 或 `60`，可在保留容器及数据的重启后生效；未设置时默认 `60`。原镜像环境中旧 `BE_CONFIG_EXTRA` 的 mem_limit 行会被替换，其余端口配置保留。应用和回滚使用 `configure_project_be_memory.py` 的新输出目录，必须验证原始计数、日期、视图定义及正式登记完全不变。更改源码或运行配置后使用新验收批次，不能将 `run-v3` 的 57 次通过当作完整 30 轮证据。

仅增加 BE 进程预算不足以保证查询成功：`memory-fix/position-last-v1` 在 60% 下仍失败，查询峰值 1.34GiB、进程 3.06GiB 超过 3GiB。该会话的 `parallel_pipeline_task_num=0` 为自动并行度，不能视为遵守容器的 4CPU 配额。受控执行器改用会话级固定并行度 4，保持 SQL、窗口、参考定义和所有查询上限不变；是否解决以新的真实单例及冻结全量批次为准，不将配置应用 PASS 等同于查询 PASS。

2026-10-09 的 `run-v9` 已通过全部 345 例原始参考预检及字段组 2820 次，但组合组第 12 轮的 `mixed-average-ma3-rsi2` 数据质量 `combinedSql` 再次被 BE 总内存保护取消：查询峰值 1,863,567,616 bytes，BE 3.02GB 超过 3GB，系统可用 1.06GB 高于 256MB 低水位。该轮保持 FAIL，不能沿用旧轮成绩补齐。当前受控执行器与独立 EXPLAIN 会话进一步降至并行度 **2**，不改变 SQL、指标公式、数据和上述预算；必须先做新的独立诊断，再按新源码/JAR 身份重跑整批。降低并行度不保证内存减半，是否稳定以新实测结果为准。

`memory-fix/position-last-v3` 已真实通过上述单例；主 SELECT 约 2.77 秒，但含数据可用性检查的 HTTP 总耗时约 10.08 秒，因此不能宣称所有端到端请求低于 10 秒。另修正了 Connector/J 在 `setMaxRows` 清理期间覆盖 `LAST_QUERY_ID` 的问题：主语句关闭前用同一限额读取 ID，随后按精确 ID 查询 Profile。仅保留已核实的摘要布局，未知、未留存或异步未就绪摘要仍明确标记 unavailable，不重复执行主 SQL。真实小型 JDBC 对照证据见 `reports/project-acceptance/2026-10-07/profile-fix/jdbc-probe-v1.json`。

## 日常启动

### 小容器的 FE 运行配置（2026-10-09）

`run-v8` 的组合预检被原生 `MEM_LIMIT_EXCEEDED` 取消：当时查询使用 1.80GiB、峰值 1.82GiB，尚未达到 2GiB 查询限额；BE 使用 2.53GiB，也未达到 3GiB 进程限额，但可用内存 191.90MiB 低于 256MiB 保护水位。稍后的空闲检查发现 FE 的私有匿名常驻内存约 2.25GiB，尽管 JVM 堆最大值只有 768MiB。不能仅凭这些数据断定全部为 glibc 碎片，诊断见 `reports/project-acceptance/2026-10-09/memory-low-water-diagnostic/README.md`。

新增的可回滚 FE profile 将进程树继承的 `MALLOC_ARENA_MAX` 固定为 4，并通过 `JAVA_TOOL_OPTIONS=-XX:ActiveProcessorCount=4` 约束两个 JVM 的 CPU 视图。BE 的显式 jemalloc 配置保持不变。这两个选项不是扩大资源预算，也不是实际 arena 数量的测量；需要新批次查询和长期内存观察验证效果。不会降低低水位，不会关闭 cgroup 检查，不会增大容器、堆、扫描、返回行或查询时间限制。

```powershell
# 仅首次显式应用。BE bounded profile 须已启用，输出目录必须不存在。
& .\.tools\data-audit-venv\Scripts\python.exe scripts/doris/configure_project_fe_runtime.py `
  --apply --report-dir reports/environment-recovery/NEW/fe-runtime
```

脚本只写专用容器的 `/run/dsl-fe-runtime-profile` 并重启该容器。它先检查所有权、已有 5GiB/4CPU/FE768MiB/JNI128MiB 预算和 BE 配置，再备份原始 override 字节及固定单文件回滚 tar；失败时恢复原 profile 并验证数据、日期、视图、正式登记和配置。已启用的 profile 不重复覆盖。恢复命令和二进制 stdin 工件保存在本次 `result.json` 中，不需要输入或导出密码。

统一验收现在冻结 FE 实际进程选项、FE 配置和挂载入口的指纹，版本为 `owned-runtime-v2-fe-process`。配置切换后必须使用新的全量验收批次，不能与旧 profile 的 30 轮结果拼接。普通关机/启动后私有 override 保留；不要删除容器，仍使用下述日常启动入口。

在项目根目录的 PowerShell 执行：

```powershell
& .\scripts\doris\start-project-environment.ps1
```

脚本启动一个隐藏的 `wsl --exec sleep infinity` 保活进程，防止 WSL 在所有前台命令结束后退出；WSL 内 Docker 为 systemd 服务，容器为 `unless-stopped`。仅 systemd 服务本身不能保证 WSL 保活。没有新增登录计划任务。电脑重新启动后再执行上述命令即可。

Windows 访问使用实际 WSL IPv4 地址。本机这次检查中 `127.0.0.1:18030` 不通，WSL IPv4 的 HTTP 和 JDBC 均通过；没有修改防火墙或建立端口代理。IP 可能在重启后改变，不要把本次的 `172.19.184.174` 写死：

```powershell
$taskDorisIp = ((wsl -d dsl-doris-official-01a104f9 --exec hostname -I) -join '').Trim().Split(' ')[0]
curl.exe --fail --connect-timeout 5 "http://${taskDorisIp}:18030/api/health"
# Windows JDBC/数据库工具：Host=$taskDorisIp，Port=19030，Database=newzl。
```

`docker ps` 默认仍然查看原 Docker Desktop，不会列出独立 daemon 的专用容器。查看专用环境：

```powershell
wsl -d dsl-doris-official-01a104f9 --exec docker ps
```

查询管理入口（不用在命令中输入密码）：

```powershell
wsl -d dsl-doris-official-01a104f9 --exec docker exec dsl-doris-official mysql --defaults-extra-file=/run/dsl-client.cnf -e 'SHOW BACKENDS;'
```

私有配置包含随机密码，放在 WSL `/var/lib/dsl-doris/client.cnf` 和 `reader.cnf`，权限为 0600；不放入 Git、Windows 报告或命令参数。正常应用使用只读 `dsl_project_reader`，不要拿 root 管理账号执行用户 DSL。

## 从现有 CSV 准备与恢复

新建发行版须使用官方 Ubuntu rootfs、验证官方 SHA256，然后执行 `wsl --import <名称> <D盘新目录> <rootfs> --version 2`。不要注销原发行版或恢复到原卷。导出原镜像不导出/修改原数据卷。

```powershell
# 新发行版中安装独立 daemon，使用已导出的镜像，不重新拉取。
wsl -d dsl-doris-official-01a104f9 --exec bash /mnt/c/Users/scx/Desktop/Dsl-Doris-Compiler/dsl-doris-compiler/scripts/doris/bootstrap-wsl.sh /mnt/d/DorisProjectRuntime/image/apache-doris-all-in-one-4.1.3-amd64.tar
& .\scripts\doris\start-project-environment.ps1

# 输出目录必须为空；原文件只读，先验 3 份文件的 SHA256 与大小。
& .\.tools\data-audit-venv\Scripts\python.exe scripts/doris/prepare_recovery_csv.py --data-root '<三份原 CSV 的根目录>' --output-dir 'D:\DorisProjectRuntime\normalized' --chunk-rows 250000

# 装载目标 newzl 必须为空，报告目录必须不存在。
wsl -d dsl-doris-official-01a104f9 --exec bash /mnt/c/Users/scx/Desktop/Dsl-Doris-Compiler/dsl-doris-compiler/scripts/doris/load-wsl-recovery.sh /mnt/c/Users/scx/Desktop/Dsl-Doris-Compiler/dsl-doris-compiler /mnt/d/DorisProjectRuntime/normalized /mnt/c/Users/scx/Desktop/Dsl-Doris-Compiler/dsl-doris-compiler/reports/environment-recovery/NEW/load
```

所有装载以 25 万行小批次串行执行，`strict_mode=true`、`max_filter_ratio=0`，不允许丢行。每批保存响应和 stderr；总行数、装入行数、过滤行数、未选择行数必须分别等于源行数、源行数、0、0。`Publish Timeout` 已提交，不换 label 重试；最后等待可见总行数完全一致。

装载完成自动应用当前 `002_semantic_view.sql`。六项基础价格直接由原始整数规范化为 `DECIMAL(19,4)`；`avgPx=turnover/100/volume` 使用精确十进制金额和成交量，输出 `DECIMAL(38,21)`，避免 DOUBLE 运算重关联破坏相等比较。复权仍使用原价/10000 × 系数 + 加数，价格、比率、量比别名和哨兵 Clean 列均由视图提供。没有构造不存在的 `open_qfq` / `close_qfq` 原表字段。

重复装载非空库会明确拒绝，而不是自动 DROP。部分装载失败时，保留数据、每批证据与所有 CSV；需要依据失败记录另行决定续传或新建环境，不允许直接清库再试。

## 恢复核验与运行证书

```powershell
& .\.tools\data-audit-venv\Scripts\python.exe scripts/doris/verify_recovered_snapshot.py --prepared-dir 'D:\DorisProjectRuntime\normalized' --output-dir reports/environment-recovery/NEW/verification
& .\.tools\data-audit-venv\Scripts\python.exe scripts/doris/validate_project_sources.py --java D:/java/bin/java.exe --data-root '<原 CSV 根目录>' --output-dir reports/environment-recovery/NEW/source-validation
```

第一步校验全表计数、日期、类型、重复键、空键、空值和哨兵计数，并独立计算 RAW 抽样的视图公式。第二步串行检查关联缺口，发布项目内部 `PROJECT_READY_WITH_LIMITATIONS` 证书。两步都不会新增 `VALIDATED` 登记；原 CSV 自带的孤儿记录、价格警告不抹掉，不伪装成官方验收通过。

核验器对行情表逐年串行检查空值、哨兵和重复键，再累加并与独立全表计数核对；不通过抽样代替这些全量检查。这样限制单次聚合内存，避免一次聚合所有列触发内存限制。公式核验仍为每表 34 条固定样本，使用独立 RAW 计算与预先声明的浮点容差。

使用已生成的项目证书重新执行只读 DSL，并生成 JSON / Markdown 和参考结果对比（输出目录必须是新目录）：

```powershell
& .\.tools\data-audit-venv\Scripts\python.exe scripts/doris/smoke_recovered_execution.py --certificate reports/environment-recovery/2026-10-06/source-validation-v1/project-validation.json --output-dir reports/environment-recovery/NEW/execution-smoke
```

该脚本从 WSL 私有配置读取只读账号密码，通过进程环境传入 Java，不在控制台、报告或命令参数显示密码；动态发现 WSL IPv4 地址与 SQL 端口。它检查 `examples/project-basic.dsl` 的前 20 个股票结果及顺序是否与独立 RAW 参考 SQL 一致。这是恢复连通性测试，不是黄金集正确率或编译 P95 测试。

本次证据见 [恢复与装载自测报告](../reports/environment-recovery/2026-10-06/恢复与装载自测报告.md)。此前跳过的真实 JDBC 测试可用 `run_wsl_integration.py --junit-only` 准备独立合成库补跑：新建随机库与账号、严格验证 8 项且零跳过、最后清理本次夹具；不清空原表、不变更官方快照登记。具体命令及本机 8/8 完成证据见 [隔离集成测试报告](../reports/wsl-integration/2026-10-06/REPORT.md)。提交代码时上传脚本、配置及脱敏报告；不要上传密码、原始 CSV、规范化副本、镜像归档或 VHDX。

来源：[Microsoft WSL 导入说明](https://learn.microsoft.com/windows/wsl/use-custom-distro)、[官方 Ubuntu WSL 镜像](https://cloud-images.ubuntu.com/wsl/releases/24.04/current/)、[Apache Doris All-in-One 配置与持久化说明](https://doris.apache.org/community/developer-guide/all-in-one-image/)。
