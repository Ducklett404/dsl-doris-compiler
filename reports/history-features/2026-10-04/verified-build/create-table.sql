CREATE TABLE dsl_history_diag_3253bcf6f36c.history_extrema_v1 (
      snapshot_id VARCHAR(128) NOT NULL, manifest_sha256 VARCHAR(64) NOT NULL,
      registry_fingerprint VARCHAR(64) NOT NULL, bizdate DATE NOT NULL,
      mktcode INT NOT NULL, tgtcode VARCHAR(64) NOT NULL,
      close_current DOUBLE NULL,close_min DOUBLE NULL,close_max DOUBLE NULL,low_current DOUBLE NULL,low_min DOUBLE NULL,low_max DOUBLE NULL,high_current DOUBLE NULL,high_min DOUBLE NULL,high_max DOUBLE NULL
    ) UNIQUE KEY(snapshot_id,manifest_sha256,registry_fingerprint,bizdate,mktcode,tgtcode)
    PARTITION BY RANGE(bizdate) (PARTITION p20260413 VALUES LESS THAN ('2026-04-14'),PARTITION p20260414 VALUES LESS THAN ('2026-04-15'))
    DISTRIBUTED BY HASH(mktcode,tgtcode) BUCKETS 4
    PROPERTIES('replication_num'='1','enable_unique_key_merge_on_write'='true');
