USE newzl;

CREATE TABLE IF NOT EXISTS stock_daily_features_v1 (
  mktcode INT NOT NULL,
  tgtcode VARCHAR(16) NOT NULL,
  bizdate DATE NOT NULL,
  ma60 DOUBLE NULL
)
UNIQUE KEY(mktcode, tgtcode, bizdate)
DISTRIBUTED BY HASH(mktcode, tgtcode) BUCKETS 16
PROPERTIES("replication_num"="1", "compression"="LZ4");

-- The frozen snapshot is immutable.  Only the acceptance date is materialized;
-- non-trading/suspended NULL observations are removed before the 60-row frame.
INSERT INTO stock_daily_features_v1
WITH observed AS (
  SELECT mktcode,tgtcode,bizdate,closePrice
  FROM v_hsj_stock_hq_basic
  WHERE closePrice IS NOT NULL AND bizdate <= DATE('2026-04-14')
), windowed AS (
  SELECT mktcode,tgtcode,bizdate,
         CASE WHEN COUNT(closePrice) OVER (
                    PARTITION BY mktcode,tgtcode ORDER BY bizdate
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) = 60
              THEN AVG(closePrice) OVER (
                    PARTITION BY mktcode,tgtcode ORDER BY bizdate
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
              ELSE NULL END AS ma60
  FROM observed
)
SELECT mktcode,tgtcode,bizdate,ma60
FROM windowed
WHERE bizdate = DATE('2026-04-14');

ANALYZE TABLE stock_daily_features_v1 WITH SYNC;
