# CLI、HTTP、Docker 与数据装载运行手册

## 现有数据按查询依赖运行（2026-10-05）

数据无法继续补充时，`execute-stock-slot-sql` 与 `serve-doris` 可显式使用可信本地 `--project-validation` JSON。按基础、衍生和证券代码来源分别验证，并返回筛选前的指标/窗口缺失统计。权限与资源限制继续有效，不写入 `VALIDATED`，正式验收入口保持完整快照门禁。配置、结果字段及限制见 [按查询依赖验证指南](project-scoped-validation.md)。

当前能力、19 指标单位、MA/RSI 参数、组合与资源限制、演示及交付恢复统一在 [项目能力与交付 v1](project-capabilities-v1.md)。新的项目验收入口使用 `scripts/doris/run_project_acceptance.py --report-dir 新目录`；默认便携执行不会声称真实 Doris 已通过，真实环境须显式 `--with-doris`。完成验收后用 `scripts/doris/package_project_delivery.py --evidence-dir 本批目录 --output-dir 新交付目录` 固定交付哈希。

## 环境

- JDK 21；Maven 3.9+；Python 3.12；Windows PowerShell 5.1+。
- Python 统一自测依赖固定在 `scripts/doris/requirements-selftest.txt`（openpyxl 3.1.5、DuckDB 1.4.3）。对指定的测试解释器安装这些依赖，并使用 `scripts/test-all.ps1 -PythonExecutable 该解释器路径`；隔离 Doris 集成脚本沿用调用它的解释器。
- Doris 本机验收使用 `apache/doris:all-in-one-4.1.3`，端口 `9030/8030/8040`。
- 密码只通过 `DORIS_PASSWORD` 环境变量传入，不进入命令历史或仓库。

## 一键建表、导入和快照验收

以下命令校验三份 CSV 的 SHA-256，重建三张真实表，规范化空值，使用严格 Stream Load
导入，创建语义视图，再校验行数、日期范围、唯一键和表间关联。只有全部正式门禁通过才登记 `VALIDATED`；当前收到的原始快照存在 249,480 条未关联衍生行，严格验证预计拒绝，不能承诺该命令结束即登记成功。
默认重建会删除同名旧表；保留表结构时显式使用 `-NoRebuild`。

```powershell
$env:DORIS_PASSWORD = '<装载账号密码>'
./scripts/doris/setup-load-validate.ps1 `
  -DataRoot 'D:\path\to\Doris A股行情数据集' `
  -MySqlContainer doris -User dsl_loader
```

需要同时建立冻结日性能特征时追加 `-BuildPerformanceFeatures`。装载响应、失败记录和失败行保存在
`data/doris/runs/<snapshot>/<run-id>/`。

## 一键构建、测试和启动

前台 HTTP：

```powershell
./scripts/build-test-start.ps1 -MavenExecutable mvn.cmd -Mode Http
```

Docker 后台：

```powershell
./scripts/build-test-start.ps1 -MavenExecutable mvn.cmd -Mode Docker
docker compose logs -f compiler
docker compose down
```

只验证构建和性能门禁使用 `-Mode VerifyOnly`。

## CLI

```powershell
# 编译正式 DSL
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql `
  examples/registry-smoke.dsl --format json

# 受控执行（只读账号、VALIDATED 快照、EXPLAIN 扫描门禁）
$env:DORIS_PASSWORD = '<只读账号密码>'
java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql `
  examples/registry-smoke.dsl --user dsl_runtime_reader `
  --snapshot-id stock-20060104-20260414-v1 --format markdown `
  -o reports/final/query.md

# 复杂正式语料编译性能
java -jar target/dsl-doris-compiler.jar benchmark-stock-slot-compiler `
  --warmup 1000 --iterations 5000 --p95-threshold-ms 50
```

## HTTP

编译服务：

```powershell
$env:DSL_HTTP_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
java -jar target/dsl-doris-compiler.jar serve --host 127.0.0.1 --port 8080
```

```bash
curl -X POST http://127.0.0.1:8080/compile \
  -H "Authorization: Bearer $DSL_HTTP_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary '{"dslVersion":"stock-slot-v1","dsl":"indicator('\''沪'\'', '\'''\'', '\''收盘价'\'', '\''2026-04-14'\'', '\'''\'', '\'''\'', '\'''\'') > 10"}'
```

带 Doris 执行的 HTTP 服务使用 `serve-doris`。该入口启动时检查只读授权，提供 `/compile`、
`/execute` 和 `/health`。Docker Compose 默认只启动无数据库依赖的编译服务；将数据库密码放入
镜像或 Compose 文件属于禁止做法。

两个入口都要求配置 `DSL_HTTP_TOKEN`（或 `--auth-token-env` 指定的变量），请求必须携带
`Authorization: Bearer <令牌>`。`serve` 仅授予 `COMPILE_DSL`；`serve-doris` 同时授予
`EXECUTE_DSL`。令牌需为 32–4096 字符，建议生成 32 字节随机值并由密钥管理系统注入。
`/health` 无需令牌。服务限制每个请求体为 1 MiB，同时处理最多 32 个已授权编译/执行请求；
超大请求返回 413，超过并发限额返回 429。重复 JSON 字段、尾随 JSON、类型不合法或客户端
传入权限字段返回 400。

## Docker

```powershell
$env:DSL_HTTP_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
mvn.cmd -B -DskipTests package
docker compose up -d --build
curl.exe http://127.0.0.1:8080/health
```

容器为只读根文件系统并仅挂载临时 `/tmp`。`docker-compose.yml` 固定暴露 `8080`，
`Dockerfile` 固定使用 JRE 21 和已构建的 fat JAR。

## 2026-10-04 修复升级

注册表升级为 `1.0.2`，数值修复后的活动范围冻结为 `stock-slot-phase1-scope-v1.0.2`；历史冻结保存在
`config/acceptance/history/`。冻结校验只统一 CRLF 为 LF，其他内容变化仍会失败。

涨跌幅使用显式 DOUBLE 减法和除法，避免 Doris 推导为五位小数的 DECIMAL。
position 使用从原始字段计算的精确伴随列、按指标量纲声明的小数位和交叉乘法，包含两个三等分边界。
升级已有数据库时由装载账号应用 `data/doris/ddl/002_semantic_view.sql`，再使用新 JAR；
该脚本只重建语义视图，不重建基础表或注册快照。先保留旧 `SHOW CREATE VIEW`
定义供回滚，并核对关联、字段范围与实际查询结果。当前官方快照仍未获 VALIDATED 登记。
注册表指纹会随新元数据变化，旧的显式历史 / 滚动特征目录不再匹配；
必须按新注册表重新构建并独立校验目录，不能直接改目录指纹来复用旧登记。

本地隔离实例可用 `scripts/doris/apply_numeric_view_revision.py --output-dir <新目录>`
保存完整视图定义并升级；备份必须包含多行 `AS SELECT` 内容，不能只保留首行。
`scripts/doris/check_view_revision_rollback.py --output-dir <新目录>` 在临时空库插入测试行，
验证旧版冻结 SQL、完整备份及恢复后的全部列类型和结果，完成后清理临时库。
4 GB BE 内存的诊断实例应顺序运行全量 position、滚动构建和完整历史校验，
避免并行任务导致 `MEM_LIMIT_EXCEEDED`。本轮最终证据见
`reports/precision-fix/2026-10-04/数值问题修复与自测报告.md`。

MA60 特征表升级为 `newzl.stock_daily_features_v2`，其窗口保留已有的 NULL 行；旧 v1 表不再
作为优化路径。部署时，先在已验证的 `stock-20060104-20260414-v1` 快照上运行
`data/doris/ddl/005_performance_features.sql`，由装载账号建表、填充并更新统计信息，再切换应用。
运行账号需要新表的 SELECT 权限；不要用只读运行账号执行 DDL。SQL 按业务键重建 v2 数据，
不会删除原始行情或旧 v1 表。仅 `2026-04-14` 且快照匹配的 MA60 执行使用 v2；其他日期或
快照回退为原始历史窗口。部署前仍需在实际 Doris 上运行结果对比。

Windows 本机自测可运行：

```powershell
.\scripts\test-all.ps1 -MavenExecutable '.\.tools\apache-maven-3.9.16\bin\mvn.cmd' `
  -MavenRepository '.mvn-cache' -Offline
```

若本机 Java 21 在 `UnixDomainSockets.connect0` 报 `Invalid argument: connect`，可为本次测试
增加 `-TestJvmArgs '-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets'`。该目录必须不存在，
让 Java 的 Selector 唤醒管道使用本机 TCP 回退。此选项不修改 Windows 或全局 JVM 配置；
同环境运行服务可将对应 `-D` 参数放在 `java -jar` 前。正常环境无需此选项。

## 本机虚拟环境诊断

2026-10-04 的历史执行曾建立 `.tools/data-audit-venv` 和独立 WSL2 发行版
`dsl-doris-official-01a104f9`，容器名为 `dsl-doris-official`。三张官方数据表完整导入，
原始 CSV 保留。虚拟磁盘、镜像缓存、导入副本和本机依赖位于忽略目录 `.tools/`，不会随 Git 克隆或小型交付包出现。当前电脑是否仍具备该环境须重新核对 `wsl -l -v`、容器和原始文件；此前报告不能证明当前连接有效。

从项目目录运行已准备好的实例：

```powershell
$wslRepo = '/mnt/c/Users/scx/Desktop/Dsl-Doris-Compiler/dsl-doris-compiler'
wsl -d dsl-doris-official-01a104f9 --exec /bin/bash "$wslRepo/scripts/doris/start-wsl-doris.sh" $wslRepo
.tools/data-audit-venv/Scripts/python.exe scripts/doris/check_local_results.py
.tools/data-audit-venv/Scripts/python.exe scripts/doris/check_wsl_results.py
python scripts/accuracy/check_contract_boundaries.py --wsl
python scripts/doris/check_wsl_execution_gate.py
```

以上脚本执行独立诊断，不登记 `VALIDATED` 快照。当前活动黄金集为 v1.0.1，修订说明与旧版本哈希保存在黄金集 `revision`；旧版两项结构失败报告保留。官方字段说明仍待确认，当前有 249,480 条衍生数据关联失败，正式快照门禁继续阻断。诊断结果、异常清单、
停止/重启方式和完整复跑步骤见
[全量检查与虚拟环境自测报告](../reports/data-inspection/2026-10-04/全量检查与虚拟环境自测报告.md)。

新一轮结果输出到 `reports/route-implementation/2026-10-04/`。本地诊断支持显式 `--manifest`、`--golden`、`--audit-report`、`--evaluation-date`、`--report-dir` 和 `--reference-output`；Doris 诊断支持 `--manifest`、`--report-dir`、`--reference-results`。日期、行数、用例数从配置读取；执行前核对快照与清单、黄金集、JAR 的哈希。必须先生成本地参考结果，再运行 Doris；编译器重建后需重新生成参考结果。

`compile-stock-slot-sql --snapshot-id <ID>` 会选择与快照相符的特征表；其他快照自动使用明细窗口。更换数据时仍需创建新的 manifest、审计数据库及黄金集快照引用，不能仅改 ID。

正式正确性入口的负向验证命令如下，当前数据预期输出 `BLOCKED` 并返回 3：

```powershell
python scripts/accuracy/run_correctness.py --wsl-distribution dsl-doris-official-01a104f9 `
  --container dsl-doris-official --output-dir reports/route-implementation/2026-10-04/formal-gate
```

只读接口诊断临时创建 SELECT 账号，检查写入拒绝、CLI 拒绝未验证快照、HTTP 401/503 和进程释放后删除账号；不登记快照。完整实施记录见 [路线实施与自测报告](../reports/route-implementation/2026-10-04/路线实施与自测报告.md)。

## 独立数据上的执行控制集成自测

在已有 WSL/Doris 实例运行时，从 Windows 项目目录执行：

```powershell
python scripts/doris/run_wsl_integration.py
```

脚本在独立的 `dsl_executor_fixture_*` 数据库创建小型合成行情，核对数量、复合键、价格及关联后，仅登记该合成库自己的测试快照。临时只读账号和带写权限的拒绝测试账号通过进程环境传入，不写入工件。脚本启用真实 JDBC 后运行统一自测，再验证 CLI/HTTP 成功执行、Markdown、鉴权、返回和扫描限制以及错误恢复，结束时清理测试库、账号和服务。

Java 集成测试另覆盖数据库超时分类、排队等待上限和异常后的跨线程恢复。排队测试使用测试传输层停顿；超时测试使用一次只读 `SELECT SLEEP(4)` 控制查询触发实际 JDBC 超时，不向用户 DSL 开放该函数。兼容 SCREEN 测试可用 `DORIS_SCREEN_TEST_REGISTRY`、`DORIS_SCREEN_TEST_CATALOG` 指定隔离映射，由脚本自动设置。

执行器从基础行情配置的数据库查找 `data_snapshot_registry`。默认仍为 `newzl.data_snapshot_registry`；切换数据库时应在该数据库建立并验证登记表，避免沿用另一数据库的验证记录。

当前本机报告输出至 `reports/continuation/2026-10-04/`。这项测试验证程序的执行控制能力，官方库的注册表仍为空。后续官方数据回归需重新生成当前 JAR 对应的参考结果：

```powershell
.tools/data-audit-venv/Scripts/python.exe scripts/doris/check_local_results.py `
  --report-dir reports/continuation/2026-10-04 `
  --reference-output target/data-audit/reference-results-continuation.json
.tools/data-audit-venv/Scripts/python.exe scripts/doris/check_wsl_results.py `
  --report-dir reports/continuation/2026-10-04 `
  --reference-results target/data-audit/reference-results-continuation.json
```

普通离线自测没有上述连接环境时，会明确跳过依赖 Doris 的集成测试；使用此脚本可在本机运行全部主模块测试。最新结果见 [继续推进与自测报告](../reports/continuation/2026-10-04/继续推进与自测报告.md)。

## 官方数据的热缓存性能诊断

等待官方关联规则期间，可运行单独的诊断工具。它验证原清单和审计来源、实际装载数量及空快照登记表，临时创建 SELECT-only 账号，通过持久 JDBC 连接执行矩阵的参考和优化路径。每类先预热，随后交替执行 30 次，逐次比较完整返回结果及排序，保存 SQL、绑定、EXPLAIN 和耗时。

```powershell
.tools/data-audit-venv/Scripts/python.exe scripts/doris/diagnose_performance.py `
  --iterations 30 --report-dir reports/performance-diagnostic/my-new-run
.tools/data-audit-venv/Scripts/python.exe scripts/doris/summarize_performance.py `
  reports/performance-diagnostic/my-new-run
```

选择新的报告目录以保留历史测量；现有 `diagnostic-summary.json` 不会覆盖。`--iterations 1` 只适合试跑，不能提供稳定分位数。诊断依赖 JDK 21、已有 JAR 及正在运行的项目专用 WSL/Doris；只读账号凭据仅传入子进程环境，结束时删除账号。

SQL 和查询结果缓存关闭，计时包括 prepare、执行及完整读取，不包含编译、WSL 启动或 EXPLAIN。操作系统和 BE 缓存已预热。热缓存矩阵使用单连接；显式目录启用均线或历史特征时，计时结束后另外使用 4 个只读连接，对选中的 MA60、MA250、长期历史候选各执行 20 次并发结果检查。工具不提供正式冷缓存或集群测量，也不创建 `VALIDATED` 快照。结果路径一致性不等于官方语义确认。相同 SQL 的耗时比不计作优化收益。

本机本轮证据见 [性能诊断与下一步](../reports/performance-diagnostic/2026-10-04/hot-30/性能诊断与下一步.md)。

## 历史极值聚合路径与复验

仅由不带计数的历史 `record_high/record_low` 组成的条件，可使用单次聚合访问路径。它扫描至评估日的历史，按 `(mktcode,tgtcode)` 聚合历史极值及评估日值，并检查评估日行是否存在。该等价改写依赖已验证的非空、唯一业务键；当日 NULL 不会回填成以前的价格。计数、排名、有限窗口、position 和混合窗口仍使用逐行窗口。

可只编译参考 SQL，以便复验或排查：

```powershell
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql query.dsl `
  --access-path FULL_SCAN_REFERENCE --format json
.tools/data-audit-venv/Scripts/python.exe scripts/accuracy/check_historical_extrema.py --wsl `
  --output-dir reports/history-optimization/new-selftest
.tools/data-audit-venv/Scripts/python.exe scripts/doris/diagnose_performance.py `
  --matrix benchmarks/history-matrix-v1.json --iterations 30 `
  --report-dir reports/history-optimization/new-hot-run
.tools/data-audit-venv/Scripts/python.exe scripts/doris/summarize_performance.py `
  reports/history-optimization/new-hot-run
```

`--access-path` 仅属于编译命令，不改变 CLI/HTTP 执行入口的快照门禁。每份 SQL 必须使用其自身的 bindings；不同访问路径的参数顺序可能不同。便携极值边界检查已加入统一脚本及 CI；`--wsl` 检查在临时独立数据库进行并清理该库，不登记官方快照。

该轮结果见 [历史极值优化与自测报告](../reports/history-optimization/2026-10-04/历史极值优化与自测报告.md)。聚合仍读取全部历史，热缓存 P95 耗时比为 4.1–8.0x。

## 显式历史极值特征

`HistoricalExtremaFeatureCatalog` 记录完整构建的日期、源快照 ID、源清单 SHA-256、字段配置指纹和安全的特征表/列名。编译器仅在四项身份匹配、所有函数均为无计数历史 MIN/MAX、所有字段均有特征时选择 `HistoricalFeatureScan`。未提供清单哈希、换快照、换字段配置、日期未构建、有限窗口、计数或混合函数均回退；`FULL_SCAN_REFERENCE` 始终使用原始窗口。

构建器在新建的 `dsl_history_diag_*` 数据库计算当日值和截至当日的 MIN/MAX，排除缺少当日行情的证券。NULL 当日值不会回填，全部 NULL 历史仍为 NULL，未来行不参与计算。发布前逐日期核对行数，并用有序窗口全量比较所有证券的 9 个数值字段；成功收集统计后才原子发布 `catalog.json`。任何步骤失败都会清理此次未发布数据库。已发布表保留以复现实验。

```powershell
.tools/data-audit-venv/Scripts/python.exe scripts/doris/build_history_features.py `
  --output-dir reports/history-features/new-build
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql query.dsl `
  --snapshot-id stock-20060104-20260414-v1 `
  --manifest-sha256 306f333e28c82c9f2c634d8a1eb64eb49d3092937d8ca7d2742d96ecdcf21a95 `
  --historical-features reports/history-features/new-build/catalog.json
.tools/data-audit-venv/Scripts/python.exe scripts/doris/diagnose_performance.py `
  --matrix benchmarks/history-matrix-v1.json --iterations 30 `
  --historical-features reports/history-features/new-build/catalog.json `
  --report-dir reports/history-features/new-hot-run
.tools/data-audit-venv/Scripts/python.exe scripts/doris/summarize_performance.py `
  reports/history-features/new-hot-run
```

目录必须新建以保留历史证据。目录中的 catalog 是受信任的完整构建发布物，不能手工声明尚未构建或不完整的日期；更新数据须重新构建和验证。数据库不存在或发布表被改动时应重新构建，不能以空结果代替缺失特征。编译器不查询数据库来判断表是否存在。当前只提供显式 SQL 编译和诊断入口，正常 CLI/HTTP 执行仍使用原有快照门禁；特征构建不会登记或验证原始快照。

该轮证据见 [历史极值特征与自测报告](../reports/history-features/2026-10-04/历史极值特征与自测报告.md)。后续均线、有限极值和增量构建的统一入口如下。

## 多日期滚动特征与完整路线复跑

`RollingAverageFeatureCatalog` 对 MA20/60/120/250 与高低价 250 观察行极值使用相同的快照、清单、字段配置指纹及完整日期绑定。`--rolling-features` 仅用于 `compile-stock-slot-sql`；所有调用都被目录覆盖时才选择 `RollingFeatureScan`。未发布的日期、窗口或字段，计数、排名及原始指标混合均回退到完整窗口。`FULL_SCAN_REFERENCE` 始终使用完整历史参考。

构建器首日保留每个证券最近 250 条实际观察行，后续从所有证券最后 249 行（包含 NULL）追加评估期间全部新行情。既不按日历天数裁剪，也不只保留上个评估日交易的证券。逐日期与完整历史 6 组窗口参考比较全部 10 个数值字段，并验证旧日期特征未变化后才发布目录。当前增量仅用于同一不可变快照内的追加；历史更正或新快照必须重新构建，不能复用旧尾部。

在项目专用 WSL/Doris、审计 DuckDB 和 Python 环境已经准备完成的本机，使用一条命令复跑当前官方数据诊断：

```powershell
.tools/data-audit-venv/Scripts/python.exe scripts/doris/run_official_data_route.py `
  --report-dir reports/official-route/new-run
# 中途失败时，修复原因后恢复已核验的阶段：
.tools/data-audit-venv/Scripts/python.exe scripts/doris/run_official_data_route.py `
  --resume --report-dir reports/official-route/new-run
```

入口核对原始 CSV 哈希，完成实际 JDBC 的全源码自测、两个特征构建、Decimal 独立数值参考、原生边界及真实数据结果、正式门禁、28 组各路径 30 次计时、并发、证据损坏拒绝及容器重启检查，最后生成中文 Markdown 和机器汇总。报告目录必须新建；`--resume` 核对最终 JAR、已发布目录和完成阶段，不用于忽略失败。

本机最终证据见 [官方数据路线执行与自测报告](../reports/official-route/2026-10-04/final/官方数据路线执行与自测报告.md)。`DIAGNOSTIC_PASS_FORMAL_BLOCKED` 表示当前项目规则下的计算诊断通过，正式源验收未通过；249,480 条未关联衍生记录以及官方字段口径仍须按解决路线图处理。原始数据、正式 CLI/HTTP 快照门禁和失败证据保留。

项目来源验证入口提供稳定输入标识、观察窗口和最多 20 个缺失样本的原因与实际相关日期。次数输入、次数结果和当前指标分别披露；解释超限或失败标为不完整，主查询沿用门禁与资源预算。19 项逐字段历史证据见 [逐字段验证与自测报告](../reports/project-fields/2026-10-05/逐字段验证与自测报告.md)。新的多指标／排名／查找／次数组合边界已纳入统一自测和普通 CI，最终矩阵与真实复跑入口见 [项目能力与交付](project-capabilities-v1.md)；真实结果状态以新目录 `project-summary.json` 为准。
