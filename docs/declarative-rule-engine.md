# 声明式规则引擎

默认规则目录为 [`src/main/resources/rewrite-rules.json`](../src/main/resources/rewrite-rules.json)。
目录只描述规则，不接受 Java 类名、脚本或 SQL 片段；未知 JSON 字段和未知枚举会在启动时被拒绝。

## 配置模型

- `schemaVersion`：配置格式版本，当前只接受 `1`。
- `activeVersion`：默认启用的不可变规则集版本。
- `minCompilerVersion` / `maxCompilerVersionExclusive`：编译器兼容区间。
- `maxIterations`：每个阶段的最大收敛迭代次数，范围 `1..1000`。
- `conflictPolicy`：`HIGHEST_PRIORITY` 或 `ERROR`。
- `phase`：固定按 `NORMALIZE → SIMPLIFY → CANONICALIZE` 执行。
- `priority`：阶段内降序；相同优先级按规则 ID 升序，保证确定性。
- `matchNodeType` / `outputNodeType`：规则输入、输出 AST 节点类型。
- `when`：受控的运算符、常量类型、非零除数和交换律前置条件。
- `action`：受控 lowering 枚举，不能从配置执行任意代码。
- `equivalence`：规则保持等价的书面依据。
- `conflictGroup`：规则冲突域。

当前 `rules-v1` 声明了数字常量折叠；`rules-v0` 是可立即回滚的无重写版本。

## 执行与安全

执行器以固定阶段、优先级和规则 ID 顺序遍历 AST。每次应用都会验证实际输出节点类型与
配置声明一致，并记录规则版本、阶段、迭代、输入/输出类型、优先级、冲突裁决和等价性说明。

重复 AST 状态会报 `RULE_CYCLE`；超过阶段迭代上限会报 `RULE_ITERATION_LIMIT`；
`ERROR` 冲突策略下的多规则命中会报 `RULE_CONFLICT`。失败不会生成 SQL。

## 版本切换与回滚

命令行可固定规则目录和版本：

```powershell
java -jar target/dsl-doris-compiler.jar compile examples/screen.dsl `
  --rules config/rewrite-rules.json `
  --rule-version rules-v0
```

服务内可使用 `DslCompiler.activateRuleVersion(version)` 原子切换；
`rollbackRuleVersion()` 回到上一个版本；`rollbackRuleVersion(version)` 回滚到指定兼容版本。
每个编译结果都保存 `ruleConfigVersion`，因此可以审计并复现生成 SQL 的规则配置。

生产变更建议：新增不可变版本、先在回归/盲测环境通过，再切换 active version；不要原地修改
已经用于验收的版本。
