WITH features AS (
  SELECT h.mktcode,h.tgtcode,h.bizdate,
    h.`low_current` = h.`low_min` AS `f1`
  FROM dsl_history_diag_a74e87700159.history_extrema_v1 h
  WHERE h.snapshot_id=? AND h.manifest_sha256=? AND h.registry_fingerprint=? AND h.bizdate=?
),
current_rows AS (
  SELECT * FROM features WHERE bizdate = ?
)
SELECT mktcode,tgtcode
FROM current_rows
WHERE (`f1` = ?)
ORDER BY mktcode,tgtcode;
