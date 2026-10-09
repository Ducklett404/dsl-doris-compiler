# 当前构建与自测报告

验证时间：2026-10-10（Asia/Shanghai）。被测 Java 源码：`main` 合并提交 `8c202a12712f800a1aab60580d313b350904bcf6`；应用版本 `0.1.0`。后续文档、包装脚本和交付工作流整理不改变编译器 Java 源码。

## 本机重建结果

| 项目 | 结果 |
|---|---|
| JDK／Maven | Oracle JDK 21.0.8／Maven 3.9.16 |
| 构建 | 重新生成文法、编译主代码与测试，离线 `package` 成功 |
| JUnit | 342 项：334 通过，0 失败，0 错误，8 跳过 |
| 跳过项 | 1 项 Doris EXPLAIN 和 7 项受控执行集成测试；本轮未启用真实数据库测试 |
| 编译热路径 I/O | JFR 检查通过 |
| 复杂 SCREEN DSL JMH P95 | 约 0.365 ms，低于 50 ms；本机测试桶结果 |
| JAR 黑盒检查 | `--help` 和 3 个示例编译通过 |

示例分别为 `project-basic.dsl`、`final-demo-complex.dsl` 的 `compile-stock-slot-sql`，以及 `basic.dsl` 的 `compile`。

本机最初的沙箱测试不能建立回环连接；允许本机测试后，使用英文临时目录、禁用不可用 Unix socket 临时路径、优先 IPv4，全部非数据库测试通过。这些属于运行环境参数，没有放宽产品权限或验收门禁。

## 本机 JAR

- 文件：`target/dsl-doris-compiler.jar`，8,460,142 字节。
- 构建时间：2026-10-10 02:07:51 +08:00。
- SHA-256：`da6daa3e577f2fd9519c9fbf06d9307643794513c6c35e7ef804d4e58f7afe1d`。
- 机器摘要：[build-verification.json](reports/build/2026-10-10/build-verification.json)。完整日志和示例输出保留在本机 `build/jar-rebuild-20261010-020451/`。

GitHub 会针对整理后的每个提交重新构建并执行便携验收。该 JAR 的哈希以相应下载包 manifest 为准，不能沿用上述本机 JAR 哈希。

## 验收边界与历史记录

本轮重建没有执行真实 Doris 数据验收、SQL 10 秒门禁或 19 年查询加速复测。历史查询加速及官方数据诊断见 [2026-10-04 路线报告](reports/official-route/2026-10-04/final/官方数据路线执行与自测报告.md)，仅适用于其原始工件和数据环境。正式验收仍受数据契约与外部证据条件限制。

早期 V1 的 7 项测试报告已归档到 [2026-08-09 历史自测](docs/history/self-test-2026-08-09.md)，不能作为当前测试数量。当前交付入口见 [DELIVERY.md](DELIVERY.md)。
