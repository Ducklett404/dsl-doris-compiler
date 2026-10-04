WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.closePrice AS `v1`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate <= ?
    AND b.mktcode=1
),
features AS (
  SELECT history.*
  FROM history
),
current_rows AS (
  SELECT * FROM features WHERE bizdate = ?
),
rank_input AS (
  SELECT * FROM current_rows WHERE `v1` IS NOT NULL
),
ranked AS (
  SELECT rank_input.*,
    ROW_NUMBER() OVER (ORDER BY `v1` DESC,mktcode,tgtcode) AS `r1`
  FROM rank_input
)
SELECT mktcode,tgtcode
FROM ranked
WHERE (`r1` <= ?)
ORDER BY `r1`,mktcode,tgtcode
LIMIT 100;
