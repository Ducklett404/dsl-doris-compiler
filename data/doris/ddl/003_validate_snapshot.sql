USE newzl;

-- All result rows must have ok = 1. Expected values are replaced by validate-snapshot.ps1.
SELECT 'code_row_count' AS check_name, COUNT(*) AS actual, __CODE_ROWS__ AS expected,
       COUNT(*) = __CODE_ROWS__ AS ok FROM hsj_stock_code_info
UNION ALL
SELECT 'basic_row_count', COUNT(*), __BASIC_ROWS__, COUNT(*) = __BASIC_ROWS__ FROM hsj_stock_hq_basic
UNION ALL
SELECT 'ext_row_count', COUNT(*), __EXT_ROWS__, COUNT(*) = __EXT_ROWS__ FROM hsj_stock_hq_ext;

SELECT 'basic_date_min' AS check_name, CAST(MIN(bizdate) AS STRING) actual, '__BASIC_MIN__' expected,
       MIN(bizdate) = DATE('__BASIC_MIN__') ok FROM hsj_stock_hq_basic
UNION ALL
SELECT 'basic_date_max', CAST(MAX(bizdate) AS STRING), '__BASIC_MAX__', MAX(bizdate) = DATE('__BASIC_MAX__') FROM hsj_stock_hq_basic
UNION ALL
SELECT 'ext_date_min', CAST(MIN(bizdate) AS STRING), '__EXT_MIN__', MIN(bizdate) = DATE('__EXT_MIN__') FROM hsj_stock_hq_ext
UNION ALL
SELECT 'ext_date_max', CAST(MAX(bizdate) AS STRING), '__EXT_MAX__', MAX(bizdate) = DATE('__EXT_MAX__') FROM hsj_stock_hq_ext;

SELECT 'code_pk_duplicates' check_name, COUNT(*) actual, 0 expected, COUNT(*) = 0 ok
FROM (SELECT mktcode,tgtcode FROM hsj_stock_code_info GROUP BY mktcode,tgtcode HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'basic_pk_duplicates', COUNT(*), 0, COUNT(*) = 0
FROM (SELECT mktcode,tgtcode,bizdate FROM hsj_stock_hq_basic GROUP BY mktcode,tgtcode,bizdate HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'ext_pk_duplicates', COUNT(*), 0, COUNT(*) = 0
FROM (SELECT mktcode,tgtcode,bizdate FROM hsj_stock_hq_ext GROUP BY mktcode,tgtcode,bizdate HAVING COUNT(*) > 1) d;

-- Relationship completeness is checked in year-sized partitions by
-- validate-snapshot.ps1.  A single 6.1M x 13.6M anti join exceeds the memory
-- limit of the supported single-node Docker environment.

-- Null and sentinel report (informational, not pass/fail).
SELECT 'basic' table_name, COUNT(*) row_count,
 SUM(lastPx IS NULL) lastPx_nulls, SUM(closePx IS NULL) closePx_nulls,
 SUM(volume IS NULL) volume_nulls, SUM(turnover IS NULL) turnover_nulls,
 SUM(outerVol IS NULL) outerVol_nulls, SUM(innerVol IS NULL) innerVol_nulls,
 ROUND(100.0*SUM(lastPx IS NULL)/COUNT(*),6) lastPx_null_pct,
 ROUND(100.0*SUM(closePx IS NULL)/COUNT(*),6) closePx_null_pct,
 ROUND(100.0*SUM(volume IS NULL)/COUNT(*),6) volume_null_pct,
 ROUND(100.0*SUM(turnover IS NULL)/COUNT(*),6) turnover_null_pct
FROM hsj_stock_hq_basic;

SELECT 'ext' table_name, COUNT(*) row_count,
 SUM(ZJLXMainNetTurInDays=-999999) net_in_days_sentinel,
 SUM(ZJLXMainNetTurOutDays=-999999) net_out_days_sentinel,
 SUM(ZJLXMainNetTurInSeries=-999999) net_in_series_sentinel,
 SUM(ZJLXMainNetTurOutSeries=-999999) net_out_series_sentinel,
 SUM(pxMkTopDays=-999999) px_top_days_sentinel,
 SUM(mainTurMkTopDays=-999999) main_top_days_sentinel
FROM hsj_stock_hq_ext;

SELECT 'basic_invalid_numeric' check_name,
 SUM(closePx < 0) negative_close,
 SUM(volume < 0) negative_volume,
 SUM(turnover < 0) negative_turnover,
 SUM(highPx IS NOT NULL AND lowPx IS NOT NULL AND highPx < lowPx) high_below_low
FROM hsj_stock_hq_basic;

-- Scale/formula sample checks. Average transaction price should be broadly near close price.
SELECT 'avg_price_scale' check_name,
 AVG(ABS(((turnover / 100.0) / volume) / (closePx / 10000.0) - 1.0)) actual,
 0.35 expected_max,
 AVG(ABS(((turnover / 100.0) / volume) / (closePx / 10000.0) - 1.0)) < 0.35 ok
FROM hsj_stock_hq_basic
WHERE turnover > 0 AND volume > 0 AND closePx > 0;

SELECT 'derived_identity_sample' check_name, COUNT(*) actual, 0 expected, COUNT(*) = 0 ok
FROM (
 SELECT * FROM v_hsj_stock_hq_basic
 WHERE (marketValue IS NOT NULL AND ABS(marketValue - lastPrice * totalShare) > 0.01)
    OR (avgPx IS NOT NULL AND ABS(avgPx - turnoverAmount / volume) > 0.000001)
    OR (closeQfq IS NOT NULL AND ABS(closeQfq - (closePrice*qfqMulti+qfqAdd)) > 0.000001)
 LIMIT 1
) bad;

-- This must be reviewed: current source has zero non-default factor rows.
SELECT 'non_default_adjustment_factor_rows' check_name, COUNT(*) actual,
       'must be > 0 before non-trivial adjustment acceptance' requirement
FROM hsj_stock_hq_basic
WHERE qfqMulti <> 1 OR qfqAdd <> 0 OR hfqMulti <> 1 OR hfqAdd <> 0;
