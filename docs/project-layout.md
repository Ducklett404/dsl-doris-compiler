# 项目目录与阅读顺序

当前源码统一在 `main`。先读 [交付清单](../DELIVERY.md)、[当前自测报告](../SELF_TEST_REPORT.md)和[项目能力范围](project-capabilities-v1.md)，再按用途进入对应目录。

| 目录／文件 | 用途 |
|---|---|
| `src/` | 编译器、CLI、HTTP、JDBC 执行层、文法、注册表及 Java 测试 |
| `executor-doris/` | 独立 Doris 执行器模块及测试 |
| `config/` | 冻结验收范围、查询矩阵、规则与模板配置 |
| `examples/` | 可编译 DSL 和演示输出 |
| `docs/` | 架构、运行、函数语义、项目能力和恢复说明 |
| `docs/history/` | 历史自测、缺陷检查与规划；不作为当前验收结论 |
| `scripts/` | 构建、自测、审计、验收、打包及恢复入口 |
| `accuracy/`、`benchmarks/` | 正确性基准和编译／查询性能定义 |
| `data/doris/` | DDL、数据契约、快照 manifest 和历史装载证据 |
| `reports/` | 按批次保留的机器报告与说明；以运行日期、JAR 哈希和快照区分 |
| `outputs/` | 既有输出文件，结合其生成说明使用 |
| `.github/workflows/` | 自动测试、性能门禁、真实数据验收与交付包构建 |
| `mvnw`、`mvnw.cmd` | Unix／Windows Maven 入口；优先使用本机 `.tools` 中的 Maven |
| `target/` | 本机 JAR、编译缓存和已有审计数据库，不提交 Git |
| `build/` | 本机构建记录、交付包和归档日志，不提交 Git |
| `.tools/`、`.mvn-cache/` | 本机工具与依赖缓存，不提交 Git |

本轮根目录日志已归档到 `build/local-logs/2026-10-10/`，没有丢弃历史文件。原始 CSV、数据库、私有配置仍留在本机；发布交付包由白名单脚本选择源码与本批证据。

## Windows 构建

准备 JDK 21 和 Maven 3.9+，在项目根目录执行：

```powershell
$env:JAVA_HOME = '<JDK 21 安装目录>'
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
.\mvnw.cmd -B package
java -jar target/dsl-doris-compiler.jar --help
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/project-basic.dsl --format json
```

若当前 Windows 环境的 Java 临时文件或本机通信测试受路径影响，可使用本轮已验证的参数：

```powershell
.\mvnw.cmd -B '-Dtest.jvm.args=-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets -Djava.net.preferIPv4Stack=true' package
```

`java.io.tmpdir` 应使用可写的英文路径。不要直接清空整个 `target/`：其中可能保存独立审计数据库和历史验收结果。

## GitHub 下载

每次推送 `main` 会运行 `project-delivery` 工作流。成功运行的 Artifacts 中，`project-delivery-<提交 SHA>` 提供可执行 JAR、源码与本批便携验收 ZIP、manifest 和 SHA-256 校验文件；保存 30 天，需要长期保留时及时下载。

交付包状态 `PASS_OFFLINE_REAL_NOT_RUN` 表示便携验收通过。真实 Doris、官方数据和正式验收结果须单独运行，不能由下载包的生成成功推定。
