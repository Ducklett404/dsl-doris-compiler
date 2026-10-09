# stock-slot-v1 真实表注册表与类型系统

随程序发布的注册表为 `stock-slot-registry-v1.0.2`；项目实际执行由 `stock-slot-phase1-scope-v1.0.4` 限定。注册表内可编译概念不等于现有数据能够验收，行业等排除项见 [能力说明](project-capabilities-v1.md)。

正式 DSL 的表、字段、市场、指标类型、函数签名和 lowering 元数据统一保存在
`src/main/resources/stock-slot-registry-v1.json`。运行时可通过：

```powershell
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql query.dsl `
  --registry src/main/resources/stock-slot-registry-v1.json --format sql
```

加载外部文件。未指定 `--registry` 时使用随程序发布的版本。

## 配置结构

- `tables`：受控的限定表名、别名、粒度、逻辑字段到真实字段的映射、关联键。
- `markets`：市场名称到 `mktcode` 的映射。
- `indicators`：名称和别名、值类型、单位、倍率、允许聚合、来源表/字段、所需字段、
  时间粒度、最大回看、复权要求、空值策略、哨兵值和 `FIELD` lowering。
- `indicatorPatterns`：`X日均线`、`RSI(N)` 等参数化指标及其受控 lowering 参数。
- `functions`：有序参数及类型、空字符串能力、返回类型（可继承指标类型）、时间粒度、
  最大回看、空值策略、lowering 类型与受控参数。
- `testVectors`：注册表随附的正向表达式/ lowering 向量和安全反向向量。

## 无 Java 改动的扩展流程

新增普通字段指标：

1. 若真实字段尚未登记，只在对应 `tables.*.fields` 增加逻辑字段映射。
2. 在 `indicators` 增加完整定义，`lowering.kind` 必须是 `FIELD`。
3. 表达式模板只能是 `{alias}.{field}` 或
   `NULLIF({alias}.{field},{sentinel})`。
4. 在 `testVectors.positive` 增加期望表达式，并补充业务测试数据。

新增已有 lowering 类型的函数：

1. 复制同 lowering 类型的函数签名并换成新函数名。
2. 只填写该 lowering 允许的参数，例如 `INDUSTRY_AGGREGATE.defaultAggregation`。
3. 增加 `FUNCTION_LOWERING` 正向向量和 DSL 结果测试数据。

以上两类扩展不需要修改核心 Java。测试 `StockSlotRegistryTest` 会在运行时向 JSON 增加
`配置新增价` 和 `config_industry_sum`，然后实际编译 SQL，以此锁定“核心 Java 0 行改动”的验收条件。

## 加载期安全边界

加载器使用严格 JSON 模式并执行交叉引用校验。以下配置直接拒绝：

- 未知 JSON 属性、重复指标/别名/函数、未知表或字段；
- 含变量、引号或表达式的动态表名和字段名；
- 未知模板占位符；
- `SELECT/FROM/JOIN/UNION/WITH`、注释、分号、子查询；
- 白名单外函数参数、lowering 参数、聚合、模式或非数值阈值；
- 非正倍率、越界回看、缺少正/反测试向量。

模板不是通用 SQL 模板。SQL 的窗口、Join、过滤和聚合结构仍由受控 lowering 代码生成，
配置只能选择已注册 lowering 类型及其经过校验的枚举/数值参数。
