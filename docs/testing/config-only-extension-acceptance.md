# “核心代码 0 行改动”扩展验收

本验收针对已有注册类型和 lowering 的扩展。三份样例位于 `config/extensions/`：

| 扩展 | 仅新增内容 | 验证点 |
|---|---|---|
| `direct-field` | `FieldDefinition` | 新字段完成类型检查并生成白名单列引用 |
| `template-calculation` | `TEMPLATE` 函数 | 模板参数由编译器递归 lowering，用户值仍参数化 |
| `window-lowering` | `WINDOW_AVG` 函数 | 自动生成窗口、交易日回看和严格完整窗口策略 |

统一测试向量在 `src/test/resources/config-only-extensions/manifest.json`。测试框架先确认基础注册表
拒绝新指标，再加载单个扩展配置验证 SQL、禁止片段、回看长度和 10 次确定性编译。以后新增
同类指标只增加扩展 JSON，并在 manifest 增加向量，不增加 Java 测试。

## CI 门禁

`.github/workflows/config-only-extension.yml` 在扩展、规则或向量发生变化时自动执行：

1. `verify-config-only-extension.ps1` 比较 PR base/head；
2. Config 模式只允许扩展注册配置、规则配置和测试向量；
3. `src/main/java`、`src/main/antlr4`、编译流水线及既有核心类一律拒绝；
4. 运行统一扩展向量测试。

建议在代码托管平台将该检查设置为合并必需状态，并保护 workflow 与门禁脚本的变更权限。

## 全新计算语义

全新语义不计入“配置 0 代码”承诺。它必须放在独立 `plugins/<plugin-id>/` 模块，通过批准的
SPI 实现，并使用 CI 的 `Spi` 模式；该模式仍禁止修改现有 `src/main/java`、ANTLR 文法和编译
流水线。若当前 SPI 无法表达该语义，应先独立评审并版本化扩展 SPI，而不能在指标扩展 PR 中
顺带修改核心。

本地检查：

```powershell
./scripts/ci/verify-config-only-extension.ps1 `
  -BaseRef origin/main -HeadRef HEAD
mvn -Dtest=ConfigOnlyExtensionAcceptanceTest test
```
