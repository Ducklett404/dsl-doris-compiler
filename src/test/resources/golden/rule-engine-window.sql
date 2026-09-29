WITH target_day AS (
  SELECT symbol, trade_date, trading_day_seq
  FROM market.dws_quote_prefix_daily
  WHERE trade_date = ?
),
prefix_points AS (
  SELECT t.symbol, t.trade_date,
    CASE WHEN (cur.close_count - COALESCE(prev_ma_close_5.close_count, 0)) = 5 THEN (cur.close_sum - COALESCE(prev_ma_close_5.close_sum, 0)) / 5 ELSE NULL END AS `ma_close_5`
  FROM target_day t
  JOIN market.dws_quote_prefix_daily cur ON cur.symbol = t.symbol AND cur.trading_day_seq = t.trading_day_seq
  LEFT JOIN market.dws_quote_prefix_daily prev_ma_close_5 ON prev_ma_close_5.symbol = t.symbol AND prev_ma_close_5.trading_day_seq = t.trading_day_seq - 5
)
SELECT `symbol`, `trade_date`, `ma_close_5`
FROM prefix_points
WHERE (`ma_close_5` > ?)
LIMIT 5;
