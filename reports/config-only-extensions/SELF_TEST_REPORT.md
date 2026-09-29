# “核心代码 0 行改动”验收报告

日期：2026-09-27

## 结论

三类扩展均只通过注册配置和测试向量接入；三份指标扩展对 `src/main/java`、ANTLR 文法、
编译流水线和既有核心类的改动均为 0 行。统一验收与全量回归通过。

## 扩展结果

| 扩展 | 配置 | 基础注册表 | 加载扩展后 | 结果 |
|---|---|---|---|---|
| 直接字段 `CLOSE_MIRROR` | `FieldDefinition` | `UNKNOWN_FIELD` | 生成白名单列引用 | 通过 |
| 计算指标 `PRICE_SPREAD` | `TEMPLATE` | `UNKNOWN_FUNCTION` | 参数递归 lowering、值参数化 | 通过 |
| 窗口指标 `SMA` | `WINDOW_AVG` | `UNKNOWN_FUNCTION` | 10 日窗口及交易日回看 | 通过 |

每个扩展额外连续编译 10 次，完整编译产物一致。

## CI 门禁自测

| 场景 | 预期 | 实际 |
|---|---|---|
| 仅扩展配置、规则配置和向量 | 允许 | 退出码 0，`coreChanges=0` |
| 扩展同时修改 `DslCompiler.java` | 拒绝 | 退出码 1，准确列出违规文件 |
| 独立 `plugins/<id>/` SPI 模块且不改核心 | 允许 | 退出码 0，`mode=Spi` |

CI workflow 会对相关 PR 自动执行同一门禁与统一测试。生产仓库应将该 workflow 配置为
合并必需检查，并保护 workflow/门禁脚本自身的修改权限。

## 完整回归

- Maven：137 tests，0 failures，0 errors，0 skipped。
- fat JAR：构建成功。
- `git diff --check`：无空白错误；仅有 Windows LF/CRLF 提示。

## 自测发现并修正的问题

初次向量没有声明复权模式，但期望 SQL 使用 `q.close_qfq`；编译器按 `ADJUST NONE` 正确生成
`q.close`。已将测试 DSL 明确为 `ADJUST FORWARD`，避免把测试口径错误误判为核心缺陷。
