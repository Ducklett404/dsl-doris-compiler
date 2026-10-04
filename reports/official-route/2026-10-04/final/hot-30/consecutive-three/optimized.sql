WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.closePrice AS `v1`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
    AND b.mktcode=1
),
features AS (
  SELECT history.*,
    `v1` AS `f1`
  FROM history
),
predicates AS (
  SELECT features.*,
    (`f1` > ?) AS `pc1`
  FROM features
),
counted AS (
  SELECT predicates.*,
    CASE WHEN COUNT(*) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)=3 THEN (SUM(CASE WHEN `pc1` THEN 1 ELSE 0 END) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)=3) ELSE NULL END AS `c1`
  FROM predicates
),
current_rows AS (
  SELECT * FROM counted WHERE bizdate = ?
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE `c1`
ORDER BY mktcode,tgtcode
LIMIT 100;
