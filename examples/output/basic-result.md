# DSL 编译结果

| 项目 | 值 |
|---|---|
| Compiler | 0.1.0 |
| Access path | DETAIL_TABLE |
| Lookback | 21 trading days |
| Bindings | 8 |

## Doris SQL

```sql
WITH base AS (
  SELECT
    q.symbol AS symbol,
    q.trade_date AS trade_date,
    q.close_qfq AS `close`,
    q.market AS `market`,
    q.turnover_rate AS `turnover_rate`,
    f.pe_ttm AS `pe_ttm`,
    f.roe_ttm AS `roe_ttm`
  FROM market.dwd_quote_daily q
  LEFT JOIN market.dwd_financial_pit f
    ON f.symbol = q.symbol
   AND f.visible_from <= q.trade_date
   AND q.trade_date < f.visible_to
  WHERE q.trade_date BETWEEN (
    SELECT MIN(cal_date) FROM (
      SELECT cal_date FROM market.dim_trade_calendar
      WHERE market = 'CN' AND is_open = 1 AND cal_date <= ?
      ORDER BY cal_date DESC LIMIT 22
    ) trading_days
  ) AND ?
),
metrics AS (
  SELECT base.*,
    AVG(`close`) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS `ma_close_5`,
    AVG(`close`) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS `ma_close_20`
  FROM base
),
signals AS (
  SELECT metrics.*,
    LAG(`ma_close_5`) OVER (PARTITION BY symbol ORDER BY trade_date) AS `prev_ma_close_5`,
    LAG(`ma_close_20`) OVER (PARTITION BY symbol ORDER BY trade_date) AS `prev_ma_close_20`
  FROM metrics
)
SELECT `symbol`, `trade_date`, `pe_ttm`, `roe_ttm`, `ma_close_5`, `ma_close_20`
FROM signals
WHERE trade_date = ?
  AND ((((`pe_ttm` BETWEEN ? AND ?) AND (`roe_ttm` >= ?)) AND (`ma_close_5` > `ma_close_20` AND `prev_ma_close_5` <= `prev_ma_close_20`)) AND (`market` IN (?, ?)))
ORDER BY `turnover_rate` DESC
LIMIT 100;
```

## 参数

| # | 值 |
|---:|---|
|1|2026-08-07|
|2|2026-08-07|
|3|2026-08-07|
|4|0|
|5|20|
|6|0.15|
|7|SH|
|8|SZ|

## 规则轨迹

| Rule | 说明 |
|---|---|
|R-010|Canonicalized expression tree and preserved predicate order|
|R-104|Deduplicated common window expressions and emitted layered CTEs|

