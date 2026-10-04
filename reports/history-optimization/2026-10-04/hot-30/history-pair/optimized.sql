WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.highPrice AS `v1`,
    b.lowPrice AS `v2`,
    CASE WHEN b.bizdate = ? THEN 1 ELSE 0 END AS is_current
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
),
historical_extrema AS (
  SELECT mktcode,tgtcode,MAX(is_current) AS has_current,
    MAX(CASE WHEN is_current=1 THEN `v1` END) AS `v1_current`,
    MAX(CASE WHEN is_current=1 THEN `v2` END) AS `v2_current`,
    MAX(`v1`) AS `f1_extremum`,
    MIN(`v2`) AS `f2_extremum`
  FROM history
  GROUP BY mktcode,tgtcode
),
features AS (
  SELECT a.*,
    a.`v1_current` = a.`f1_extremum` AS `f1`,
    a.`v2_current` = a.`f2_extremum` AS `f2`
  FROM historical_extrema a
),
current_rows AS (
  SELECT * FROM features WHERE has_current=1
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE ((`f1` = ?) OR (`f2` = ?))
ORDER BY mktcode,tgtcode;
