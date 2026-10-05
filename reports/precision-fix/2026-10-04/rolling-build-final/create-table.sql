CREATE TABLE dsl_rolling_diag_2a7d2bb431c5.rolling_averages_v1(snapshot_id VARCHAR(128) NOT NULL,manifest_sha256 VARCHAR(64) NOT NULL,
      registry_fingerprint VARCHAR(64) NOT NULL,bizdate DATE NOT NULL,mktcode INT NOT NULL,tgtcode VARCHAR(64) NOT NULL,
      ma20 DOUBLE NULL,ma60 DOUBLE NULL,ma120 DOUBLE NULL,ma250 DOUBLE NULL,
      high_current DOUBLE NULL,high_min250 DOUBLE NULL,high_max250 DOUBLE NULL,low_current DOUBLE NULL,low_min250 DOUBLE NULL,low_max250 DOUBLE NULL)
      UNIQUE KEY(snapshot_id,manifest_sha256,registry_fingerprint,bizdate,mktcode,tgtcode)
      PARTITION BY RANGE(bizdate)(PARTITION p20260410 VALUES LESS THAN ('2026-04-11'),PARTITION p20260413 VALUES LESS THAN ('2026-04-14'),PARTITION p20260414 VALUES LESS THAN ('2026-04-15')) DISTRIBUTED BY HASH(mktcode,tgtcode) BUCKETS 4
      PROPERTIES('replication_num'='1','enable_unique_key_merge_on_write'='true');
