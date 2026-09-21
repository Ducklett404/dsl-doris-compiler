# 比赛行情表字段映射草案

状态：候选映射，不可直接作为生产 SQL 依据。来源为主办方 `stock_schema_tables.md` 和 `生成式建表语句.txt`；须与 Doris 实际 DDL、样本值及指标台账核对。

## 表和连接键

| 逻辑实体 | 比赛表 | 键/连接条件 | 当前仓库差异 |
| --- | --- | --- | --- |
| 标的基础信息 | `newzl.hsj_stock_code_info` | `(mktcode,tgtcode)` | 旧模型只用 `symbol` |
| 每日基础行情 | `newzl.hsj_stock_hq_basic` | `(mktcode,tgtcode,bizdate)` | 旧模型的 `trade_date` 和列名均不同 |
| 每日衍生行情 | `newzl.hsj_stock_hq_ext` | `(mktcode,tgtcode,bizdate)` | 旧模型没有此表 |

不得仅按 `tgtcode` 连接，否则跨市场同代码可能误并。按日指标需在同一 `bizdate` 连接；用户输入的标的代码应保留前导零。

## 高频指标初步对照

| 语料名称 | 候选来源 | 状态/待核对 |
| --- | --- | --- |
| 最新价 | basic.`lastPx` | 价格倍率未知；与“收盘价”不同 |
| 收盘价 | basic.`closePx` | 价格倍率、复权公式未知 |
| 开盘价/最高价/最低价 | basic.`openPx/highPx/lowPx` | 价格倍率、复权公式未知 |
| 成交量 | basic.`volume` | 单位是股、手还是源分量需确认 |
| 成交额 | basic.`turnover` | 货币单位/倍率未知 |
| 换手率 | basic.`turnRatio` | 百分比倍率未知 |
| 量比 | 文档 `quanRatio`，DDL `quantRatio` | 字段名冲突，按实际 DDL 决定 |
| 涨幅/跌幅/涨跌幅 | 文档 `risePct`；或由 `lastPx/preClosePx` 算 | DDL 无 `risePct`；正负方向和倍率需确认 |
| 总市值 | 文档 `marketValue`；或 `lastPx * totalShare` | DDL 无 `marketValue`；倍率与复权关系需确认 |
| 市盈率 | basic.`pETTM/dynPE/staticPE` | 三种口径不能自动混同 |
| 市净率 | basic.`pBR` | 倍率未知 |
| 主力净流入 | ext.`ZJLXMainNetTur` | 金额单位/口径未知 |
| 涨停 | basic.`limitFlag = 1` 候选 | 数据更新时间及历史判定需确认 |
| ST股票标识 | code.`stFlag` | 可直连，但需核验样本值编码 |
| 5/10/20/60日均线 | 基础价格时序窗口候选 | 使用 `lastPx` 还是 `closePx`、复权和停牌策略需确认 |
| 行业范围 | code.`hyBlkRefName` 候选 | 当前 CSV 全空，不能作为可验收路径 |
| 成分股/跟踪指数/基金类型 | 未提供完整来源表 | 暂不编造映射 |
| 归母净利润/ROE等财务指标 | 未提供财务点时表 | 暂不编造映射，避免未来数据泄漏 |

## 缺失或冲突的物理约束

- A股代码样例只包含基础表 5686 行；两个行情数据目录为空。
- 文档列出的 `risePct`、`avgPx` 为生成列，但草案 DDL 未定义。`marketValue`、`listedMarketValue` 也存在类似落差。
- 草案 DDL 未见按 `bizdate` 的分区语句，不能仅凭文件名宣称已经支持分区裁剪。
- 前缀和表、特征表、物化视图及交易日历表不在主办方给出的 DDL 中；若团队创建，需提供 DDL、刷新策略和一致性测试。
- 旧仓库的 `market.dwd_financial_pit` 在比赛资料中没有对应物理表。旧财务 SQL 不得默认复用。
