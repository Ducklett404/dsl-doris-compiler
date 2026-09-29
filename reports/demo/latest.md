# 最终七步演示报告

- Generated: 2026-09-28T23:34:29.8287723+08:00
- Doris evidence mode: **HistoricalEvidence**
- **警告：本报告的 Doris 查询与性能数字来自 2026-09-18 固定快照历史证据，不是本轮实时执行。正式演示必须使用 `-DorisMode Live`。**

## 1. 正式复杂 DSL

```text
indicator('沪', '', '收盘价', '2026-04-14', '', '', '') > 10
and indicator('沪', '', '主力净流入', '2026-04-14', '', '', '') > 0
then rank('沪', '', '涨跌幅', 'desc:row_number', '2026-04-14', '', '', '') <= 20
limit 0,20

```

## 2. Typed AST、规则轨迹、逻辑计划和参数化 SQL

### Typed AST / Semantic Model

```json
{
  "document": {
    "expression": {
      "kind": "Binary",
      "operator": "THEN",
      "left": {
        "kind": "Binary",
        "operator": "AND",
        "left": {
          "kind": "Binary",
          "operator": ">",
          "left": {
            "kind": "FunctionCall",
            "name": "indicator",
            "arguments": [
              {
                "kind": "Literal",
                "value": "沪",
                "type": "STRING",
                "span": {
                  "line": 1,
                  "column": 11,
                  "endLine": 1,
                  "endColumn": 14
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 1,
                  "column": 16,
                  "endLine": 1,
                  "endColumn": 18
                }
              },
              {
                "kind": "Literal",
                "value": "收盘价",
                "type": "STRING",
                "span": {
                  "line": 1,
                  "column": 20,
                  "endLine": 1,
                  "endColumn": 25
                }
              },
              {
                "kind": "Literal",
                "value": "2026-04-14",
                "type": "STRING",
                "span": {
                  "line": 1,
                  "column": 27,
                  "endLine": 1,
                  "endColumn": 39
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 1,
                  "column": 41,
                  "endLine": 1,
                  "endColumn": 43
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 1,
                  "column": 45,
                  "endLine": 1,
                  "endColumn": 47
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 1,
                  "column": 49,
                  "endLine": 1,
                  "endColumn": 51
                }
              }
            ],
            "type": "NUMBER",
            "span": {
              "line": 1,
              "column": 1,
              "endLine": 1,
              "endColumn": 52
            }
          },
          "right": {
            "kind": "Literal",
            "value": 10,
            "type": "NUMBER",
            "span": {
              "line": 1,
              "column": 55,
              "endLine": 1,
              "endColumn": 57
            }
          },
          "type": "BOOLEAN",
          "span": {
            "line": 1,
            "column": 1,
            "endLine": 1,
            "endColumn": 57
          }
        },
        "right": {
          "kind": "Binary",
          "operator": ">",
          "left": {
            "kind": "FunctionCall",
            "name": "indicator",
            "arguments": [
              {
                "kind": "Literal",
                "value": "沪",
                "type": "STRING",
                "span": {
                  "line": 2,
                  "column": 15,
                  "endLine": 2,
                  "endColumn": 18
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 2,
                  "column": 20,
                  "endLine": 2,
                  "endColumn": 22
                }
              },
              {
                "kind": "Literal",
                "value": "主力净流入",
                "type": "STRING",
                "span": {
                  "line": 2,
                  "column": 24,
                  "endLine": 2,
                  "endColumn": 31
                }
              },
              {
                "kind": "Literal",
                "value": "2026-04-14",
                "type": "STRING",
                "span": {
                  "line": 2,
                  "column": 33,
                  "endLine": 2,
                  "endColumn": 45
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 2,
                  "column": 47,
                  "endLine": 2,
                  "endColumn": 49
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 2,
                  "column": 51,
                  "endLine": 2,
                  "endColumn": 53
                }
              },
              {
                "kind": "Literal",
                "value": "",
                "type": "STRING",
                "span": {
                  "line": 2,
                  "column": 55,
                  "endLine": 2,
                  "endColumn": 57
                }
              }
            ],
            "type": "NUMBER",
            "span": {
              "line": 2,
              "column": 5,
              "endLine": 2,
              "endColumn": 58
            }
          },
          "right": {
            "kind": "Literal",
            "value": 0,
            "type": "NUMBER",
            "span": {
              "line": 2,
              "column": 61,
              "endLine": 2,
              "endColumn": 62
            }
          },
          "type": "BOOLEAN",
          "span": {
            "line": 2,
            "column": 5,
            "endLine": 2,
            "endColumn": 62
          }
        },
        "type": "BOOLEAN",
        "span": {
          "line": 1,
          "column": 1,
          "endLine": 2,
          "endColumn": 62
        }
      },
      "right": {
        "kind": "Binary",
        "operator": "<=",
        "left": {
          "kind": "FunctionCall",
          "name": "rank",
          "arguments": [
            {
              "kind": "Literal",
              "value": "沪",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 11,
                "endLine": 3,
                "endColumn": 14
              }
            },
            {
              "kind": "Literal",
              "value": "",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 16,
                "endLine": 3,
                "endColumn": 18
              }
            },
            {
              "kind": "Literal",
              "value": "涨跌幅",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 20,
                "endLine": 3,
                "endColumn": 25
              }
            },
            {
              "kind": "Literal",
              "value": "desc:row_number",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 27,
                "endLine": 3,
                "endColumn": 44
              }
            },
            {
              "kind": "Literal",
              "value": "2026-04-14",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 46,
                "endLine": 3,
                "endColumn": 58
              }
            },
            {
              "kind": "Literal",
              "value": "",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 60,
                "endLine": 3,
                "endColumn": 62
              }
            },
            {
              "kind": "Literal",
              "value": "",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 64,
                "endLine": 3,
                "endColumn": 66
              }
            },
            {
              "kind": "Literal",
              "value": "",
              "type": "STRING",
              "span": {
                "line": 3,
                "column": 68,
                "endLine": 3,
                "endColumn": 70
              }
            }
          ],
          "type": "NUMBER",
          "span": {
            "line": 3,
            "column": 6,
            "endLine": 3,
            "endColumn": 71
          }
        },
        "right": {
          "kind": "Literal",
          "value": 20,
          "type": "NUMBER",
          "span": {
            "line": 3,
            "column": 75,
            "endLine": 3,
            "endColumn": 77
          }
        },
        "type": "BOOLEAN",
        "span": {
          "line": 3,
          "column": 6,
          "endLine": 3,
          "endColumn": 77
        }
      },
      "type": "BOOLEAN",
      "span": {
        "line": 1,
        "column": 1,
        "endLine": 3,
        "endColumn": 77
      }
    },
    "selectionLimit": {
      "minimum": 0,
      "maximum": 20,
      "span": {
        "line": 1,
        "column": 1,
        "endLine": 5,
        "endColumn": 6
      }
    },
    "span": {
      "line": 1,
      "column": 1,
      "endLine": 5,
      "endColumn": 6
    }
  },
  "calls": [
    {
      "function": "indicator",
      "span": {
        "line": 1,
        "column": 1,
        "endLine": 1,
        "endColumn": 52
      },
      "slots": [
        {
          "name": "market",
          "rawValue": "沪",
          "structuredValue": {
            "value": "沪"
          }
        },
        {
          "name": "filter_scope",
          "rawValue": "",
          "structuredValue": {
            "value": ""
          }
        },
        {
          "name": "indicator_name",
          "rawValue": "收盘价",
          "structuredValue": {
            "value": "收盘价",
            "template": "收盘价",
            "parameters": {}
          }
        },
        {
          "name": "date",
          "rawValue": "2026-04-14",
          "structuredValue": {
            "raw": "2026-04-14",
            "reportPeriod": null,
            "offsets": []
          }
        },
        {
          "name": "select_type",
          "rawValue": "",
          "structuredValue": {
            "value": ""
          }
        },
        {
          "name": "agg_func",
          "rawValue": "",
          "structuredValue": ""
        },
        {
          "name": "count_exp",
          "rawValue": "",
          "structuredValue": null
        }
      ]
    },
    {
      "function": "indicator",
      "span": {
        "line": 2,
        "column": 5,
        "endLine": 2,
        "endColumn": 58
      },
      "slots": [
        {
          "name": "market",
          "rawValue": "沪",
          "structuredValue": {
            "value": "沪"
          }
        },
        {
          "name": "filter_scope",
          "rawValue": "",
          "structuredValue": {
            "value": ""
          }
        },
        {
          "name": "indicator_name",
          "rawValue": "主力净流入",
          "structuredValue": {
            "value": "主力净流入",
            "template": "主力净流入",
            "parameters": {}
          }
        },
        {
          "name": "date",
          "rawValue": "2026-04-14",
          "structuredValue": {
            "raw": "2026-04-14",
            "reportPeriod": null,
            "offsets": []
          }
        },
        {
          "name": "select_type",
          "rawValue": "",
          "structuredValue": {
            "value": ""
          }
        },
        {
          "name": "agg_func",
          "rawValue": "",
          "structuredValue": ""
        },
        {
          "name": "count_exp",
          "rawValue": "",
          "structuredValue": null
        }
      ]
    },
    {
      "function": "rank",
      "span": {
        "line": 3,
        "column": 6,
        "endLine": 3,
        "endColumn": 71
      },
      "slots": [
        {
          "name": "market",
          "rawValue": "沪",
          "structuredValue": {
            "value": "沪"
          }
        },
        {
          "name": "filter_scope",
          "rawValue": "",
          "structuredValue": {
            "value": ""
          }
        },
        {
          "name": "indicator_name",
          "rawValue": "涨跌幅",
          "structuredValue": {
            "value": "涨跌幅",
            "template": "涨跌幅",
            "parameters": {}
          }
        },
        {
          "name": "direction",
          "rawValue": "desc:row_number",
          "structuredValue": "desc:row_number"
        },
        {
          "name": "date",
          "rawValue": "2026-04-14",
          "structuredValue": {
            "raw": "2026-04-14",
            "reportPeriod": null,
            "offsets": []
          }
        },
        {
          "name": "select_type",
          "rawValue": "",
          "structuredValue": {
            "value": ""
          }
        },
        {
          "name": "agg_func",
          "rawValue": "",
          "structuredValue": ""
        },
        {
          "name": "count_exp",
          "rawValue": "",
          "structuredValue": null
        }
      ]
    }
  ]
}
```

### 规则与转换轨迹

| Phase | Input | Output | Action |
|---|---|---|---|
| PARSE | stock-slot-v1 source | Typed AST | ANTLR parse with source spans |
| NORMALIZE | SemanticModel | SemanticModel | stable normalization hook; identity for an already canonical typed tree |
| LOWER | typed indicator/rank calls | registered expressions | registry mapping, scale and sentinel policy |
| ACCESS_PATH | registered expressions | logical scan path | HistoryScan: newzl.v_hsj_stock_hq_basic through 2026-04-14 |
| PARAMETERIZE | typed literals | JDBC placeholders | 5 bound values; no user literal concatenation |

> `NORMALIZE` 是正式 DSL 当前真实的稳定规则钩子；输入已经规范化时保持恒等，不虚构未执行的重写。

### 逻辑计划

| # | Node | Detail |
|---:|---|---|
| 1 | HistoryScan | newzl.v_hsj_stock_hq_basic through 2026-04-14 |
| 2 | LeftJoin | newzl.v_hsj_stock_hq_ext on (mktcode,tgtcode,bizdate) |
| 3 | Window | 1 contract(s) |
| 4 | EvaluationDateFilter | 2026-04-14 |
| 5 | Filter | then precondition before ranking |
| 6 | NullFilter | exclude NULL rank metrics |
| 7 | Rank | [ROW_NUMBER] |
| 8 | Sort | rank,mktcode,tgtcode |
| 9 | CardinalityConstraint | 0,20 |
| 10 | Project | mktcode,tgtcode |

### 参数绑定

| Index | Value |
|---:|---|
| 1 | `2026-04-14` |
| 2 | `2026-04-14` |
| 3 | `10` |
| 4 | `0` |
| 5 | `20` |

### SQL

```sql
WITH history AS (
  SELECT b.mktcode AS mktcode,b.tgtcode AS tgtcode,b.bizdate AS bizdate,
    b.closePrice AS `v1`,
    NULLIF(e.ZJLXMainNetTur,-999999) AS `v2`,
    b.risePct AS `v3`
  FROM newzl.v_hsj_stock_hq_basic b
  LEFT JOIN newzl.v_hsj_stock_hq_ext e ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate
  WHERE b.bizdate <= ?
    AND b.mktcode=1
),
features AS (
  SELECT history.*,
    `v1` AS `f1`,
    `v2` AS `f2`
  FROM history
),
current_rows AS (
  SELECT * FROM features WHERE bizdate = ?
),
prefiltered AS (
  SELECT * FROM current_rows WHERE ((`f1` > ?) AND (`f2` > ?))
),
rank_input AS (
  SELECT * FROM prefiltered WHERE `v3` IS NOT NULL
),
ranked AS (
  SELECT rank_input.*,
    ROW_NUMBER() OVER (ORDER BY `v3` DESC,mktcode,tgtcode) AS `r1`
  FROM rank_input
)
SELECT mktcode,tgtcode
FROM ranked
WHERE (`r1` <= ?)
ORDER BY `r1`,mktcode,tgtcode
LIMIT 20;
```

## 3. Doris 股票结果（实时步骤 NOT_RUN）

> 以下行为历史 `registry-smoke.dsl` 冒烟证据，仅验证结果展示格式；它不是第 1 步复杂 DSL 的执行结果，不能作为实时演示通过证据。

| Evidence | Status | Snapshot | Rows shown | Query ms |
|---|---|---|---:|---:|
| HistoricalEvidence | HISTORICAL_REFERENCE_ONLY | `stock-20060104-20260414-v1` | 20 | 100.3504 |

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

## 4–5. 同结果基线、优化路径与19年性能

| Check | Value | Gate | Result |
|---|---:|---:|---|
| Optimized P95 | 52.5262 ms | ≤ 10000 ms | PASS |
| Full-scan P95 | 4070.1145 ms | reference | PASS |
| Speedup | 77.4873x | ≥ 10x | PASS |
| Result equality | enforced for 5 iteration(s) | identical rows/order | PASS |

## 6. 单指标配置扩展，核心代码 0 行改动

| Item | Value |
|---|---|
| Added config | `config/extensions/direct-field/registry-plugin.json` |
| Indicator | `CLOSE_MIRROR` |
| Compile | PASS |
| CI allow-list gate | PASS |
| Core fingerprint before | `sha256:b188d0f56cbe8b9ec1caee1ca5bb9e20d1006b558d7f84be41c7e6b5d3b19874` |
| Core fingerprint after | `sha256:b188d0f56cbe8b9ec1caee1ca5bb9e20d1006b558d7f84be41c7e6b5d3b19874` |
| Core code changes during demo | **0** |

## 7. 正确率与编译 P95

| Report | Value | Gate | Result |
|---|---:|---:|---|
| Golden accuracy | 100% (24/24) | ≥ 95% | PASS |
| Uncached compiler P95 | 0.1218 ms | < 50 ms | PASS |
| Compiler iterations | 5000 | ≥ 5000 | PASS |

## 总结

**PARTIAL_PASS（脚本/编译器通过；实时 Doris 步骤 NOT_RUN）**
