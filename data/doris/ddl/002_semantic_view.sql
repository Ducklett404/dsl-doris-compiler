USE newzl;
DROP VIEW IF EXISTS v_hsj_stock_hq_basic;
DROP VIEW IF EXISTS v_hsj_stock_hq_ext;
CREATE VIEW v_hsj_stock_hq_basic AS
SELECT
  b.*,
  b.quantRatio AS quanRatio,
  -- BIGINT prices are exact ten-thousandths; never round through DOUBLE.
  -- DECIMAL(19,4) covers the entire signed BIGINT / 10000 source domain.
  CAST(CAST(b.lastPx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4)) AS lastPrice,
  CAST(CAST(b.preClosePx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4)) AS preClosePrice,
  CAST(CAST(b.openPx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4)) AS openPrice,
  CAST(CAST(b.highPx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4)) AS highPrice,
  CAST(CAST(b.lowPx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4)) AS lowPrice,
  CAST(CAST(b.closePx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4)) AS closePrice,
  CAST(b.turnover AS DOUBLE) / 100.0 AS turnoverAmount,
  CAST(b.quantRatio AS DOUBLE) / 10000.0 AS quantityRatio,
  CAST(b.turnRatio AS DOUBLE) / 10000.0 AS turnoverRatio,
  CAST(b.trueTurnRatio AS DOUBLE) / 10000.0 AS trueTurnoverRatio,
  CAST(b.lastPx AS DOUBLE) / 10000.0 * b.totalShare AS marketValue,
  CAST(b.lastPx AS DOUBLE) / 10000.0 * b.listedShare AS listedMarketValue,
  CASE WHEN b.preClosePx IS NULL OR b.preClosePx = 0 THEN NULL
       ELSE (CAST(b.lastPx AS DOUBLE) - CAST(b.preClosePx AS DOUBLE))
            * 100.0 / CAST(b.preClosePx AS DOUBLE) END AS risePct,
  CASE WHEN b.volume IS NULL OR b.volume = 0 THEN NULL
       -- Normalize the exact cents before division; the explicit decimal
       -- boundary also prevents the optimizer's DOUBLE division reassociation.
       -- 17 integer + 21 fractional digits cover signed BIGINT cents / volume.
       ELSE CAST(CAST(CAST(b.turnover AS DECIMAL(24,2)) / 100 AS DECIMAL(36,19))
                 / CAST(b.volume AS DECIMAL(20,0)) AS DECIMAL(38,21)) END AS avgPx,
  CAST(b.openPx AS DOUBLE) / 10000.0 * b.qfqMulti + b.qfqAdd AS openQfq,
  CAST(b.highPx AS DOUBLE) / 10000.0 * b.qfqMulti + b.qfqAdd AS highQfq,
  CAST(b.lowPx AS DOUBLE) / 10000.0 * b.qfqMulti + b.qfqAdd AS lowQfq,
  CAST(b.closePx AS DOUBLE) / 10000.0 * b.qfqMulti + b.qfqAdd AS closeQfq,
  CAST(b.openPx AS DOUBLE) / 10000.0 * b.hfqMulti + b.hfqAdd AS openHfq,
  CAST(b.highPx AS DOUBLE) / 10000.0 * b.hfqMulti + b.hfqAdd AS highHfq,
  CAST(b.lowPx AS DOUBLE) / 10000.0 * b.hfqMulti + b.hfqAdd AS lowHfq,
  CAST(b.closePx AS DOUBLE) / 10000.0 * b.hfqMulti + b.hfqAdd AS closeHfq,
  -- Exact companions are used only for position's categorical boundaries.
  CAST(b.lastPx AS DECIMAL(24,4)) / 10000 AS lastPricePosition,
  CAST(b.preClosePx AS DECIMAL(24,4)) / 10000 AS preClosePricePosition,
  CAST(b.openPx AS DECIMAL(24,4)) / 10000 AS openPricePosition,
  CAST(b.highPx AS DECIMAL(24,4)) / 10000 AS highPricePosition,
  CAST(b.lowPx AS DECIMAL(24,4)) / 10000 AS lowPricePosition,
  CAST(b.closePx AS DECIMAL(24,4)) / 10000 AS closePricePosition,
  CAST(b.turnover AS DECIMAL(24,2)) / 100 AS turnoverAmountPosition,
  CAST(b.quantRatio AS DECIMAL(18,4)) / 10000 AS quantityRatioPosition,
  CAST(b.turnRatio AS DECIMAL(18,4)) / 10000 AS turnoverRatioPosition,
  CAST(b.trueTurnRatio AS DECIMAL(18,4)) / 10000 AS trueTurnoverRatioPosition,
  CAST(b.lastPx AS DECIMAL(24,4)) / 10000 * b.totalShare AS marketValuePosition,
  CAST(b.lastPx AS DECIMAL(24,4)) / 10000 * b.listedShare AS listedMarketValuePosition,
  CASE WHEN b.preClosePx IS NULL OR b.preClosePx = 0 THEN NULL
       ELSE (CAST(b.lastPx AS DECIMAL(30,10)) / CAST(b.preClosePx AS DECIMAL(20,0)) - 1)
            * CAST(100 AS DECIMAL(3,0)) END AS risePctPosition,
  CASE WHEN b.volume IS NULL OR b.volume = 0 THEN NULL
       ELSE CAST(b.turnover AS DECIMAL(30,10)) / 100 / CAST(b.volume AS DECIMAL(20,0)) END AS avgPxPosition,
  CAST(b.amplitude AS DECIMAL(24,4)) / 10000 AS amplitudePosition
FROM hsj_stock_hq_basic b;

CREATE VIEW v_hsj_stock_hq_ext AS
SELECT
  e.*,
  NULLIF(e.ZJLXMainNetTurInDays, -999999) AS ZJLXMainNetTurInDaysClean,
  NULLIF(e.ZJLXMainNetTurOutDays, -999999) AS ZJLXMainNetTurOutDaysClean,
  NULLIF(e.ZJLXMainNetTurInSeries, -999999) AS ZJLXMainNetTurInSeriesClean,
  NULLIF(e.ZJLXMainNetTurOutSeries, -999999) AS ZJLXMainNetTurOutSeriesClean,
  NULLIF(e.pxMkTopDays, -999999) AS pxMkTopDaysClean,
  NULLIF(e.mainTurMkTopDays, -999999) AS mainTurMkTopDaysClean
FROM hsj_stock_hq_ext e;
