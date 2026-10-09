# 编译器架构说明

本文描述当前设计；实际执行范围见 [能力说明](project-capabilities-v1.md)，完成的验收证据见 [项目状态](project-status.md)。

## 版本化入口

| 入口 | 用途 | 文法 |
|---|---|---|
| `stock-slot-v1` | 正式行情选股 DSL | `StockSlotDsl.g4` |
| `screen-v1` | 旧 `SCREEN ON` 兼容方言 | 独立旧文法与流水线 |

两套入口不会共用含义模糊的语法分支。正式 DSL 的主链路为：

```text
ANTLR parse tree → immutable Typed AST → semantic model → normalized rule hook
→ logical/access-path planning → parameterized layered Doris SQL
```

## 文法与 AST

正式文法位于 `src/main/antlr4/com/acme/dorisdsl/stockslot/StockSlotDsl.g4`。它定义 12 类核心
函数、空字符串槽位、算术与布尔优先级、比较/区间、`then`、集合表达式和提槽 `limit x,y`。
`StockSlotAst` 使用不可变 record 表示 `Literal/FunctionCall/Binary/Unary`、源码范围、集合、时间、
次数表达式及选择数量约束；`limit x,y` 不直接等同 SQL `LIMIT`。

## 类型系统

表达式类型固定为 `BOOLEAN/NUMBER/PERCENT/STRING/NULL/UNKNOWN`。函数参数类型来自注册表：
`SET/INDICATOR/DATE/DIRECTION/AGGREGATION/COUNT_EXPRESSION/PERIOD/SECURITY`。语义分析检查函数
元数、槽位必须为字符串、布尔/算术操作数、方向/聚合枚举、市场集合、`then` 右侧排名以及
时间、`CONS/EXIST` 和占位指标结构。

## 规则引擎

兼容方言的规则由 `rewrite-rules.json` 声明，包含阶段、优先级、前置条件、输入/输出节点、冲突
策略、等价性说明和最大迭代次数。规则版本可加载、激活和回滚；产物保存规则轨迹。正式 DSL
当前语义模型已经规范化，保留显式 rewrite 阶段作为稳定扩展点，禁止不受控 SQL 片段重写。

## 逻辑计划与窗口合同

计划节点包含扫描、连接、日期/市场过滤、窗口、前置过滤、排名、排序和投影。窗口产物同时
记录分区键、排序键、交易日单位、回看长度、停牌策略、新股窗口不足策略和空值策略。高级
lowering 使用多层 CTE，确保 `LAG`、聚合窗口、次数窗口和最终过滤不会非法嵌套或提前裁剪历史。

## 访问路径

`FULL_SCAN_REFERENCE` 永远走明细语义视图，用作结果基线；`OPTIMIZED` 仅在注册表中的指标、
窗口、快照日期和特征字段完全匹配时使用特征表。内置冻结日路径为 2026-04-14 的 MA60；
显式历史／滚动目录还能选择历史极值、MA20/60/120/250 及 250 观察行高低点路径，须核对快照、
清单、字段指纹和完整构建日期。无法等价混用时，公开编译入口捕获特征混用诊断并回退完整明细窗口。
项目来源验证路径按完整观察依赖裁剪窗口，保留参考模式；显式目录仅用于 SQL 编译／诊断，
不表示普通执行服务已经启用所有特征。细节见 [运行手册](runtime-guide.md)。

## 安全与确定性

表/列只来自加载期校验的注册表；用户值全部进入 JDBC bindings。编译器拒绝未知函数/指标、
多语句、超大输入和越界窗口。有界 LRU 缓存覆盖 AST、规范化模型、指标解析和稳定 SQL 模板；
同一 DSL、注册版本和编译器版本生成确定性相同的 SQL 与 bindings。
