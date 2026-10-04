# DSL → Doris 执行结果

- 数据快照：`synthetic-execution-edf945ef375f`
- 编译器版本：`0.1.0`
- SQL 指纹：`sha256:8d5fcc89f34b923f04d2dfd353c5f1329d1ab5a67940232f0b7641fd8081ddc6`
- 返回行数：2（已按安全上限截断）
- 估算扫描行数：18 / 10000

## 分阶段耗时

| 阶段 | 毫秒 |
|---|---:|
| 编译 | 1.893 |
| 应用排队 | 0.005 |
| EXPLAIN/门禁 | 5.309 |
| Doris 执行至结果可读 | 9.460 |
| 结果读取/返回 | 0.047 |
| 总耗时 | 28.638 |

## 股票列表

| mktcode | tgtcode |
|---|---|
| 1 | 000001 |
| 1 | 000002 |

## Query Profile 摘要

- 可用：false
- Query ID：`a21028364a1746fa-9efbc785f26c4c7a`
- 状态：不可用
- Doris 总耗时：不可用
- 用户：不可用
- 说明：Profile is asynchronous or not retained

## EXPLAIN

```text
PLAN FRAGMENT 0
  OUTPUT EXPRS:
    mktcode[#12]
    tgtcode[#13]
  PARTITION: UNPARTITIONED

  HAS_COLO_PLAN_NODE: false

  VRESULT SINK
     MYSQL_PROTOCOL

  2:VMERGING-EXCHANGE
     offset: 0
     distribute expr lists: tgtcode[#13]

PLAN FRAGMENT 1

  PARTITION: HASH_PARTITIONED: tgtcode[#1]

  HAS_COLO_PLAN_NODE: false

  STREAM DATA SINK
    EXCHANGE ID: 02
    UNPARTITIONED
IS_MERGE: true

  1:VSORT(271)
  |  order by: mktcode[#12] ASC, tgtcode[#13] ASC
  |  algorithm: full sort
  |  local merge sort
  |  merge by exchange
  |  offset: 0
  |  distribute expr lists: 
  |  
  0:VOlapScanNode(259)
     TABLE: dsl_executor_fixture_edf945ef375f.v_hsj_stock_hq_basic(v_hsj_stock_hq_basic), PREAGGREGATION: ON
     PREDICATES: (((closePrice[#3] > 1) AND (bizdate[#2] = '2026-04-14')) AND (__DORIS_DELETE_SIGN__[#8] = 0))
     partitions=1/1 (v_hsj_stock_hq_basic)
     tablets=1/1, tabletList=1791094906679
     cardinality=18, avgRowSize=760.55554, numNodes=1
     pushAggOp=NONE
     final projections: mktcode[#0], tgtcode[#1]
     final project output tuple id: 1



========== STATISTICS ==========
planned with unknown column statistics
```
