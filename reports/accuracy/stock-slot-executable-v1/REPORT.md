# stock-slot-v1 正确性报告

黄金集：`stock-slot-executable-v1`  
数据快照：`stock-20060104-20260414-v1`  
执行时间（UTC）：`2026-09-18T05:10:04.912292+00:00`

## 可复现工件

- 黄金集 SHA-256：`6d2f3159668081ca57aa217b4b4b29e86fcd79f47576eced446d20739bc992ae`
- 快照清单 SHA-256：`306f333e28c82c9f2c634d8a1eb64eb49d3092937d8ca7d2742d96ecdcf21a95`
- 编译器 JAR SHA-256：`a9ea5470b65fc9066b4cfa8479c82e40c4a438fc3ab33449cd94d7f400bb1760`

## 正确率

| 数据集 | 正确数 | 分母 | 正确率 |
|---|---:|---:|---:|
| development | 8 | 8 | 100.00% |
| regression | 8 | 8 | 100.00% |
| blind | 8 | 8 | 100.00% |
| **整体** | **24** | **24** | **100.00%** |

正确样例必须同时通过 Typed AST/语义、SQL 结构和 Doris 结果三层检查。

## 失败分类

- 无失败样例。

## 分母与排除范围

Only cases with accepted metric mappings and executable=true are included.

- financial indicators without a source table
- industry/concept/index membership without a source table
- fund/bond/security-type filters without a source table
- relative Chinese dates that require an evaluation-date contract
- CONS/EXIST and multi-period aggregation pending window semantics

## 快照检查

固定快照核验：`True`。
行数与日期范围均在执行黄金集前同 manifest 强制比对。

## 样例明细

| ID | 集合 | 三层结果 | 返回行数 |
|---|---|---|---:|
| DEV-001 | development | PASS/PASS/PASS | 3836 |
| DEV-002 | development | PASS/PASS/PASS | 23 |
| DEV-003 | development | PASS/PASS/PASS | 5205 |
| DEV-004 | development | PASS/PASS/PASS | 2413 |
| DEV-005 | development | PASS/PASS/PASS | 2323 |
| DEV-006 | development | PASS/PASS/PASS | 348 |
| DEV-007 | development | PASS/PASS/PASS | 3828 |
| DEV-008 | development | PASS/PASS/PASS | 5 |
| REG-001 | regression | PASS/PASS/PASS | 5573 |
| REG-002 | regression | PASS/PASS/PASS | 2247 |
| REG-003 | regression | PASS/PASS/PASS | 1726 |
| REG-004 | regression | PASS/PASS/PASS | 106 |
| REG-005 | regression | PASS/PASS/PASS | 5473 |
| REG-006 | regression | PASS/PASS/PASS | 1227 |
| REG-007 | regression | PASS/PASS/PASS | 10 |
| REG-008 | regression | PASS/PASS/PASS | 5 |
| BLIND-001 | blind | PASS/PASS/PASS | 2685 |
| BLIND-002 | blind | PASS/PASS/PASS | 1410 |
| BLIND-003 | blind | PASS/PASS/PASS | 7 |
| BLIND-004 | blind | PASS/PASS/PASS | 2963 |
| BLIND-005 | blind | PASS/PASS/PASS | 5573 |
| BLIND-006 | blind | PASS/PASS/PASS | 825 |
| BLIND-007 | blind | PASS/PASS/PASS | 8 |
| BLIND-008 | blind | PASS/PASS/PASS | 6 |
