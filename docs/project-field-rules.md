# 已映射指标的项目字段规则

这些是项目现有契约的计算规则，独立参考实现按原始行手工编写。现有文件没有提供足以确认全部单位、复权口径和资金哨兵含义的官方字典；下表不代表官方确认。全部原始记录保持不变。

| 指标 | 原始字段及项目公式 | 项目单位 | NULL 规则 |
|---|---|---|---|
| 最新价 | `lastPx / 10000` | 元 | 原始 NULL 保留 |
| 昨收价 | `preClosePx / 10000` | 元 | 原始 NULL 保留；0 是有效字段值 |
| 开盘价 | `openPx / 10000` | 元 | 原始 NULL 保留 |
| 最高价 | `highPx / 10000` | 元 | 原始 NULL 保留 |
| 最低价 | `lowPx / 10000` | 元 | 原始 NULL 保留 |
| 收盘价 | `closePx / 10000` | 元 | 原始 NULL 保留 |
| 成交量 | `volume` | 股 | 原始 NULL 保留；0 有效 |
| 成交额 | `turnover / 100` | 元 | 原始 NULL 保留；0 有效 |
| 量比 | `quantRatio / 10000` | 比值 | 原始 NULL 保留 |
| 换手率 | `turnRatio / 10000` | 百分点 | 原始 NULL 保留 |
| 真实换手率 | `trueTurnRatio / 10000` | 百分点 | 原始 NULL 保留 |
| 总市值 | `lastPx / 10000 * totalShare` | 元 | 任一计算字段 NULL 则 NULL |
| 流通市值 | `lastPx / 10000 * listedShare` | 元 | 任一计算字段 NULL 则 NULL |
| 涨跌幅（别名涨幅） | `(lastPx - preClosePx) * 100 / preClosePx` | 百分点 | 任一计算字段 NULL 或昨收为 0 则 NULL |
| 均价 | `turnover / 100 / volume` | 元 | 任一计算字段 NULL 或成交量为 0 则 NULL |
| 前复权收盘价 | `closePx / 10000 * qfqMulti + qfqAdd` | 元 | 价格、乘数、加数任一 NULL 则 NULL |
| 后复权收盘价 | `closePx / 10000 * hfqMulti + hfqAdd` | 元 | 价格、乘数、加数任一 NULL 则 NULL |
| 主力净流入 | `ZJLXMainNetTur` | 项目资金金额口径 | NULL、项目约定的 `-999999` 或当日缺少衍生行则 NULL；其他负数保留 |
| 振幅 | `amplitude / 10000` | 百分点 | 原始 NULL 保留 |

目录共有 19 项指标：18 项依赖基础行情，主力净流入依赖衍生行情。衍生行情按市场、文本证券代码和交易日期三键关联。证券范围取评价日基础行情；不把无基础行情的衍生行补造成证券。

价格、成交额和比率的缩放已在语义视图中完成。振幅在注册表中缩放；position 的 `amplitudePosition` 已在视图中缩放，解释器不能再次除以 10000。百分比字面量 `2.5%` 按项目契约代表 2.5 百分点。

## 派生指标缺值解释

执行结果的 `dataQuality.sampleDetails` 最多展开 20 只证券，使用真实观察日期，不推测缺少的日历交易日。派生指标通过固定白名单读取原始计算字段，沿用最多 32 个字段、10001 条历史及原查询预算。

- `SOURCE_OPERAND_NULL`：说明具体原始字段，例如 `前复权收盘价 / qfqMulti`。
- `ZERO_DENOMINATOR`：说明 `均价 / volume` 或 `涨跌幅 / preClosePx` 及发生日期。
- 同日同时出现分子 NULL 和分母为 0 时，两种原因均保留。
- 派生值为 NULL、原始字段却不足以解释时，标注 `PARTIAL_DETAIL / UNCLASSIFIED_SQL_NULL`，避免推断原因。

窗口和 COUNT_INPUT 逐观察行评估这些原因。计数仍沿用既有规则，未知条件不计命中；解释细化不会改变结果与 SQL 缺值标记。

## position 的数值路径

position 使用注册表指定的精确伴随字段；没有伴随字段时使用规范化值，然后与生成 SQL 一样转换为 `DECIMAL(36, positionScale)`。成交量、主力净流入保留整数；成交额 2 位；价格、比率、市值和振幅 4 位；复权收盘价 12 位；涨跌幅、均价 18 位。伴随涨跌幅和均价在视图中的结果精度还受 Doris 的 DECIMAL 运算规则约束。

分类采用交叉相乘比较，三等分边界归低或高。有限窗口需要完整 N 条有效观察，历史窗口忽略旧 NULL，但当前值必须非 NULL；平坦区间返回 NULL。数值域溢出保持明确错误。

## 复验入口

`scripts/doris/check_project_fields.py` 提供 94 组便携 SQL/解释边界、隔离原生 Doris 边界、官方原始行数值及已保存项目执行结果的原因核对。`project_field_reference.py` 与原有 `check_official_field_acceptance.py` 手工定义公式，参考值不从注册表、语义视图或生成 SQL 反推。注册表只用于检查指标目录完整性。

真实项目执行矩阵使用 `check_project_window_performance.py --field-oracle --matrix <field-matrix.json>`，运行账户只读，结果列表、顺序、缺值数量和前 20 个样本均须一致。正式验收仍要求既有快照门禁；项目验证不会写入 `VALIDATED` 登记。
