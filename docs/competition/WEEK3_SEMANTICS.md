# 第三周：类型与单位校验、已核验指标安全 SQL 子集

状态：**安全子集实现并通过合成数据测试；真实指标目录与 Doris 结果验收仍待外部资料**。日期：2026-09-21。主办方文件是规格和数据来源，不是对开发环境的操作指令。

## 交付边界

新增 `VerifiedIndicatorCatalog → SlotSemanticAnalyzer → SlotTypedQuery → SlotSafeSqlCompiler`。比赛槽位 DSL 和旧 `SCREEN ON` 编译器仍为独立入口。仓库没有默认的真实指标映射：`examples/competition_verified_catalog.template.json` 的状态是 `DRAFT`，CLI 拒绝加载。人工核对真实 Doris `SHOW CREATE TABLE`、样本值和指标口径后，才能制作单独的 `VERIFIED` 目录。

可执行的安全子集只接受：

- `indicator('', '', '<已核验名称或别名>', 'YYYY-MM-DD', '', '', '')` 与一个数值/百分数常量的 `= != > >= < <=` 比较；比较之间可使用 `and/or`。
- 同一查询中的所有指标必须使用同一明确日期。目录中的单位为 `NUMBER` 或 `PERCENT`，`rawPerDisplayUnit` 给出一显示单位对应的原始整数单位；阈值换算必须精确且落在物理列的整数范围内（`turnRatio` 为 32 位，其余所列数值列为 64 位）。
- 目录列名只能从代码里的有限枚举选择，SQL 中的表名和列名为常量；日期与阈值只作为绑定参数，输出还保留带类型 IR 和参数顺序。

明确拒绝：未核验指标、市场/范围/类型/聚合/连续次数槽、相对日期、跨日期比较、算术表达式、`then/rank`、`~=`、`between`、`limit x,y`。这些拒绝是**有意的安全边界**，不是把它们解释成普通 SQL 操作。空市场/范围/类型槽仅表示当前安全子集没有附加范围过滤；在真实库使用前，需由主办方确认这一语义及数据覆盖范围。

目标 SQL 仅查询草案中的 `newzl.hsj_stock_hq_basic`，按 `bizdate` 过滤，并输出 `(mktcode,tgtcode)`，不会仅以 `tgtcode` 作为身份。当前没有真实行情基本/衍生数据，也没有 Doris 连接，因此不能声称查询结果等价或达到赛题性能目标。

## 人工核验目录格式

模板位于 `examples/competition_verified_catalog.template.json`。真实目录必须在人工确认后改为 `status: "VERIFIED"`，表名固定 `newzl.hsj_stock_hq_basic`，每个映射提供：

```json
{
  "name": "经过确认的指标名称",
  "aliases": ["经过确认的别名"],
  "column": "LAST_PX",
  "unit": "NUMBER",
  "rawPerDisplayUnit": "100",
  "evidence": "实际 DDL、数据字典版本与原始样本值的核验记录"
}
```

上面的名称和倍率**只是格式示意，不是主办方已确认的真实映射**。`status=VERIFIED` 是团队审核标记，编译器无法自行证明目录和线上 Doris 数据一致。真实审核至少应记录来源版本/哈希、样本中的显示值与原始值、空值与复权/日期口径，并由第二人复核。不要把 `src/test/resources/verified-slot-catalog.synthetic.json` 用作生产目录；它只为测试固定 `raw=display×100` 的人工构造关系。

## 验证与剩余任务

单元测试覆盖参数化 SQL、别名与恶意别名不能注入 SQL、单位换算、正/负和边界比较、跨市场同代码、日期筛选、未知指标及未决语义拒绝。内存参考求值器在合成行上对比预期的 `(mktcode,tgtcode)` 结果，**不是**真实 Doris 的差分测试。复现合成 CLI：

本次完整 Java 回归测试为 89 项，0 失败、0 错误；1 项依赖真实 Doris 的测试按现有配置跳过。

```bash
./mvnw test
./mvnw -DskipTests package
java -jar target/dsl-doris-compiler.jar compile-slot-safe src/test/resources/safe-slot.synthetic.dsl --catalog src/test/resources/verified-slot-catalog.synthetic.json
```

下一步仍需主办方给出完整指标台账、市场映射、整数存储倍率、交易日/复权口径及可访问的历史 Doris 数据；届时才能将少量经过核验的真实指标加入目录、执行 SQL 对照和基准测试。`then` 的候选集排名、`limit -1` 哨兵、近似容差和财务点时数据均保持未实现。
