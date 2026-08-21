WITH base AS (
  SELECT
    q.symbol AS symbol,
    q.trade_date AS trade_date,
    q.close AS `close`,
    q.market AS `market`,
    q.turnover_rate AS `turnover_rate`
  FROM market.dwd_quote_daily q
  WHERE q.trade_date = ?
)
SELECT `symbol`, `trade_date`
FROM base
WHERE trade_date = ?
  AND ((`close` > ?) AND (`market` IN (?, ?)))
ORDER BY `turnover_rate` DESC
LIMIT 20;
