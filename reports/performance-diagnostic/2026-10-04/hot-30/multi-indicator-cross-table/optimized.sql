WITH base AS (
  SELECT b.mktcode AS mktcode, b.tgtcode AS tgtcode, b.bizdate AS bizdate,
    b.closePrice AS `m1`,
    NULLIF(e.ZJLXMainNetTur,-999999) AS `m2`
  FROM newzl.v_hsj_stock_hq_basic b
  LEFT JOIN newzl.v_hsj_stock_hq_ext e ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate
  WHERE b.bizdate = ?
    AND b.mktcode = 1
)
SELECT mktcode, tgtcode
FROM base
WHERE ((`m1` > ?) AND (`m2` > ?))
ORDER BY mktcode, tgtcode
LIMIT 100;
