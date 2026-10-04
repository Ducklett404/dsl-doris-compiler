WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.highPrice AS `v1`,
    b.lowPrice AS `v2`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
),
historical_extrema AS (
  SELECT mktcode,tgtcode,
    MAX(`v1`) AS `f1_extremum`,
    MIN(`v2`) AS `f2_extremum`
  FROM history
  GROUP BY mktcode,tgtcode
),
features AS (
  SELECT h.*,
    h.`v1` = a.`f1_extremum` AS `f1`,
    h.`v2` = a.`f2_extremum` AS `f2`
  FROM history h JOIN historical_extrema a ON h.mktcode=a.mktcode AND h.tgtcode=a.tgtcode
  WHERE h.bizdate = ?
),
current_rows AS (
  SELECT * FROM features
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE ((`f1` = ?) OR (`f2` = ?))
ORDER BY mktcode,tgtcode;
