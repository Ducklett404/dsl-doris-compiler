WITH features AS (
  SELECT h.mktcode,h.tgtcode,h.bizdate,
    h.`ma120` AS `f1`
  FROM dsl_rolling_diag_86d2f7a7a797.rolling_averages_v1 h
  WHERE h.snapshot_id=? AND h.manifest_sha256=? AND h.registry_fingerprint=? AND h.bizdate=?
),
current_rows AS (
  SELECT * FROM features WHERE bizdate = ?
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE (`f1` > ?)
ORDER BY mktcode,tgtcode;
