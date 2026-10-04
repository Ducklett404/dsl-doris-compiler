WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.lowPrice AS `v1`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
),
historical_extrema AS (
  SELECT mktcode,tgtcode,
    MIN(`v1`) AS `f1_extremum`
  FROM history
  GROUP BY mktcode,tgtcode
),
features AS (
  SELECT h.*,
    h.`v1` = a.`f1_extremum` AS `f1`
  FROM history h JOIN historical_extrema a ON h.mktcode=a.mktcode AND h.tgtcode=a.tgtcode
  WHERE h.bizdate = ?
),
current_rows AS (
  SELECT * FROM features
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE (`f1` = ?)
ORDER BY mktcode,tgtcode;
