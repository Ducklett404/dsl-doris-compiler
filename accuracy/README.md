# `stock-slot-v1` 正确性闭环

## 口径

一个样例只有同时通过以下三层才计为正确：

1. Typed AST/语义层：根操作符、函数遍历和语义约束符合金标准；
2. SQL 结构层：逻辑计划及表、字段、关联、过滤、排序、参数等关键结构符合金标准；
3. 结果层：生成 SQL 与独立参考 SQL 在同一固定 Doris 快照上得到相同证券集合；排序类查询必须逐行同序。

正确率的分母仅包含 `executable=true` 且已有真实数据定义的样例。不具备数据源或尚未冻结语义的能力列在黄金集的 `excludedCapabilities` 中，不混入分母，也不编造字段映射。结果比较以 `(mktcode,tgtcode)` 为证券身份；数值结果扩展时采用黄金集声明的绝对/相对容差。

## 数据集划分

- `development`：日常开发样例；
- `regression`：历史 `badcase`，修复后永久保留；
- `blind`：仓库内冻结盲测集，修改编译器时不得据此改写预期结果。

这里的 `blind` 是内部冻结集，不等价于项目方保管的外部盲测集。正式验收仍应由项目方在不可见样本上复跑同一口径。样例按函数、指标类型、时间类型和复杂度记录 `strata`，当前首期范围见 [黄金集](golden/stock-slot-executable-v1.json)。

## 执行

前提是名为 `doris` 的容器健康，且数据库已恢复为黄金集声明的快照。

```powershell
$env:DORIS_PASSWORD = '<本机 dsl_loader 密码>'
mvn -q -DskipTests package
python scripts/accuracy/run_correctness.py
python scripts/accuracy/run_function_smoke.py
```

脚本会先用 snapshot manifest 强制核对三张表的行数和日期范围，再逐例执行。输出：

- `reports/accuracy/stock-slot-executable-v1/result.json`：机器可读结果，包含每例 DSL、错误分类及可复现 SQL/参数；
- `reports/accuracy/stock-slot-executable-v1/REPORT.md`：验收摘要；
- `reports/accuracy/stock-slot-functions-v1-smoke.json`：各函数生成 SQL 的真实 Doris 可执行性烟测；
- 黄金集、快照 manifest 和编译器 JAR 的 SHA-256：用于锁定复跑工件。

盲测正确率低于 95%，或任一层出现失败时，脚本以非零状态退出。
