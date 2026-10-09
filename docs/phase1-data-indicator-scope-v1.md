# 首期数据指标范围冻结书（stock-slot-phase1-scope-v1.0.4）

项目内部批准生效，不表示比赛组织方认证。v1.0.4 修订六个 BIGINT 价格字段及均价的精度边界；历史 v1.0.0—v1.0.3 在 `config/acceptance/history/`。真实执行前须应用现行语义视图并生成新证书；当前验证状态见 [项目状态](project-status.md)。机器清单哈希按冻结校验的文本换行口径计算，不沿用历史报告中的原字节 manifest 哈希。

状态：**已批准并冻结生效（无需签字）**<br>
初始批准日期：2026-09-29；现行修订生效日期：2026-10-10<br>
DSL：`stock-slot-v1`<br>
机器清单：`config/acceptance/stock-slot-phase1-scope-v1.json`

## 1. 冻结结论

首期验收只覆盖本文件明确列出的19个精确指标、2类参数化技术指标、11个函数和沪/深/京市场。
所有其他指标、市场、标的类型、时间形式和业务范围必须在编译阶段返回明确诊断，禁止猜字段、
借用近似指标或把不支持项放入可执行正确率分母。

首期 SQL 正确率分母定义为：一条 DSL 引用的所有市场、指标、函数、日期形式、聚合方式、范围和
标的类型均在本冻结书中标记为纳入，并且固定快照具备所需数据表。排序查询按顺序比较，其余查询
按证券集合比较；数值绝对容差为 `1e-6`、相对容差为 `1e-8`。

## 2. 固定数据快照

| 对象 | 固定值 |
|---|---|
| Snapshot | `stock-20060104-20260414-v1` |
| Manifest SHA-256 | `a4f509b7bcaeae96df40ebf97fa2e18c8d7c131a078562f898f94d00d05c091c` |
| 代码表 | 5,686行，SHA-256 `133293...e01cc` |
| 基础行情 | 13,650,347行，2006-01-04至2026-04-14，SHA-256 `9c5fd6...1d749` |
| 扩展行情 | 6,170,822行，2018-08-20至2026-04-14，SHA-256 `18ab00...b4a18` |
| 注册表 | `stock-slot-registry-v1.0.2`，SHA-256 `401c7f5073d2a4ee4f29231b679e44fc56e90df75226cb05851c28bc9b6f3071` |

CSV、注册表、建表语句、语义视图、验证门禁和性能特征脚本的完整哈希均记录在机器清单中。
任何哈希变化都会使自动校验失败。

## 3. 纳入首期验收的精确指标

| 指标 | 别名 | 类型/单位 | 唯一数据定义 | 数据范围 | 空值/异常 | 聚合 |
|---|---|---|---|---|---|---|
| 最新价 | - | NUMBER/CNY | `lastPx / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 昨收价 | - | NUMBER/CNY | `preClosePx / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 开盘价 | - | NUMBER/CNY | `openPx / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 最高价 | - | NUMBER/CNY | `highPx / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 最低价 | - | NUMBER/CNY | `lowPx / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 收盘价 | - | NUMBER/CNY | `closePx / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 成交量 | - | NUMBER/SHARE | `volume` | 基础表范围 | 保留NULL | MAX/MIN/AVG/SUM |
| 成交额 | - | NUMBER/CNY | `turnover / 100` | 基础表范围 | 保留NULL | MAX/MIN/AVG/SUM |
| 量比 | - | NUMBER/RATIO | `quantRatio / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 换手率 | - | PERCENT/PERCENT_POINT | `turnRatio / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 真实换手率 | - | PERCENT/PERCENT_POINT | `trueTurnRatio / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 总市值 | - | NUMBER/CNY | `(lastPx/10000) * totalShare` | 基础表范围 | 任一输入NULL则NULL | MAX/MIN/AVG/SUM |
| 流通市值 | - | NUMBER/CNY | `(lastPx/10000) * listedShare` | 基础表范围 | 任一输入NULL则NULL | MAX/MIN/AVG/SUM |
| 涨跌幅 | 涨幅 | PERCENT/PERCENT_POINT | `(lastPx-preClosePx)*100/preClosePx` | 基础表范围 | 昨收为空或0则NULL | MAX/MIN/AVG |
| 均价 | - | NUMBER/CNY | `turnover/(100*volume)`（按现行视图显式 DECIMAL 边界计算） | 基础表范围 | 成交量为空或0则NULL | MAX/MIN/AVG |
| 前复权收盘价 | - | NUMBER/CNY | `(closePx/10000)*qfqMulti+qfqAdd` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 后复权收盘价 | - | NUMBER/CNY | `(closePx/10000)*hfqMulti+hfqAdd` | 基础表范围 | 保留NULL | MAX/MIN/AVG |
| 主力净流入 | - | NUMBER/CNY | `NULLIF(ZJLXMainNetTur,-999999)` | 2018-08-20至2026-04-14 | `-999999`转NULL，保留其他NULL | MAX/MIN/AVG/SUM |
| 振幅 | - | PERCENT/PERCENT_POINT | `amplitude / 10000` | 基础表范围 | 保留NULL | MAX/MIN/AVG |

“基础表范围”只表示表级日期边界，不承诺每个字段每日非空。查询必须遵守注册表中的空值策略，
不能用0或前值填充缺失值。

## 4. 纳入的参数化指标与函数

- `X日均线`：`1 <= X <= 5000`，按证券和交易日排序，对收盘价取完整X条已观测记录的平均；
  窗口不足或有效值不足返回NULL。只有冻结日的60日均线允许读取等价特征表，其余走历史路径。
- `RSI(N)`：`1 <= N <= 5000`，使用N个完整收盘价差值，公式固定在机器清单中。
- 函数：`indicator`、`rank`、`queryData`、`record_high`、`record_low`、`position`、
  `cross_above`、`cross_down`、`close_together`、`reset`、`golden_cross`。
- 次数表达式：只接受 `CONS>=N日`、`CONS=N日`、`EXIST>=N日`、`EXIST=N日`。
- 市场：沪(`1`)、深(`0`)、京(`103`)；允许 `| & ^` 集合运算。市场为空表示快照内全部证券。
- 日期：绝对日期 `YYYY-MM-DD`、`YYYY年M月D日`，以及绝对日期后的 `近N日` 聚合。
- `filter_scope` 和 `select_type` 首期必须为空。

## 5. 明确排除清单

| 类别 | 排除内容 | 原因 |
|---|---|---|
| 财务 | 归母净利润、每股收益、财报ROE/PE等 | 没有带公告/生效时间的财务表 |
| 概念/指数 | 概念板块、指数成分 | 没有带生效区间的成员表 |
| 行业 | 行业过滤、`belong_industry`、`industry_max` | 固定快照代码表5,686行的`hyBlkRefName`全部为空 |
| 标的类型 | 基金、ETF、债券、指数 | `majorType`枚举和数据覆盖未冻结 |
| 市场 | 港、美、新三板和海外市场 | 没有可执行市场码映射和数据覆盖 |
| 时间 | 今天/昨日、财报期、开始/前/后偏移、多评价日期 | 缺少固定评价日或点时语义 |
| 聚合 | `GROWTH_RISE`、`GROWTH_FALL` | 增长公式和比较基准未冻结 |
| 其他指标 | 未出现在第3、4节的任意名称 | 没有唯一且可测试的数据定义 |

排除项不得通过别名、相近字段或常量替代。补齐数据后必须发布新的冻结版本，不能原地修改V1。

## 6. 批准与变更控制

本范围已由项目请求方于2026-09-29直接批准，不设置项目方、数据方或技术负责人的签字前置
流程。批准状态记录在机器清单中：`status=APPROVED`、
`approval.mode=DIRECT_PROJECT_APPROVAL`。

任何指标、公式、倍率、来源、日期范围、快照、DDL哈希或结果比较口径变化，都必须：

1. 新增版本号，不覆盖 `stock-slot-phase1-scope-v1.0.0`；
2. 补来源表合同、正反测试、黄金SQL、Doris结果差分和快照校验；
3. 重新计算正确率分母；
4. 由项目请求方直接批准新版本，无需签字。

本批准仅代表项目内部首期验收范围已经生效，不表述为赛事组织方对实现结果作出认证。
