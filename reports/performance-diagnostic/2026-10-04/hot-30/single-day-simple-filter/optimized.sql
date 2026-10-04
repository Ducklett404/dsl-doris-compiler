WITH base AS (
  SELECT b.mktcode AS mktcode, b.tgtcode AS tgtcode, b.bizdate AS bizdate,
    b.closePrice AS `m1`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate = ?
    AND b.mktcode = 1
)
SELECT mktcode, tgtcode
FROM base
WHERE (`m1` > ?)
ORDER BY mktcode, tgtcode
LIMIT 100;
