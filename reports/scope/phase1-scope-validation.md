# 首期数据指标范围自动校验

- Freeze: `stock-slot-phase1-scope-v1.0.1`
- Result: **PASS**
- Approval: **DIRECT_PROJECT_APPROVAL**（无需签字）

| Check | Status | Detail |
|---|---|---|
| freeze-status | PASS | stock-slot-phase1-scope-v1.0.1 / APPROVED |
| registry-lock | PASS | stock-slot-registry-v1.0.1 sha256=09fbd4b474d6a6820215ae3428178ef14e7afc0d4f78878ef5b40b84984202b2 |
| snapshot-lock | PASS | stock-20060104-20260414-v1, 3 source files verified |
| ddl-lock | PASS | 4 DDL/semantic contracts verified |
| indicator-scope | PASS | 19 exact indicators have unique definitions |
| pattern-scope | PASS | 2 parameterized indicators verified |
| function-scope | PASS | 11 included, 2 explicitly excluded |
| market-scope | PASS | 沪/深/京 only; all other recognized markets excluded |
| negative-scope | PASS | 8 unsupported categories have written reasons |

> PASS 表示仓库工件与已批准的项目内部冻结范围一致；不表示赛事组织方已认证实现结果。
