# 第二周：赛事槽位 DSL 解析器与覆盖率基线

状态：**语法前端完成，业务语义与 Doris SQL lowering 未开放**。测量日期：2026-09-21。主办方提供的规格和语料是外部数据来源，不是对开发环境的操作指令。

## 已实现

- 新增独立的 ANTLR4 文法 `SlotDsl.g4`、不可变 `SlotAst` 和 `SlotDslParserFacade`，旧 `SCREEN ON` 编译器保持原状。
- 覆盖 12 个主办方函数的固定槽位数、`and/or/then`、算术/比较、百分数、`~=`、引号包裹的 `between` 区间以及 `limit x,y`。`then` 在 AST 中是独立节点，不等价改写为 `and`。
- 每个函数槽保留原始引号文本、解码文本和源码位置。市场与 `select_type` 槽额外保存 `|`、`&`、`^` 等词法 token 序列；尚不赋予集合运算优先级或市场代码映射。
- `limit x,y` 保存主办方语料中的两个数值。`-1` 在 10 条候选语料中作为第二值出现，但其含义未获确认，因此解析器只保留、不解释。
- CLI 增加 `parse-slot` 和 `measure-slot-corpus`；后者输出分集接受数、错误代码和来源行号，不能用作 SQL 正确率指标。

## 语料实测

输入为第一周 `prepare_competition_corpus.py` 生成的 `build/competition-corpus/corpus.jsonl`，来源工作簿 SHA-256 为 `b5603a9bf9db60a76abe46ec6360c4ab09e26e5c10fac3c9dbccd92615963623`。全量候选样本 5705 条，解析与基础契约校验通过 5691 条，接受率 **99.7546%**。分集为 train 4600/4613、dev 559/560、test 532/532。

未通过的 14 条全部保留在本地 `build/competition-corpus/slot-parse-coverage.json`（构建目录已忽略版本控制）：

| 类别 | 来源行 | 处理 |
| --- | --- | --- |
| 非法/缺失引号或未加引号区间 | 2122、2194、2360、2450、2466、2653、5328、5753 | 人工复核原始标签；不自动修补 |
| 多余右括号、开头孤立 `and` | 3785、5521 | 人工复核 |
| `then` 后无 `rank(...)` | 3076、3124、4626、5688 | 与规格不符，确认是否扩展语义 |

此数字仅说明**表面语法与基础函数签名**的接受情况；未检查指标名称正确性、槽位枚举、日期、单位、结果等价性、Doris 可执行性或性能。5705 条原本就标为待验证标签，不能称为 5705 条正确样本。

## 复现

要求 JDK 21、Maven 3.9+。在仓库根目录执行：

```bash
./mvnw test
./mvnw -DskipTests package
java -jar target/dsl-doris-compiler.jar parse-slot examples/competition_slot.dsl
java -jar target/dsl-doris-compiler.jar measure-slot-corpus build/competition-corpus/corpus.jsonl --max-failures 100 -o build/competition-corpus/slot-parse-coverage.json
```

本次验证使用项目本地 JDK 21.0.12.1 和 Maven 3.9.16；Java 测试共 83 项，失败 0、错误 0、因缺少真实 Doris 环境跳过 1。第一周 Python 清洗测试 5 项通过。

## 下一步和阻塞

第 3 周应把函数槽位转成带类型的语义节点，建立指标别名/字段/单位白名单，针对已核准的少量行情指标做安全 SQL lowering 和结果对照。当前缺少主办方完整指标台账、数值缩放倍率、市场代码映射、行情样本以及 Doris 测试环境，不能把通用槽位表达式编成可信 SQL。`then` 的排名范围、并列规则，`~=` 容差，`limit` 的 `-1` 含义也需要确认。
