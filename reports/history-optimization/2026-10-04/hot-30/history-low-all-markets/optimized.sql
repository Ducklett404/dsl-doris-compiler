WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.lowPrice AS `v1`,
    CASE WHEN b.bizdate = ? THEN 1 ELSE 0 END AS is_current
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
),
historical_extrema AS (
  SELECT mktcode,tgtcode,MAX(is_current) AS has_current,
    MAX(CASE WHEN is_current=1 THEN `v1` END) AS `v1_current`,
    MIN(`v1`) AS `f1_extremum`
  FROM history
  GROUP BY mktcode,tgtcode
),
features AS (
  SELECT a.*,
    a.`v1_current` = a.`f1_extremum` AS `f1`
  FROM historical_extrema a
),
current_rows AS (
  SELECT * FROM features WHERE has_current=1
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE (`f1` = ?)
ORDER BY mktcode,tgtcode;
