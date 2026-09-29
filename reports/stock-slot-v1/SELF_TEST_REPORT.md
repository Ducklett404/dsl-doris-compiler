# stock-slot-v1 正式 DSL 自测报告

日期：2026-09-18  
DSL 版本：`stock-slot-v1`  
语料文件 SHA-256：`b5603a9bf9db60a76abe46ec6360c4ab09e26e5c10fac3c9dbccd92615963623`

## 结论

工作簿共有 5,845 个数据行，其中 `slot_dsl` 非空行恰好为 5,799。全部非空
DSL 均获得确定分类：5,770 条成功解析，29 条为明确不支持，无法解释的内部
错误为 0。成功解析率为 99.50%。

## 覆盖能力

- 12 类规范函数及所有空字符串参数。
- 括号、`and`、`or`、`then` 和固定运算优先级。
- `= != > >= < <= ~= between`。
- 函数/指标结果之间的 `+ - * /`。
- 独立于 SQL 的尾部 `limit x,y` 数量范围。
- market、filter_scope、keywords、select_type 中的 `| & ^`，包括前缀排除 `^`。
- `CONS/EXIST + 比较符 + 次数 + 单位` 的结构化语义。
- 中文普通时间、财报期及 `开始/前/后 + 阿拉伯数字 + 单位` 偏移。
- `X日均线`、`RSI(N)`、`我的自选股_STR分组` 的实例化元数据。

## 29 条明确不支持项

不支持项均违反规范文档本身的格式约束，没有以容错改写掩盖源语料问题：

| 原因 | 涉及行/诊断数 | 说明 |
|---|---:|---|
| `COUNT_EXPRESSION` | 13 条 DSL / 15 个诊断 | 使用 `天/分钟`、小数次数或 `1-2月` 等区间次数，规范只允许数字/每及年、季度、月、周、日 |
| `DSL_SYNTAX` / `STOCK_SLOT_SYNTAX` | 10 条 DSL | 多余双引号、缺失引号、多余右括号、前置 `and`，或未按字符串书写 between 区间 |
| `THEN_REQUIRES_RANK` | 4 条 DSL | `then` 右侧没有 `rank`，违反“then 仅可用于 rank 前”的规则 |
| `BETWEEN_RANGE` | 2 条 DSL | 区间内部使用句点而非逗号，例如 `'[10%.20%]'` |

个别 DSL 同时产生多个诊断，因此诊断计数之和可能大于 29。逐行结果保存在
`classification.jsonl`，每一行包含工作簿原始行号、`PARSED/UNSUPPORTED` 状态
和结构化诊断。

## 自动化验证

- Maven/JUnit：18 个测试，0 失败，0 错误。
- 正式入口：CLI `--dsl-version stock-slot-v1` 和 HTTP `dslVersion=stock-slot-v1`。
- 兼容入口：未指定版本时仍使用 `screen-v1`，原测试全部通过。
- 全量审计：`total=5799`、`unexplained=0`。

## 当前边界

本阶段完成正式 DSL 的解析、Typed AST 和语义分类。正式 DSL 尚未统一映射到
真实指标数据契约，因此不会生成虚假的 Doris SQL；SQL lowering 是下一阶段，
必须以每个验收指标的唯一数据定义为前置条件。
