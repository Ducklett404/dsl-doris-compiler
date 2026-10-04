WITH history AS (
  SELECT pf.mktcode AS mktcode,pf.tgtcode AS tgtcode,pf.bizdate AS bizdate,
    pf.ma60 AS `v1`
  FROM newzl.stock_daily_features_v2 pf
  WHERE pf.bizdate = ?
    AND pf.mktcode=1
),
features AS (
  SELECT history.*,
    `v1` AS `f1`
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
