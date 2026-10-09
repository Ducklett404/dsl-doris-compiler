# 行情选股 DSL → Doris SQL 编译器

将正式选股槽位 DSL 编译为参数化 Doris SQL，提供类型检查、窗口与排名计算、受控查询执行、结果解释和可追溯的测试／交付流程。源码入口为 `main`，`competition-v1.0` 已合并。

**当前状态：可构建和演示；当前 JAR 的真实数据验收尚未复测，正式验收仍受数据契约与评测条件限制。**
2026-10-10 本机重建：342 项 Java 测试中 334 通过、8 项真实 Doris 集成测试跳过，零失败、零错误。历史数据和性能报告按原批次使用，不作为新 JAR 的实时结果。

## 阅读入口

| 目的 | 入口 |
|---|---|
| 查看统一状态与证据日期 | [项目状态](docs/project-status.md) |
| 对照比赛要求、准备提交 | [赛题要求与证据对照](docs/delivery/competition-readiness.md) |
| 取得 JAR、源码包与自测记录 | [交付清单](docs/delivery/README.md)、[当前自测](docs/delivery/self-test.md) |
| 了解实际支持范围 | [能力说明](docs/project-capabilities-v1.md)、[冻结范围](docs/phase1-data-indicator-scope-v1.md) |
| 构建、运行和展示 | [运行手册](docs/runtime-guide.md)、[演示说明](docs/final-demo.md) |
| 浏览文档与目录 | [文档索引](docs/README.md)、[目录说明](docs/project-layout.md) |

## 当前能力

- 正式入口 `stock-slot-v1` 使用独立 ANTLR 文法、不可变 AST 和语义模型；旧 `SCREEN ON` 方言作为 `screen-v1` 兼容入口保留。
- 解析层覆盖 12 类函数；实际执行以冻结范围为准：19 项指标、MA／RSI、11 类函数、沪深京市场及明确日期。解析接受不等于可执行覆盖或结果正确率。
- 支持指标筛选、算术和布尔组合、窗口、交叉信号、历史极值、位置、次数、候选集排名、跨证券读取和数量上界；具体 NULL、单位和日期限制见能力说明。
- SQL 使用绑定参数、字段／函数白名单和分层 CTE；产物包括 AST、语义／规则信息、逻辑计划、SQL、参数及诊断。
- 受控 Doris 执行检查只读账号、数据来源、扫描／内存／返回限制和查询超时，并提供 JSON／Markdown 输出。
- 访问路径包含明细参考、项目窗口裁剪、冻结日 MA60 及显式历史／滚动特征目录。目录必须匹配快照、清单、字段指纹和日期；无法等价组合时回退明细。显式特征目录用于 SQL 编译和诊断，不直接等于普通执行服务已启用全部优化。
- 已有注册类型的指标／函数可通过配置扩展；全新计算语义须另行实现与验证，不能承诺任意新函数均无需代码。

## 快速构建与编译

要求 JDK 21、Maven 3.9+。`mvnw`／`mvnw.cmd` 优先调用本机 `.tools` 中的 Maven，否则调用已安装的 Maven；工具缓存不随源码分发。

```powershell
.\mvnw.cmd -B package
java -jar target/dsl-doris-compiler.jar --help
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/project-basic.dsl --format json
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/final-demo-complex.dsl --format sql
```

`compile-stock-slot-sql` 输出 JSON 或 SQL；查询执行的 `execute-stock-slot-sql` 可输出 Markdown，需满足数据与权限条件。

Unix 可先执行 `./scripts/bootstrap-maven.sh`，再运行 `./mvnw -B package`。产物统一为 `target/dsl-doris-compiler.jar`。

正式 DSL 示例：

```text
indicator('沪', '', '收盘价', '2026-04-14', '', '', '') > 10 limit 0,100
```

`limit x,y` 中 x 为数量下界声明，y 为数量上界；不是 SQL OFFSET。本版 SQL 使用非 -1 的 y 限制数量，执行器另有返回行预算。

## HTTP 与 Docker

```powershell
$env:DSL_HTTP_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
java -jar target/dsl-doris-compiler.jar serve --host 127.0.0.1 --port 8080
```

`serve` 提供编译服务；`serve-doris` 增加受控执行能力，需另备 Doris、只读账号和有效来源证据。
`Dockerfile`／`docker-compose.yml` 使用已构建 JAR 启动编译器服务，数据库需另行准备。详细请求和环境配置见运行手册。

## 验收与交付

```powershell
python -m pip install -r scripts/doris/requirements-selftest.txt
python scripts/doris/run_project_acceptance.py --report-dir build/project-acceptance/new-portable --java java
```

便携验收完成后的 `PASS_OFFLINE_REAL_NOT_RUN` 只证明本批离线检查通过。真实项目验收须显式使用 `--with-doris` 和专用环境、原始文件、独立参考；完整命令见能力说明。项目证书不会自动登记正式 `VALIDATED` 快照。

GitHub `project-delivery` 工作流成功后提供绑定该次源码、JAR 和便携证据的 Artifacts。原始 CSV、审计数据库、工具缓存和私有凭据需单独准备。修改源码或文档后应针对新身份重新验收和打包，不能沿用旧包的校验和。

## 数据与评测边界

三份 CSV 共 19,826,855 行。现有数据保留 249,480 条未关联衍生行及 3,487 条价格范围警告；单位、复权和资金哨兵沿用项目规则，尚缺完整官方确认。行业字段全空；财务、概念／指数成分、基金／ETF／债券、海外市场和部分相对日期等不属于当前执行范围。

≥95% 正确率、≥10 倍加速、编译 P95 <50ms、SQL ≤10 秒是评估目标。历史内部通过、解析接受率、便携 CI 或某条热缓存查询的收益，均不能单独证明比赛全范围达标。当前证据与剩余事项统一见项目状态和赛题对照材料。
