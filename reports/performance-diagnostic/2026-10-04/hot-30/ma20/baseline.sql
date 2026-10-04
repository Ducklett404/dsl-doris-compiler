WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.closePrice AS `v1`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
    AND b.mktcode=1
),
features AS (
  SELECT history.*,
    CASE WHEN COUNT(`v1`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)=20 THEN AVG(`v1`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) ELSE NULL END AS `f1`
  FROM history
),
current_rows AS (
  SELECT * FROM features WHERE bizdate = ?
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE (`f1` > ?)
ORDER BY mktcode,tgtcode
LIMIT 100;
