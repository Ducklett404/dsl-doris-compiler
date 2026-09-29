# 最终编译和查询结果

## 当前编译结果

| DSL | DSL version | Status | Logical plan | Bindings | SQL fingerprint |
|---|---|---|---|---:|---|
| `examples/registry-smoke.dsl` | `stock-slot-v1` | PASS | Scan → DateAndMarketFilter → Sort → Project | 2 | `sha256:2fe9c3b4bf7d41bdbf5940ed243fb1f9325011014faee6f9a6fdc7ab6b01bda7` |

```sql
WITH base AS (
  SELECT b.mktcode AS mktcode, b.tgtcode AS tgtcode, b.bizdate AS bizdate,
    (b.amplitude * 1 / 10000) AS `m1`
  FROM newzl.v_hsj_stock_hq_basic b
  WHERE b.bizdate = ?
)
SELECT mktcode, tgtcode
FROM base
WHERE (`m1` > ?)
ORDER BY mktcode, tgtcode;
```

## 查询结果

| Evidence | Snapshot | Status | Rows | Compile ms | Query ms | Note |
|---|---|---|---:|---:|---:|---|
| `reports/performance/doris-execution-smoke.json` | `stock-20060104-20260414-v1` | HISTORICAL_PASS | 20 | 30.2279 | 100.3504 | 2026-09-18 固定快照证据；本轮状态为 NOT_RUN |

### 历史查询返回样例

| mktcode | tgtcode |
|---|---|
| 0 | 000002 |
| 0 | 000004 |
| 0 | 000006 |
| 0 | 000007 |
| 0 | 000008 |
| 0 | 000009 |
| 0 | 000010 |
| 0 | 000011 |
| 0 | 000012 |
| 0 | 000014 |
| 0 | 000016 |
| 0 | 000017 |
| 0 | 000019 |
| 0 | 000020 |
| 0 | 000021 |
| 0 | 000026 |
| 0 | 000027 |
| 0 | 000028 |
| 0 | 000029 |
| 0 | 000030 |

> 历史证据不会替代本轮复测；当前 Docker/凭据不可用时保持 `NOT_RUN`。
