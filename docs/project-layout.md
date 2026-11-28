# 项目目录与阅读顺序

评审比赛结果，从 [参赛验收总览](../reports/competition-review/2026-11-29/README.md) 选择受测版本、报告和复现命令。运行原型，从 [运行手册](runtime-guide.md) 和 [DSL 示例](../examples/README.md) 开始。

## 开发与运行

| 位置 | 内容 |
|---|---|
| [src/](../src/) | 主 Maven 模块的 Java 实现、ANTLR 文法、工作台资源和测试 |
| [executor-doris/](../executor-doris/README.md) | 独立 Doris 执行器 Maven 模块及测试 |
| [config/](../config/) | 验收范围、查询矩阵，以及按类型组织的扩展配置 |
| [data/doris/](../data/doris/README.md) | Doris DDL、字段契约、快照清单与装载记录 |
| [examples/](../examples/README.md) | 根层两个正式 DSL 入门示例，子目录按正式方言、SCREEN 方言和早期解析原型归类 |
| [scripts/](../scripts/README.md) | 构建、自测、语料准备、Doris 验收与打包入口 |
| [根 POM](../pom.xml)、[Unix](../mvnw) 和 [Windows](../mvnw.cmd) Maven 入口 | 构建编译器并生成可执行 JAR |
| [Dockerfile](../Dockerfile)、[Compose](../docker-compose.yml) | 启动编译 HTTP 服务 |

## 测试、文档与交付

| 位置 | 内容 |
|---|---|
| [accuracy/](../accuracy/README.md) | 正确性测试使用的黄金集和边界夹具 |
| [benchmarks/](../benchmarks/README.md) | 编译性能语料和 Doris 基准查询矩阵 |
| [reports/](../reports/README.md) | 按问题查找实测报告、原始样本、SQL 及哈希记录。早期数据盘点见 [指标工作簿](../reports/history/indicator-inventory/DSL指标数据契约.xlsx) |
| [docs/](README.md) | 运行手册、项目状态与主题索引；架构在 [architecture/](architecture/)，测试方法在 [testing/](testing/) |
| [docs/delivery/](delivery/README.md) | 交付清单、历史构建自测及赛题要求对照 |
| [docs/history/](history/) | 历史规划、优化待办和早期检查 |
| [.github/workflows/](../.github/workflows/) | 自动测试、性能门禁、数据验收与交付包构建 |

构建产物位于 `target/`，临时验收与本地交付包放在 `build/`。`.tools/`、`.mvn-cache/` 和临时导出目录 `outputs/` 由 Git 忽略。比赛证据随批次放入 `reports/`，长期维护的参考资料放入对应文档目录。

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
