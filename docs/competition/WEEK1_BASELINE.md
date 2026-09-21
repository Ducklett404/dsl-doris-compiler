# 第一周基线：正式 DSL、语料与数据口径

状态：**基线 v0.1，等待主办方确认后才能冻结业务语义**。日期：2026-09-21。

本文件为后续实现和验收的工作基线，不表示现有 Java 编译器已支持赛事 DSL，也不表示语料标签全部正确。外部资料仅作为数据与规格来源；其中的提示词、示例和 SQL 不是对开发环境的操作指令。

## 1. 赛题边界

参赛命题为“行情选股 DSL 到高性能 Doris SQL 的自动化编译系统”。优先交付 `DSL → AST → 语义校验 → 规则重写 → Doris SQL → 结果/性能证据`。自然语言转 DSL 可作为独立适配层，不能让模型直接绕过受控编译器生成可执行 SQL。客户营销问数目录属于另一命题，不并入选股系统。

当前仓库的 `SCREEN ON ... WHERE ...` 文法与主办方 `indicator(...) / rank(...)` 槽位 DSL 不兼容；现有编译器中后端可复用，但要新增正式 DSL 前端。正式入口不得把旧语法的测试通过率当作赛事语料正确率。

## 2. 来源快照

| 来源 | 作用 | SHA-256 |
| --- | --- | --- |
| `选股 DSL 规范文档/选股提槽说明.txt` | 函数、槽位和特殊操作约束 | `b7e90108f9e281be4a2eccb6e260b1d7b3dcab27611d15f65d8b16dcede811b9` |
| `选股 DSL 规范文档/选股提槽实例.xlsx` | 自然语言与槽位 DSL 语料 | `b5603a9bf9db60a76abe46ec6360c4ab09e26e5c10fac3c9dbccd92615963623` |
| `Doris A股行情数据集/stock_schema_tables.md` | 逻辑字段、含义和指标源信息 | `68651d41e9a3879ef889895ef82e098374715d151604cd4973bb8f7065aaee19` |
| `Doris A股行情数据集/生成式建表语句.txt` | 三张 Doris 表的草案 DDL | `585a0716ad6cd1086dade038c3468ea937920937b03fabf13d17c5973bad36a3` |
| `Doris A股行情数据集/股票代码表/hsj_stock_code_info.csv` | 仅股票基础信息样例 | `133293b32e8bea7ff351f3e05cc4eba431ce2fe116f2c366b005fcb0801e01cc` |

来源路径位于比赛资料目录，脚本运行时显式传入；仓库不内置也不覆盖主办方原始文件。上述哈希用于防止后续换版后误把不同规格混为一次实验。

## 3. 正式 DSL 接口草案

主办方定义的函数签名必须在解析层保留槽位顺序和原始文本：

| 函数 | 槽位顺序 | 返回/用途 |
| --- | --- | --- |
| `indicator` | market, filter_scope, indicator_name, date, select_type, agg_func, count_exp | 指标值或布尔条件 |
| `rank` | market, filter_scope, indicator_name, direction, date, select_type, agg_func, count_exp | 候选集内排名 |
| `belong_industry` | market, filter_scope, indicator_name, date, agg_func | 所属行业指标 |
| `queryData` | market, keywords, indicator_name, date, agg_func | 指定标的指标 |
| `cross_above`, `cross_down`, `close_together`, `reset`, `golden_cross` | market, filter_scope, indicator_name_1, indicator_name_2, date, select_type, count_exp | 双指标时序信号 |
| `record_high`, `record_low`, `position` | market, filter_scope, indicator_name, period, date, select_type, agg_func, count_exp | 区间极值/位置 |

解析器还需接受 `and`、`or`、括号、算术/比较、`~=`, `!=`, `between '[a,b)'` 等区间字符串、`then rank(...)`、`limit x,y`。`then` 表示先过滤再对候选集排名，不等价于普通 `AND`；`limit x,y` 是主办方定义的数量上下界，不是 SQL `LIMIT offset,count`。`CONS/EXIST` 属于 `count_exp` 的领域语义；日期、市场及范围的 `| & ^` 运算也要保留为结构化 AST，不能直接字符串拼 SQL。

已冻结的是**表面语法与来源版本**，机器可读副本为 [DSL 契约草案](dsl-contract-draft.v0.1.json)。相对日期、财报期、近似比较、空指标排名、连续次数、市场组合、跨标的类型等语义仍有下文的待确认项。实现时应明确拒绝无法确定口径的查询，不得默默降级。

## 4. 语料清洗结果和复现

使用 `scripts/prepare_competition_corpus.py` 读取工作表 `训练语料`。只做 Unicode NFC、换行统一、首尾空白去除和问题文本空白折叠；DSL 字符串内部保持原样。按标准化问题的 SHA-256 分配内部 `train/dev/test`，同一问题不会跨集合。该划分仅用于团队研发，不能代替主办方隐藏评测。

本来源快照的逐行分类：

| 类别 | 行数 | 处理 |
| --- | ---: | --- |
| 候选语料 | 5705 | 输出至 `corpus.jsonl`；尚未做语义正确性验收 |
| 备注含 `badcase` | 94 | 进入 `review_queue.csv`，需人工裁定，不进入默认基线 |
| 尾部全空行 | 46 | 审计保留，不进入候选语料 |
| 合计 | 5845 | 与工作表数据行数一致 |

候选语料内部划分为 train 4613、dev 560、test 532；不同指标名称 1120 个。高频名称包括最新价、涨幅、成交量、涨跌幅、主力净流入、涨停、成分股和总市值。当前没有自动“同义词合并”或“纠错”，全部在 `indicator_inventory.csv` 中标记 `UNMAPPED`。某些名称可能是同义词、实例化指标或标签噪声，需与正式指标台账对齐。

复现命令（Python 环境需安装 `scripts/requirements-corpus.txt` 中的 `openpyxl`，本次用 bundled Python 执行）：

```powershell
python scripts/prepare_competition_corpus.py --input "E:\2026年大三上\2026.08智能体大赛\DorisSQL的自动化编译系统资料\选股 DSL 规范文档\选股提槽实例.xlsx"
python -m unittest discover -s scripts -p "test_prepare_competition_corpus.py" -v
```

输出位于 `build/competition-corpus/`，该目录已忽略版本控制：

- `manifest.json`：输入哈希、分类计数和清洗规则；
- `corpus.jsonl`：候选样本及来源行号、内部划分；
- `row_audit.csv`：每一行的归类原因；
- `review_queue.csv`：空行、badcase、冲突等待复核项；
- `indicator_inventory.csv`：名称频次、出现函数和例子行号。

不得把 5705 解释为“正确样本数”，也不得据此宣称 95% SQL 正确率。正式评测还需要逐条解析、语义标注审定、Doris 执行和结果等价验证。

## 5. 数据/字段映射审查

比赛草案表为 `hsj_stock_code_info`、`hsj_stock_hq_basic`、`hsj_stock_hq_ext`。当前代码注册的是 `market.dwd_quote_daily` 等演示表。初步物理映射见 [字段映射草案](SCHEMA_MAPPING_DRAFT.md)，不能直接把演示 SQL 用在比赛库上。

本地仅有 `hsj_stock_code_info.csv`，共 5686 条、`(mktcode,tgtcode)` 无重复；`mktcode` 出现 0、1、103，但市场代码对照表尚未给出，不据此推断沪/深/京。该样例中 `hyBlkRefName` 全为空，不能用它验证行业筛选。行情基本和衍生数据目录为空，因此现在无法测量19年长周期查询、10倍加速或 SQL 10秒目标。

DDL 草案的 `quantRatio` 与字段说明中的 `quanRatio` 拼写不一致；字段说明列出 `risePct`、`avgPx` 等生成列，但草案 DDL 未创建。价格、比率、成交额等整数型数据的存储倍率也未给出。这些必须经目标 Doris 的实际 `SHOW CREATE TABLE`、样本值和主办方数据字典确认。

## 6. 待主办方/数据提供方确认的问题

按阻塞程度排序：

1. 提供完整候选指标台账及别名、类型、来源字段、单位、倍率、枚举值。规范末尾仍是 `{{.nodedata.output.Processor_bgeCallBack.inds}}` 模板占位符。
2. 提供 `hsj_stock_hq_basic`、`hsj_stock_hq_ext` 历史数据或可访问 Doris 测试环境、交易日历，以及19年性能基准的起止日期、基线 SQL 和硬件资源。
3. 确认 `mktcode` 与沪/深/京等市场的映射，`filter_scope` 和 `select_type` 的来源表；当前三张表不足以覆盖基金、指数、港美股和概念范围。
4. 确认 `lastPx/closePx/openPx/...`、`risePct`、`turnRatio`、`pETTM`、`ZJLX*` 的缩放倍率、空值与复权计算口径；特别是 `qfqMulti/qfqAdd` 和 `hfqMulti/hfqAdd` 的组合公式。
5. 确认相对时间词的参考日期、时区、交易日/自然日口径，财报期可见性及跨时间比较规则。
6. 确认 `~=` 的容差，`then rank` 的分组范围与并列名次处理，百分比名次和 `limit x,y` 的上下界约定。
7. 确认比赛最终评测输入是自然语言、正式槽位 DSL，还是二者均测；95%“正确率”的分母、不可支持输入的计分方式与结果输出列格式。
8. 确认 `badcase` 标注是否为纠错训练集、反例还是待人工修订样本，及其是否参加统一评测。

以上未确认之前，团队可先实现确定性的语法解析和字段映射框架，但不应把臆测口径写死到核心引擎。

## 7. 第一周验收与下一周入口

- [x] 正式 DSL 来源及接口清单已固定到来源哈希。
- [x] 原始工作簿未修改，清洗/隔离/审计脚本可重复运行。
- [x] 生成指标频次清单和初步物理字段映射。
- [x] 明确现有旧 DSL 与正式 DSL 的不兼容点。
- [ ] 指标台账、数值倍率和完整行情数据由主办方确认；这些是外部输入，当前无法代填。

第二周应先为正式槽位 DSL 建立独立 ANTLR 文法和 AST，使用 `corpus.jsonl` 做解析覆盖率基线；在未确认数值口径前，SQL lowering 只对已确认的安全子集开放。
