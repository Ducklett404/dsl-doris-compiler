WITH base AS (
  SELECT
    q.symbol AS symbol,
    q.trade_date AS trade_date,
    q.close_qfq AS `close`,
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
    CASE WHEN COUNT(`close`) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) = 5 THEN AVG(`close`) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) ELSE NULL END AS `ma_close_5`,
    CASE WHEN COUNT(`close`) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) = 20 THEN AVG(`close`) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) ELSE NULL END AS `ma_close_20`
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
  AND (((`pe_ttm` BETWEEN ? AND ?) AND (`roe_ttm` >= ?)) AND (`ma_close_5` > `ma_close_20` AND `prev_ma_close_5` <= `prev_ma_close_20`))
LIMIT 100;
