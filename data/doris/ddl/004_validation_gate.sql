USE newzl;
SELECT IF(
  (SELECT COUNT(*) FROM hsj_stock_code_info) = __CODE_ROWS__
  AND (SELECT COUNT(*) FROM hsj_stock_hq_basic) = __BASIC_ROWS__
  AND (SELECT COUNT(*) FROM hsj_stock_hq_ext) = __EXT_ROWS__
  AND (SELECT MIN(bizdate) FROM hsj_stock_hq_basic) = DATE('__BASIC_MIN__')
  AND (SELECT MAX(bizdate) FROM hsj_stock_hq_basic) = DATE('__BASIC_MAX__')
  AND (SELECT MIN(bizdate) FROM hsj_stock_hq_ext) = DATE('__EXT_MIN__')
  AND (SELECT MAX(bizdate) FROM hsj_stock_hq_ext) = DATE('__EXT_MAX__')
  -- The cross-table relationship gate is executed in bounded yearly slices
  -- by validate-snapshot.ps1 after these structural checks pass.
  AND NOT EXISTS (
    SELECT 1 FROM hsj_stock_code_info GROUP BY mktcode,tgtcode HAVING COUNT(*) > 1 LIMIT 1
  )
  AND NOT EXISTS (
    SELECT 1 FROM hsj_stock_hq_basic GROUP BY mktcode,tgtcode,bizdate HAVING COUNT(*) > 1 LIMIT 1
  )
  AND NOT EXISTS (
    SELECT 1 FROM hsj_stock_hq_ext GROUP BY mktcode,tgtcode,bizdate HAVING COUNT(*) > 1 LIMIT 1
  )
  AND NOT EXISTS (
    SELECT 1 FROM hsj_stock_hq_basic
    WHERE closePx < 0 OR volume < 0 OR turnover < 0
       OR (highPx IS NOT NULL AND lowPx IS NOT NULL AND highPx < lowPx) LIMIT 1
  )
  AND (SELECT AVG(ABS(((turnover / 100.0) / volume) / (closePx / 10000.0) - 1.0))
       FROM hsj_stock_hq_basic WHERE turnover > 0 AND volume > 0 AND closePx > 0) < 0.35,
  1, 0) AS gate_ok;
