# stock-slot-v1 函数执行语义（v1）

本文是 `compile-stock-slot-sql` 的执行契约。未列入真实映射的指标和标的类型必须报错，不能猜测字段。

## 统一窗口契约

| 项目 | 约定 |
|---|---|
| 分区键 | 单证券窗口为 `(mktcode,tgtcode)`；行业横截面为 `(hyBlkRefName,bizdate)` |
| 排序键 | 时间窗口固定为 `bizdate ASC` |
| 时间单位 | `N日` 指数据库中已观测到的 N 条交易记录，不是 N 个自然日 |
| 停牌 | 无行情记录的停牌日不补行、不前向填充；前一日指前一条已观测交易记录 |
| 新股/窗口不足 | 要求完整窗口的函数返回 `NULL`，不以短窗口代替 |
| 空值 | 不插值；严格窗口只要有效值数量不足 N 就返回 `NULL` |
| 历史窗口 | `历史` 使用截至评价日的全部已观测记录，不要求固定 N 条 |
| 评价日 | SQL 先计算历史窗口，再筛选评价日，禁止提前过滤导致窗口退化 |

上述内容同时写入编译产物的 `windowContracts`，供测试和审计使用。

## 函数定义

### `indicator`

- 普通行情指标读取语义视图中的真实字段或已确认派生字段。
- `X日均线`：完整 X 条有效收盘价的算术平均；不足或含空值返回 `NULL`。
- `RSI(N)`：使用收盘价相邻已观测交易记录之差；完整 N 个差值后计算
  `100 - 100 / (1 + AVG(max(delta,0)) / AVG(max(-delta,0)))`。
- 时间聚合写法为 `评价日期近N日`，并配合 `MAX/MIN/AVG/SUM`。增长类聚合尚无冻结公式，返回明确错误。
- 市场在历史扫描前过滤；行业范围使用代码表 `hyBlkRefName`；无可靠 `majorType` 枚举的基金、债券等标的类型拒绝执行。

### `rank`

- `asc`/`desc` 默认采用 `DENSE_RANK`，保持现有语料兼容。
- 显式形式：`asc:rank`、`desc:dense_rank`、`desc:row_number`。
- `RANK/DENSE_RANK` 只按指标计算并保留并列；`ROW_NUMBER` 用 `(mktcode,tgtcode)` 作稳定的并列决胜键。
- 空指标行在排名前排除。`filter_scope='行业'` 时按行业分组排名。
- `A then rank(...)` 先执行 A，再在剩余证券上排名。

### `queryData`

`keywords` 必须是一个精确证券代码或名称。函数在同一评价日返回该证券指标，默认用 `MAX(CASE...)` 形成标量；找不到证券或值为空时返回 `NULL`。集合关键词拒绝执行，避免不明确的多证券标量。

### `record_high` / `record_low`

当前值等于 `N日`（或 `历史`）窗口的 `MAX/MIN` 时为真。`N日` 必须具备完整 N 条非空值，否则返回 `NULL`；相等值均算创新高/低。

### `cross_above` / `cross_down`

- 上穿：`a(t)>b(t) AND a(t-1)<=b(t-1)`。
- 下穿：`a(t)<b(t) AND a(t-1)>=b(t-1)`。
- 任一当前值或前值为空时返回 `NULL`；`t-1` 是前一条已观测交易记录。

### `position`

在完整窗口 `[min,max]` 中计算当前位置：落在下 1/3 为 `低`，上 1/3 为 `高`，其余为 `中`。当 `max=min`、窗口不足或存在导致有效计数不足的空值时返回 `NULL`。

### `belong_industry`

行业来自 `hsj_stock_code_info.hyBlkRefName`。默认返回同评价日同行业指标的 `AVG`，也支持 `MAX/MIN/SUM`；行业缺失时返回 `NULL`。这是横截面窗口，不涉及停牌填充。

### `close_together` / `reset` / `golden_cross`

- `close_together(a,b)`：`abs(a-b)/max(abs(a),abs(b)) <= 1%`；分母为零或任一值为空时返回 `NULL`。
- `reset(a,b)`：本版本固定为“重新站上”，即 `a(t)>b(t) AND a(t-1)<=b(t-1)`。
- `golden_cross(a,b)`：本版本固定为短周期序列 a 上穿长周期序列 b，数学式与 `cross_above` 相同；调用方必须按短、长顺序传参。

### `CONS` / `EXIST`

- `CONS>=N日`：当前及之前 N 条已观测记录上的条件均为真；`CONS=N日` 还要求第 N+1 条记录为假，即当前连续段恰好为 N。
- 支持 `EXIST>=N日`、`EXIST=N日`：最近 `max(20,N)` 条已观测记录中条件为真的次数与 N 比较。
- 窗口不足返回 `NULL`。当前版本不接受 `<`、`<=`、`!=` 或“每”，因为这些写法没有唯一的回看边界。

## 当前硬边界

- 没有真实来源的财务指标、概念/指数成分、基金和债券分类仍返回稳定错误码。
- `GROWTH_RISE/GROWTH_FALL`、财报期相对偏移和多评价日期查询在公式或时间基准冻结前不生成 SQL。
- SQL 使用参数绑定；动态表名、列名和任意 SQL 片段均不来自 DSL 输入。
