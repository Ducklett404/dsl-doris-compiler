WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.closePrice AS `v1`,
    b.openPrice AS `v2`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
    AND b.mktcode=1
),
features AS (
  SELECT history.*,
    CASE WHEN `v1` IS NOT NULL AND `v2` IS NOT NULL AND LAG(`v1`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate) IS NOT NULL AND LAG(`v2`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate) IS NOT NULL THEN (`v1`>`v2` AND LAG(`v1`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate)<=LAG(`v2`) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate)) ELSE NULL END AS `f1`
  FROM history
),
current_rows AS (
  SELECT * FROM features WHERE bizdate = ?
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE (`f1` = ?)
ORDER BY mktcode,tgtcode
LIMIT 100;
