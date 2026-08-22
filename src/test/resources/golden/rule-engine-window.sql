WITH base AS (
  SELECT
    q.symbol AS symbol,
    q.trade_date AS trade_date,
    q.close AS `close`
  FROM market.dwd_quote_daily q
  WHERE q.trade_date BETWEEN (
    SELECT MIN(cal_date) FROM (
      SELECT cal_date FROM market.dim_trade_calendar
      WHERE market = 'CN' AND is_open = 1 AND cal_date <= ?
      ORDER BY cal_date DESC LIMIT 6
    ) trading_days
  ) AND ?
),
metrics AS (
  SELECT base.*,
    AVG(`close`) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS `ma_close_5`
  FROM base
)
SELECT `symbol`, `trade_date`, `ma_close_5`
FROM metrics
WHERE trade_date = ?
  AND (`ma_close_5` > ?)
LIMIT 5;
