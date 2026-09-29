CREATE DATABASE IF NOT EXISTS newzl;
USE newzl;

DROP VIEW IF EXISTS v_hsj_stock_hq_basic;
DROP VIEW IF EXISTS v_hsj_stock_hq_ext;
DROP TABLE IF EXISTS data_snapshot_registry;
DROP TABLE IF EXISTS hsj_stock_hq_ext;
DROP TABLE IF EXISTS hsj_stock_hq_basic;
DROP TABLE IF EXISTS hsj_stock_code_info;

CREATE TABLE hsj_stock_code_info (
  mktcode INT NOT NULL,
  tgtcode VARCHAR(16) NOT NULL,
  name VARCHAR(64) NULL,
  tztcode VARCHAR(16) NULL,
  marketNo INT NULL,
  majorType INT NULL,
  hyBlkRefName VARCHAR(64) NULL,
  stFlag BOOLEAN NULL,
  ahFlag BOOLEAN NULL,
  hkConnFlag BOOLEAN NULL,
  shConnFlag BOOLEAN NULL,
  szConnFlag BOOLEAN NULL,
  hsFlag BOOLEAN NULL,
  hsjFlag BOOLEAN NULL,
  kcbFlag BOOLEAN NULL,
  gemFlag BOOLEAN NULL,
  bShareFlag BOOLEAN NULL
)
UNIQUE KEY(mktcode, tgtcode)
DISTRIBUTED BY HASH(mktcode, tgtcode) BUCKETS 16
PROPERTIES("replication_num"="1", "compression"="LZ4");

CREATE TABLE hsj_stock_hq_basic (
  mktcode INT NOT NULL,
  tgtcode VARCHAR(16) NOT NULL,
  bizdate DATE NOT NULL,
  lastPx BIGINT NULL,
  preClosePx BIGINT NULL,
  openPx BIGINT NULL,
  highPx BIGINT NULL,
  lowPx BIGINT NULL,
  closePx BIGINT NULL,
  volume BIGINT NULL,
  turnover BIGINT NULL,
  quantRatio INT NULL,
  turnRatio INT NULL,
  trueTurnRatio INT NULL,
  outerVol BIGINT NULL,
  innerVol BIGINT NULL,
  commissionBuy BIGINT NULL,
  commissionSale BIGINT NULL,
  numOfOrders BIGINT NULL,
  qfqMulti DOUBLE NULL,
  qfqAdd DOUBLE NULL,
  hfqMulti DOUBLE NULL,
  hfqAdd DOUBLE NULL,
  amplitude BIGINT NULL,
  totalShare BIGINT NULL,
  listedShare BIGINT NULL,
  freeShare BIGINT NULL,
  bVPS BIGINT NULL,
  pBR BIGINT NULL,
  dynPE BIGINT NULL,
  staticPE BIGINT NULL,
  pETTM BIGINT NULL,
  limitFlag TINYINT NULL,
  limitType TINYINT NULL,
  limitShape TINYINT NULL,
  firstLimitUpTime DATETIME NULL,
  lastLimitUpTime DATETIME NULL,
  firstLimitDownTime DATETIME NULL,
  lastLimitDownTime DATETIME NULL,
  upTradeAmt BIGINT NULL,
  maxUpSealVol BIGINT NULL,
  downTradeAmt BIGINT NULL,
  maxDownSealVol BIGINT NULL,
  upCount INT NULL,
  downCount INT NULL,
  upSealPx BIGINT NULL,
  upSealVol BIGINT NULL,
  downSealPx BIGINT NULL,
  downSealVol BIGINT NULL,
  lastFUpTime DATETIME NULL,
  lastFDownTime DATETIME NULL,
  upSerialLb INT NULL,
  pressure BIGINT NULL,
  support BIGINT NULL,
  upperShadow BIGINT NULL,
  lowerShadow BIGINT NULL
)
UNIQUE KEY(mktcode, tgtcode, bizdate)
AUTO PARTITION BY RANGE(date_trunc(bizdate, 'year')) ()
DISTRIBUTED BY HASH(mktcode, tgtcode) BUCKETS 16
PROPERTIES("replication_num"="1", "compression"="LZ4");

CREATE TABLE hsj_stock_hq_ext (
  mktcode INT NOT NULL, tgtcode VARCHAR(16) NOT NULL, bizdate DATE NOT NULL,
  riseSpd3m BIGINT NULL, riseSpd5m BIGINT NULL, riseSpd10m BIGINT NULL,
  callAucAmt BIGINT NULL, callAucRisePct BIGINT NULL, callAucAsk2Vol BIGINT NULL,
  callAucBid2Vol BIGINT NULL, callAucMatchVol BIGINT NULL, callAucMatchPx BIGINT NULL,
  MPResExt BIGINT NULL, MPCost BIGINT NULL, ZJLXMainNetTur BIGINT NULL,
  ZJLXMainIncPer INT NULL, smBuyTur BIGINT NULL, smSellTur BIGINT NULL,
  bigBuyTur BIGINT NULL, bigSellTur BIGINT NULL, midSellTur BIGINT NULL,
  supBuyTur BIGINT NULL, supSellTur BIGINT NULL, midBuyTur BIGINT NULL,
  ZJLXMainBuyTur BIGINT NULL, ZJLXMainSellTur BIGINT NULL, ZJLXMainCnt BIGINT NULL,
  ZJLXMainTradeVolPer INT NULL, ZJLXSupNetTur BIGINT NULL, ZJLXBigNetTur BIGINT NULL,
  ZJLXMidNetTur BIGINT NULL, ZJLXSmNetTur BIGINT NULL, ZJLXMainActBuyCnt BIGINT NULL,
  ZJLXMainActBuyCntPer INT NULL, ZJLXMainActSellCnt BIGINT NULL,
  ZJLXMainActSellCntPer INT NULL, ZJLXRetailBuyCnt BIGINT NULL,
  ZJLXRetailSellCnt BIGINT NULL, ZJLXMainBuyCnt BIGINT NULL,
  ZJLXMainBuyCntPer INT NULL, ZJLXMainSellCnt BIGINT NULL,
  ZJLXMainSellCntPer INT NULL, ZJLXRetailBuyCntPer INT NULL,
  ZJLXRetailSellCntPer INT NULL, ZJLXMainNetCntTurPer BIGINT NULL,
  ZJLXMidAndSmNetTur BIGINT NULL, ZJLXMainNetTurInDays INT NULL,
  ZJLXMainNetTurOutDays INT NULL, ZJLXMainNetTurInSeries BIGINT NULL,
  ZJLXMainNetTurOutSeries BIGINT NULL, ZJLXDDX BIGINT NULL, ZJLXDDY BIGINT NULL,
  ZJLXDDZ BIGINT NULL, formFlag INT NULL, maxRetreat INT NULL, maAngle INT NULL,
  pxMkTopDays INT NULL, pxMkBotDays INT NULL, pxMkIncDays INT NULL,
  pxMkDescDays INT NULL, mainTurMkTopDays INT NULL, lmtUpNum INT NULL,
  boardBreaks INT NULL, downBoardBreaks INT NULL
)
UNIQUE KEY(mktcode, tgtcode, bizdate)
AUTO PARTITION BY RANGE(date_trunc(bizdate, 'year')) ()
DISTRIBUTED BY HASH(mktcode, tgtcode) BUCKETS 16
PROPERTIES("replication_num"="1", "compression"="LZ4");

CREATE TABLE data_snapshot_registry (
  snapshot_id VARCHAR(96) NOT NULL,
  contract_version VARCHAR(16) NOT NULL,
  manifest_sha256 CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL,
  loaded_at DATETIME NOT NULL,
  note VARCHAR(1024) NULL
)
UNIQUE KEY(snapshot_id)
DISTRIBUTED BY HASH(snapshot_id) BUCKETS 1
PROPERTIES("replication_num"="1");
