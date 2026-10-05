# DSL → Doris 执行结果

- 数据快照：`synthetic-execution-bd3f202e623b`
- 编译器版本：`0.1.0`
- SQL 指纹：`sha256:754a459b9bf25fa8b5883e89ff58ca498e45f9f4b566047ef528bf6b58305167`
- 返回行数：2（已按安全上限截断）
- 估算扫描行数：18 / 10000

## 分阶段耗时

| 阶段 | 毫秒 |
|---|---:|
| 编译 | 0.603 |
| 应用排队 | 0.006 |
| EXPLAIN/门禁 | 5.268 |
| Doris 执行至结果可读 | 10.751 |
| 结果读取/返回 | 0.088 |
| 总耗时 | 28.848 |

## 股票列表

| mktcode | tgtcode |
|---|---|
| 1 | 000001 |
| 1 | 000002 |

## Query Profile 摘要

- 可用：false
- Query ID：`714ffb9969a74c9c-8d6bf10347df88b1`
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
     TABLE: dsl_executor_fixture_bd3f202e623b.v_hsj_stock_hq_basic(v_hsj_stock_hq_basic), PREAGGREGATION: ON
     PREDICATES: (((closePrice[#3] > 1) AND (bizdate[#2] = '2026-04-14')) AND (__DORIS_DELETE_SIGN__[#8] = 0))
     partitions=1/1 (v_hsj_stock_hq_basic)
     tablets=1/1, tabletList=1791116605905
     cardinality=18, avgRowSize=760.55554, numNodes=1
     pushAggOp=NONE
     final projections: mktcode[#0], tgtcode[#1]
     final project output tuple id: 1



========== STATISTICS ==========
planned with unknown column statistics
```
