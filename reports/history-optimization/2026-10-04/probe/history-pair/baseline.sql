WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.highPrice AS `v1`,
    b.lowPrice AS `v2`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
),
features AS (
  SELECT history.*,
    CASE WHEN COUNT(`v1`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) > 0 THEN `v1` = MAX(`v1`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) ELSE NULL END AS `f1`,
    CASE WHEN COUNT(`v2`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) > 0 THEN `v2` = MIN(`v2`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) ELSE NULL END AS `f2`
  FROM history
),
current_rows AS (
  SELECT * FROM features WHERE bizdate = ?
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE ((`f1` = ?) OR (`f2` = ?))
ORDER BY mktcode,tgtcode;
