# V1 自测报告

测试时间：2026-08-09 16:06（Asia/Shanghai）  
运行环境：macOS arm64、Oracle JDK 24（以 `--release 21` 编译）、Maven 3.9.16  
被测版本：0.1.0

## 结论

`./scripts/self-test.sh` 完整执行成功，最终标记为 `SELF_TEST_OK`。

| 检查项 | 结果 |
|---|---:|
| JUnit 测试 | 7/7 通过 |
| 编译器核心测试 | 4/4 通过 |
| JSON 插件零核心改动 | 通过 |
| HTTP `/health` 与 `/compile` | 通过 |
| 安全与错误诊断 | 通过 |
| fat JAR CLI 黑盒编译 | 通过 |
| 1,000 次编译 P50 | 0.047 ms |
| 1,000 次编译 P95 | 0.110 ms |
| 1,000 次编译 P99 | 0.265 ms |

## 覆盖范围

- 复杂示例 DSL 被解析为 Typed AST。
- 生成 SQL 包含 `base`、`metrics`、`signals` 分层，两个 MA 只计算一次。
- `CROSS_UP` 使用独立 `LAG` 层，未生成嵌套窗口函数。
- 字符串、百分比、日期和数值均进入绑定参数，未拼入 SQL。
- 未注册函数、类型不匹配、超大 LIMIT 和 SQL 注入字符会被拒绝。
- 外部 JSON 新增 `ABS_CHANGE` 后可直接编译，编译核心无需修改。
- HTTP 成功响应和结构化 400 错误均经本机回环请求验证。
- Markdown、JSON、SQL 三种 CLI 输出均通过 fat JAR 黑盒运行。

## 构建产物

- 文件：`target/dsl-doris-compiler.jar`
- 大小：约 3.2 MB
- SHA-256：`e534235d1b4b026571b85efbd60e26f092821a451d7ce42df68e860fbde16883`

## 尚未验证

当前工作区没有比赛数据和 Doris 集群，因此没有执行 Doris 方言解析、`EXPLAIN`、Query Profile、19 年数据查询或 10 倍加速验收。V1 对这些指标只提供 SQL 结构、访问路径接口和可重复基准入口，不将其标记为已达成。
