# 行情选股 DSL → Doris SQL 编译器 V1

当前源码入口为 `main`，已合并 `competition-v1.0`。2026-10-10 已重建本机 JAR：334 项 Java 测试通过，8 项真实 Doris 集成测试未运行。请先阅读 [交付清单](DELIVERY.md)、[当前自测报告](SELF_TEST_REPORT.md)和[项目目录说明](docs/project-layout.md)。GitHub `project-delivery` 工作流会为每次推送生成绑定提交与证据的 JAR／源码 ZIP；真实数据与正式验收状态另行披露。

项目包含两个隔离的版本化入口：正式提槽 DSL 使用 `stock-slot-v1`，原有
`SCREEN ON` 方言保留为 `screen-v1` 兼容模式。兼容模式的完整编译链路为：

比赛适配的演进记录见[第一周基线](docs/competition/WEEK1_BASELINE.md)、
[第二周解析报告](docs/competition/WEEK2_PARSER.md)和
[第三周已核验指标安全子集](docs/competition/WEEK3_SEMANTICS.md)。完整实现仍要求指标目录、
单位和倍率经过人工复核。2026-10-04 已在独立 WSL2/Doris 中导入收到的三张官方数据表；当前跨表关联门禁未通过，尚不能宣称正式验收完成。

`ANTLR4 Parse Tree → 不可变 Typed AST → 语义检查 → 等价规则 → 逻辑计划 → AccessPathPlanner → 分层 Doris SQL`

当前版本已接入真实 Doris JDBC 执行：执行前强制校验已冻结且状态为
`VALIDATED` 的数据快照，只执行编译器生成的参数化 `SELECT`，并对 10 秒查询上限、
编译 P95 和 19 年等价计算加速倍数提供自动验收入口。最新执行层修复、隔离集成测试和官方数据回归见 [继续推进与自测报告](reports/continuation/2026-10-04/继续推进与自测报告.md)，前一轮记录见 [路线实施与自测报告](reports/route-implementation/2026-10-04/路线实施与自测报告.md)。历史交付材料中的结果不能替代本轮数据验收。

官方数据上的 12 类查询已另做热缓存性能诊断，测量与证据见 [性能诊断与下一步](reports/performance-diagnostic/2026-10-04/hot-30/性能诊断与下一步.md)。该诊断不登记快照，也不替代正式冷/热缓存和并发验收。

历史聚合及特征路径的前两轮记录见 [历史极值优化与自测报告](reports/history-optimization/2026-10-04/历史极值优化与自测报告.md)、[历史极值特征与自测报告](reports/history-features/2026-10-04/历史极值特征与自测报告.md)。这些目录保留各自工件与测量，不能混用不同 JAR 的结果。

最新路线已实现 MA20/60/120/250 和 250 观察行高低点的多日期特征及同一快照内增量构建，修复 MA60 与原始指标混合时的完整窗口回退。已验证 278 项 Java 测试、328 次 SQLite/Doris 边界执行、168,460 个原始数据独立数值/NULL 检查及 34 项真实数据结果。28 组共 1,680 次计时、60 次并发查询、损坏证据拒绝和重启持久性复验通过；19 年代表查询的热缓存 P95 比值为 86.74x。完整路线可用 `.tools/data-audit-venv/Scripts/python.exe scripts/doris/run_official_data_route.py --report-dir reports/official-route/new-run` 复跑，并自动输出 [官方数据路线执行与自测报告](reports/official-route/2026-10-04/final/官方数据路线执行与自测报告.md)。正式验收仍为 BLOCKED；下一步须取得官方关联/字段定义或补丁，创建符合契约的新快照，再完成正式验收。

## 最终交付入口

- 交付物总索引：[`DELIVERY.md`](DELIVERY.md)
- 当前自测摘要：[`SELF_TEST_REPORT.md`](SELF_TEST_REPORT.md)
- 当前项目能力与恢复：[`docs/project-capabilities-v1.md`](docs/project-capabilities-v1.md)
- 历史正式演示交付摘要：[`reports/final/FINAL_DELIVERY.md`](reports/final/FINAL_DELIVERY.md)
- CLI、HTTP、Docker 运行说明：[`docs/runtime-guide.md`](docs/runtime-guide.md)
- 编译器架构说明：[`docs/compiler-architecture.md`](docs/compiler-architecture.md)
- 指标注册与插件开发：[`docs/registry-plugin-guide.md`](docs/registry-plugin-guide.md)
- 首期数据指标范围冻结书：[`docs/phase1-data-indicator-scope-v1.md`](docs/phase1-data-indicator-scope-v1.md)
- 最终编译和查询表格：[`reports/final/compilation-and-query.md`](reports/final/compilation-and-query.md)
- 最终七步演示说明：[`docs/final-demo.md`](docs/final-demo.md)

一键构建、测试并启动 HTTP 服务：

```powershell
& .\scripts\build-test-start.ps1 -Mode Http
```

一键重建三张 Doris 表、导入 CSV、校验并登记固定快照：

```powershell
$env:DORIS_PASSWORD = '<装载账号密码>'
& .\scripts\doris\setup-load-validate.ps1 `
  -DataRoot '<Doris A股行情数据集目录>' `
  -SnapshotId 'stock-20060104-20260414-v1'
```

## 已实现

- ANTLR4 大小写不敏感文法、源码位置和结构化语法错误。
- 强类型 AST：价格、比率、百分比、成交量、日期、字符串和布尔类型。
- `BETWEEN`、`IN`、`AND/OR/NOT`、算术、比较、排序、复权和限制。
- `MA`、`CROSS_UP`、`PE_TTM`、`ROE_TTM`，以及 JSON 插件函数。
- 自动生成 `base → metrics → signals → final` CTE，避免嵌套窗口函数。
- 交易日回看范围、点时财务 Join、参数化 SQL、字段/函数白名单。
- 编译产物包含 Typed AST、逻辑计划、访问路径候选、SQL、绑定参数、规则轨迹和诊断。
- CLI、Markdown/JSON/SQL 输出、HTTP `/compile` API、Dockerfile。
- JUnit 单元/集成/安全/插件/性能冒烟测试。
- 独立的 `stock-slot-v1` ANTLR 文法、Typed AST、槽位语义模型和全语料分类器。
- 正式 DSL 覆盖 12 类函数、空字符串槽位、`and/or/then`、比较与约等于、
  指标四则运算、提槽 `limit x,y`、集合表达式、`CONS/EXIST`、中文时间和占位指标。

## 环境与构建

要求 JDK 21 或更高版本。仓库内已放置项目本地 Maven；如果移动项目时不携带 `.tools`，可重新下载：

```bash
./scripts/bootstrap-maven.sh
./mvnw test
./mvnw -DskipTests package
```

最终可执行文件为 `target/dsl-doris-compiler.jar`。

## 使用

仅解析主办方槽位 DSL，输出保留槽位原文和源码位置的 AST；不会执行或生成 SQL：

```bash
java -jar target/dsl-doris-compiler.jar parse-slot examples/competition_slot.dsl
java -jar target/dsl-doris-compiler.jar measure-slot-corpus build/competition-corpus/corpus.jsonl --max-failures 100 -o build/competition-corpus/slot-parse-coverage.json
```

安全子集 CLI 必须显式传入 `status=VERIFIED` 的人工核验目录；仓库示例 `examples/competition_verified_catalog.template.json` 为 `DRAFT`，会被拒绝。以下命令**只用合成测试数据演示流程，不能用于真实选股**：

```bash
java -jar target/dsl-doris-compiler.jar compile-slot-safe src/test/resources/safe-slot.synthetic.dsl --catalog src/test/resources/verified-slot-catalog.synthetic.json
```

赛事入口与下面的旧 `compile` 入口互相独立；`limit x,y` 在赛事入口中只保存两项数值（包括语料里的 `-1`），尚不做数据库分页解释。

生成 Markdown：

```bash
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl --format markdown -o result.md
```

输出 SQL 或完整 JSON：

```bash
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl --format sql
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl --format json
```

解析正式提槽 DSL（当前产出 AST 和语义模型，不把未完成的数据映射伪装成 SQL）：

```bash
java -jar target/dsl-doris-compiler.jar compile examples/stock-slot-v1.dsl \
  --dsl-version stock-slot-v1 --format json
```

把已具备真实数据契约的正式 DSL 子集编译为参数化 Doris SQL：

```bash
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql \
  examples/stock-slot-v1.dsl --format json
```

在已装载并登记的冻结快照上执行正式 DSL：

```powershell
$env:DORIS_PASSWORD = '<本机 Doris 用户密码>'
java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql `
  examples/registry-smoke.dsl --user dsl_runtime_reader `
  --snapshot-id stock-20060104-20260414-v1 `
  --timeout-seconds 10 --max-rows 100 `
  -o reports/performance/doris-execution-smoke.json
```

生产式执行必须使用只读账号。先以管理员身份复制并替换
[`data/doris/ddl/007_runtime_guardrails.template.sql`](data/doris/ddl/007_runtime_guardrails.template.sql)
中的用户名和密码占位符，再执行该脚本；它会配置仅 `SELECT_PRIV` 的账号、独立 Workload
Group，以及 100 万实际扫描行/10 秒的 Doris 端取消策略。不要提交替换后的含密码文件。

完整的受控执行和 Markdown 报告示例：

```powershell
$env:DORIS_PASSWORD = '<只读账号密码>'
java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql `
  examples/performance-long-cycle.dsl `
  --user dsl_runtime_reader `
  --snapshot-id stock-20060104-20260414-v1 `
  --timeout-seconds 10 --max-scan-rows 1000000 `
  --max-return-rows 1000 --max-rows 100 `
  --format markdown -o reports/e2e/doris-execution.md
```

输出记录编译、应用排队、EXPLAIN 门禁、Doris 执行至结果可读、结果读取和总耗时，
同时保存 SQL SHA-256 指纹、快照/契约/清单版本、编译器版本、EXPLAIN 和 Query Profile
摘要。SQL 与 EXPLAIN 均复用 JDBC 占位符绑定，用户值不会拼进 SQL。

启动带 Doris 执行能力的 HTTP 服务：

```powershell
$env:DSL_HTTP_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
java -jar target/dsl-doris-compiler.jar serve-doris `
  --user dsl_runtime_reader --bind-host 127.0.0.1 --http-port 8080
```

```bash
curl -X POST http://127.0.0.1:8080/execute \
  -H "Authorization: Bearer $DSL_HTTP_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary '{"dsl":"indicator('\''沪'\'', '\'''\'', '\''60日均线'\'', '\''2026-04-14'\'', '\'''\'', '\'''\'', '\'''\'') > 1 limit 0,100","snapshotId":"stock-20060104-20260414-v1","maxRows":100,"format":"markdown"}'
```

`/compile` 和 `/execute` 均使用服务端环境变量 `DSL_HTTP_TOKEN` 配置的 Bearer 令牌；
可以通过 `--auth-token-env` 更换变量名。令牌须为至少 32 字符的随机值，不配置则服务拒绝启动。
`serve` 只授予编译权限，`serve-doris` 授予编译和执行权限；请求 JSON 不接受用户身份或权限。
`/execute` 的错误契约为：未登录 `401`、无权限 `403`、语法错误 `400`、语义错误 `422`、
请求体超过 1 MiB `413`、安全配额 `429`、Doris
错误 `502`、数据不可用 `503`、超时 `504`。服务端配置的返回行上限优先于请求中的
`maxRows`。

旧的性能基准命令仍可在本机无密码测试实例中显式使用 `--user root
--allow-empty-password`；受控 `execute-stock-slot-sql` 和 `serve-doris` 会检查授权并拒绝含
管理、建表、装载、修改或删除权限的账号。执行器拒绝超过 10 秒的业务查询超时配置。

复跑长周期性能验收：

```powershell
java -jar target/dsl-doris-compiler.jar benchmark-doris `
  examples/performance-long-cycle.dsl `
  --user root --allow-empty-password --warmup 1 --iterations 5 `
  --timeout-seconds 10 --baseline-timeout-seconds 120 `
  -o reports/performance/doris-benchmark-long-cycle-v1.json
```

运行“先基准、后选优化”的 12 类冷热缓存矩阵：

```powershell
$env:DORIS_PASSWORD = '<基准只读账号密码>'
java -jar target/dsl-doris-compiler.jar benchmark-matrix `
  --user dsl_benchmark_reader --iterations 30 --cold-restart-container doris
```

矩阵定义、冷/热口径、证据目录和输出说明见
[`benchmarks/README.md`](benchmarks/README.md)。基准程序不接受少于 30 次的配置，并在每轮
逐行验证全表扫描参考与优化查询结果完全一致。

验收同时要求加速路径与等价全周期窗口计算返回完全相同的证券及顺序，否则立即失败。
当前基准、环境、结果及边界见
[`reports/performance/PERFORMANCE_REPORT.md`](reports/performance/PERFORMANCE_REPORT.md)。

黄金集三层正确性闭环的口径和复跑命令见
[`accuracy/README.md`](accuracy/README.md)。
函数、窗口、停牌、空值和新股处理的冻结语义见
[`docs/stock-slot-function-semantics-v1.md`](docs/stock-slot-function-semantics-v1.md)。

加载插件（不修改编译核心）：

```bash
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl \
  --plugin examples/custom-plugin.json --format json
```

启动 API：

```bash
export DSL_HTTP_TOKEN="$(openssl rand -hex 32)"
java -jar target/dsl-doris-compiler.jar serve --host 127.0.0.1 --port 8080
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/compile \
  -H "Authorization: Bearer $DSL_HTTP_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary '{"dsl":"SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5"}'

curl -X POST http://127.0.0.1:8080/compile \
  -H "Authorization: Bearer $DSL_HTTP_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary '{"dslVersion":"stock-slot-v1","dsl":"indicator('\''沪'\'', '\'''\'', '\''10日均线'\'', '\''今天'\'', '\'''\'', '\'''\'', '\'''\'') > 5 limit 0,10"}'
```

编译基准与整套自测：

```bash
java -jar target/dsl-doris-compiler.jar benchmark examples/basic.dsl --iterations 5000
./scripts/self-test.sh
```

Windows 上的一键自动化验收入口为：

```powershell
./scripts/test-all.ps1 -MavenExecutable mvn.cmd
```

加入固定 Doris 快照差分可追加 `-WithDoris`；完整 19 年冷热性能矩阵再追加
`-RunNineteenYearBenchmark`。覆盖矩阵及“未连接数据库不得伪报通过”的规则见
[`docs/automated-testing.md`](docs/automated-testing.md)。

正式 `stock-slot-v1` 的复杂语料性能门禁（预热后 5,000 次，缓存旁路 P95 必须小于 50ms）：

```powershell
java -jar target/dsl-doris-compiler.jar benchmark-stock-slot-compiler `
  --warmup 1000 --iterations 5000 --p95-threshold-ms 50
```

它会分别输出解析、语义、重写、规划、SQL 生成和总耗时的 P50/P95/P99/最大值，以及每次
编译内存分配和有界缓存统计。完整口径见
[`docs/compiler-performance.md`](docs/compiler-performance.md)，最近一次实测见
[`reports/compiler-performance/latest.md`](reports/compiler-performance/latest.md)。

## DSL 示例

```text
SCREEN ON 2026-08-07
WHERE PE_TTM() BETWEEN 0 AND 20
  AND ROE_TTM() >= 15%
  AND CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
  AND MARKET IN ['SH', 'SZ']
ADJUST FORWARD
ORDER BY TURNOVER_RATE DESC
LIMIT 100
```

正式提槽 DSL 的 `limit 0,10` 是选取数量上下界，不等于 SQL `LIMIT 10`；两者
位于不同 AST 中。`then` 的优先级低于 `or`，且语义检查要求其右侧包含 `rank`。

## 声明式规则

`screen-v1` 的等价重写由版本化规则目录驱动，规则声明包含前置条件、输入/输出节点类型、
阶段、优先级、冲突策略、等价性说明和最大迭代次数。编译产物记录所用规则版本和完整轨迹。
可通过 `--rules` 加载外部目录、通过 `--rule-version` 固定或回滚版本；详细契约见
[`docs/declarative-rule-engine.md`](docs/declarative-rule-engine.md)。

已有注册类型/lowering 的“核心代码 0 行改动”验收包含直接字段、模板计算和窗口指标三类样例，
并由 PR 门禁自动拒绝核心目录变更，详见
[`docs/config-only-extension-acceptance.md`](docs/config-only-extension-acceptance.md)。

## 插件契约

`examples/custom-plugin.json` 演示通过 `TEMPLATE` 注册 `ABS_CHANGE`。插件模板只能是表达式片段；加载器拒绝分号、注释和 `SELECT`，DSL 的字段和函数也必须通过白名单解析。

V1 支持 `COLUMN`、`WINDOW_AVG`、`CROSS_UP` 和 `TEMPLATE` 四类 lowering。下一版应扩展前缀和、特征表新鲜度元数据、Doris 能力矩阵和 EXPLAIN/Profile 闭环。

## 目录

- `src/main/antlr4`：DSL 文法。
- `src/main/antlr4/.../stockslot`：正式 `stock-slot-v1` 文法。
- `src/main/java/.../stockslot`：正式 DSL AST、语义分析和语料审计器。
- `src/main/java/.../ast`：版本化 AST 数据结构。
- `semantic`、`rewrite`、`plan`、`sql`：确定性编译核心。
- `src/main/resources/registry.json`：字段、指标、表映射和 lowering 元数据。
- `src/main/resources/rewrite-rules.json`：版本化声明式规则目录和回滚版本。
- `src/test`：正确性、安全性、插件、HTTP 和性能测试。
- `examples`：可运行 DSL 与插件样例。

## 当前边界

- 编译器自身不接受任意 SQL 片段；数据库执行由正确率/装载验收脚本显式完成。
- `stock-slot-v1` 已完成解析和语义分类；只有具备真实指标映射、确定日期语义的首期子集
  才能进入 `compile-stock-slot-sql`。其他表达式返回稳定的不支持分类，不生成伪 SQL。
- 访问路径只在注册表中的窗口、字段和冻结日期完全匹配时选用特征表；不匹配时安全回退到明细表。
- 当前真实加速路径只覆盖冻结验收日 `2026-04-14` 的 `60日均线`；其他窗口或日期安全回退
  到明细表，特征表和历史指标混用会返回 `EXECUTION_FEATURE_MIXED`，不会静默生成错误 SQL。
- 真实表名、字段、倍率、空值策略和 lowering 均由版本化注册表约束；新增已有 lowering 类型
  的普通指标无需修改核心 Java 代码。
- 仓库内性能数字针对本机单节点 Doris 和固定快照，不等同于其他硬件、并发或数据版本的保证。
