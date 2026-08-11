# V1 编译器优化与功能新增优先级路线图

本文基于《行情选股 DSL 到 Doris SQL 项目分析与技术路线报告》和当前 V1 编译器现状整理。当前 V1 已具备 ANTLR4 语法、Typed AST、语义检查、规则 Trace、Doris SQL 生成、CLI、HTTP API 和插件雏形；后续优化重点应从“能编译”推进到“语义可信、性能可证、扩展可治理”。

## 总体目标

- 复杂 DSL 到 Doris SQL 正确率达到 95% 以上，P0 金融语义用例 100% 通过。
- 编译阶段 P95 小于 50ms，且编译热路径不访问 Doris、不读文件、不加载插件。
- 对代表性 19 年行情查询实现可复现的 10 倍加速，并用 EXPLAIN / Query Profile 证明。
- 新增常用指标时核心代码零改动，通过插件和规则注册完成。
- 输出完整可解释产物：AST、逻辑计划、规则 Trace、访问路径候选、SQL、参数、诊断信息。

## P0：正确性与金融语义边界

P0 是最高优先级。没有这一层，SQL 即使能跑也不可信。

### 1. 补齐首版最小 DSL 语法

建议优先补齐：

- `IS NULL` / `IS NOT NULL`
- 显式窗口单位，例如 `MA(CLOSE, 20, unit=TRADING_DAY)`
- 横截面排序或排名，例如 `RANK_BY(...)`
- 参数化查询上下文，例如市场、行业、股票池、用户权限上下文
- 更严格的表达式深度、`IN` 列表长度、窗口长度限制

验收标准：

- 新增语法都有正例、反例和错误定位测试。
- 恶意深层表达式、超长 `IN` 列表、超大窗口不会拖垮编译器。

### 2. 强化领域类型系统

建议新增或细化类型：

- `PriceSeries`
- `RatioSeries`
- `Percent`
- `VolumeSeries`
- `TradeDate`
- `SecurityId`
- `BooleanSeries`
- `ScalarNumber`
- `StringCategory`

重点规则：

- `ROE_TTM() >= 15%` 合法。
- `ROE_TTM() + TRADE_DATE` 编译期报错。
- `CROSS_UP(...)` 的两个参数必须是可按证券和交易日排序的序列。
- `ORDER BY` 表达式必须能在目标日得到标量结果。

验收标准：

- 类型错误包含错误码、行列、问题片段和建议改法。
- P0 类型用例 100% 通过。

### 3. 固化交易日窗口语义

窗口必须基于交易日，而不是自然日。建议新增：

- `WindowSpec` 中间结构，包含窗口长度、单位、排序键、分区键、是否要求完整窗口。
- `STRICT_FULL_WINDOW`、`ALLOW_PARTIAL_WINDOW` 等空值策略。
- 停牌日、上市首日、窗口不足场景测试数据。

验收标准：

- MA、LAG、CROSS_UP 等窗口类指标不会因为目标日过滤过早而截断输入。
- 所有窗口 SQL 都先扩大扫描范围，再在最终层过滤目标日。

### 4. 防未来数据的财务指标语义

财务指标必须使用公告日可见值。建议新增：

- 财务指标元数据：`visibleFromColumn`、`visibleToColumn`、`reportPeriodColumn`。
- 编译诊断中明确说明财务指标使用公告日可见值。
- 未来数据防护测试。

验收标准：

- 不允许使用报告期直接 Join 导致未来函数。
- 财务指标 SQL 必须带 `visible_from <= trade_date < visible_to` 或等价条件。

## P1：指标插件与规则系统

P1 的目标是让项目不再靠改核心代码堆指标。

### 5. 升级插件契约

建议插件字段升级为：

- `id` / `version`
- `signature`
- `returnType`
- `requiredFields`
- `windowSpec`
- `adjustmentRequirement`
- `nullPolicy`
- `loweringKind`
- `sqlTemplate` 或受控 `IRBuilder`
- `capabilities`
- `tests`

优先支持：

- 简单模板插件，例如 `ABS_CHANGE(CLOSE, OPEN)`
- 受控窗口插件，例如 `VOLATILITY(CLOSE, 20)`

验收标准：

- 新增一个指标时核心 Java 代码 diff 为 0。
- 插件非法 SQL 片段、动态表名、注释、分号、子查询会被拒绝。

### 6. 声明式规则引擎

建议每条规则包含：

- `ruleId`
- `pattern`
- `precondition`
- `transform`
- `semanticProofTag`
- `priority`
- `version`
- `testVectors`

优先实现规则：

- 常量折叠
- 布尔化简
- 重复谓词去重
- 比较方向统一
- 公共指标表达式共享
- 相同分区和排序窗口合并
- 投影裁剪

验收标准：

- 每条规则都有 Trace。
- 规则前后结果可通过 Golden SQL 或参考执行器差分证明等价。

### 7. 扩充标准指标包

建议首批控制在 20 到 30 个高频指标：

- 价格类：`OPEN`、`HIGH`、`LOW`、`CLOSE`
- 成交类：`VOLUME`、`AMOUNT`、`TURNOVER_RATE`
- 均线类：`MA`、`EMA`
- 信号类：`CROSS_UP`、`CROSS_DOWN`
- 估值类：`PE_TTM`、`PB`、`PS_TTM`
- 财务类：`ROE_TTM`、`ROA_TTM`、`NET_PROFIT_YOY`
- 波动类：`VOLATILITY`、`STDDEV`
- 强弱类：`RETURN_N`、`RSI`
- 排名类：`RANK_BY`、`PERCENTILE_RANK`

验收标准：

- 每个指标有口径说明、类型签名、SQL lowering、边界测试。
- 指标版本进入编译产物。

## P2：AccessPathPlanner 与性能闭环

P2 的目标是从“总是生成明细表 SQL”升级为“能解释为什么选某条路径”。

### 8. 引入 Metadata Catalog 快照

编译器不能在线访问 Doris，但可以读取预加载的元数据快照。

建议目录快照包含：

- 表名映射：明细表、财务 PIT 表、交易日历表、特征表、前缀和表
- 分区范围
- 行数估算
- bucket 信息
- 可用索引
- 可用物化视图
- 特征版本和刷新时间
- Doris 版本能力矩阵

验收标准：

- 编译请求只读内存快照。
- 元数据版本进入缓存键和编译产物。

### 9. 实现访问路径候选评分

建议先使用规则化成本模型：

```text
cost = estimated_scan_bytes
     + window_compute_cost
     + join_cost
     + freshness_penalty
     + unsupported_risk_penalty
```

候选路径：

- `DETAIL_TABLE`
- `PARTITION_BUCKET_INDEX`
- `PREFIX_DAILY`
- `FEATURE_DAILY`
- `MATERIALIZED_VIEW`
- `QUERY_CACHE_FRIENDLY`

验收标准：

- 编译产物输出所有候选路径、淘汰原因和最终选择。
- 数据新鲜度不满足时必须回退明细表。

### 10. 支持前缀和表

前缀和表适合 `SUM`、`AVG`、`COUNT`、累计收益、成交额窗口等。

建议新增：

- `dws_quote_prefix_daily` 逻辑表
- 交易日序号字段
- 当前累计值减 N 日前累计值的 lowering
- 窗口不足与停牌缺口策略

验收标准：

- `MA(CLOSE, N)` 在前缀和路径可用时能生成两点差 SQL。
- 与明细窗口 SQL 结果一致。

### 11. 支持日级指标特征表

特征表是 19 年全周期稳定加速的关键。

建议新增：

- `dws_quote_feature_daily`
- `feature_version`
- `adjustment_version`
- `source_snapshot`
- 指标列映射，例如 `ma_close_5`、`ma_close_20`、`roe_ttm`、`volatility_20`

验收标准：

- 高频指标查询优先命中特征表。
- 特征版本过期时自动回退。

### 12. 接入 Doris EXPLAIN 和 Query Profile

这部分放在执行器，不放在编译核心。

建议新增模块：

- `executor-doris`
- `ExplainService`
- `QueryProfileCollector`
- `BenchmarkRunner`

验收标准：

- 能证明分区裁剪、物化视图、索引或特征表是否命中。
- 性能报告包含扫描字节、扫描行数、耗时、内存、MV 命中情况。

## P3：工程化、验收和产品化增强

### 13. 建立参考执行器和差分测试

建议用小数据集参考实现验证 SQL 语义。

验收标准：

- 500+ DSL 语料差分测试。
- P0 金融语义用例 100% 通过。

### 14. 建立 Golden SQL 与 AST 快照

建议新增：

- `src/test/resources/golden/*.sql`
- `src/test/resources/golden/*.json`
- 稳定格式化 SQL 输出
- AST schema version

验收标准：

- 任意规则修改导致 SQL 或 AST 变化时，测试能提示差异。
- 变化必须可解释。

### 15. 编译性能基准

建议升级为 JMH，分桶测试：

- 简单 DSL
- 中等 DSL
- 复杂 DSL
- 错误 DSL
- 恶意边界 DSL

验收标准：

- 预热后复杂 DSL P95 < 50ms。
- 编译热路径无文件 IO、无网络 IO。

### 16. API 和缓存设计

建议标准返回：

```json
{
  "ast": {},
  "logicalPlan": {},
  "sql": "...",
  "bindings": [],
  "diagnostics": [],
  "ruleTrace": [],
  "accessPath": {},
  "lookback": 21,
  "compilerVersion": "0.1.0",
  "ruleSetVersion": "..."
}
```

缓存键：

```text
normalized_ast_hash + rule_version + catalog_version + doris_capability_version
```

验收标准：

- 编译缓存只缓存编译产物，不缓存权限判断和敏感参数。
- 规则、表映射或 Doris 能力版本变化后缓存自然失效。

### 17. 安全和治理增强

建议新增：

- 权限门禁
- 成本门禁
- 最大扫描量估算
- 只读执行账号
- SQL hash 审计
- 敏感参数脱敏
- 插件签名和版本兼容检查

验收标准：

- 用户输入不能成为库名、表名、列名。
- DSL 不允许任意 SQL、注释、子查询、分号透传。

## 建议实施顺序

### 第 1 阶段：2 周内完成

1. 补最小语法。
2. 强化领域类型系统。
3. 固化交易日窗口和财务 PIT 语义。
4. 增加 AST 快照和 Golden SQL。
5. 扩充核心错误和边界用例。

### 第 2 阶段：第 3 到 5 周完成

1. 升级插件契约。
2. 实现标准指标包 20 到 30 个。
3. 规则引擎支持可注册规则。
4. 实现公共窗口合并、投影裁剪、谓词下推。
5. 完成新增指标核心代码零改动演示。

### 第 3 阶段：第 6 到 8 周完成

1. 建立 Metadata Catalog 快照。
2. 实现 AccessPathPlanner 候选评分。
3. 接入前缀和表和特征表 lowering。
4. 接入 Doris EXPLAIN / Query Profile。
5. 选 3 条代表性策略做明细路径与优化路径对比。

### 第 4 阶段：第 9 到 10 周完成

1. 建立 500+ DSL 语料。
2. 建立参考执行器差分测试。
3. 输出 JMH 编译性能报告。
4. 输出 19 年查询基准报告。
5. CLI / REST / Docker Compose 一键演示。
6. 输出最终技术说明和答辩材料。

## 当前 V1 最应该立即做的 5 件事

1. 增强语义分析：领域类型、交易日窗口、财务 PIT、防未来数据。
2. 建立 Golden SQL / AST 快照测试，防止后续优化改坏语义。
3. 升级插件元数据，让新增指标不再依赖核心代码改动。
4. 把 AccessPathPlanner 从“展示候选”升级为“基于元数据评分并解释选择”。
5. 做特征表和前缀和表两条优化路径，因为这是 19 年 10 倍加速的关键。

## 不建议现在优先做的事

- 不建议首版完整接入 Apache Calcite。
- 不建议继续扩大 DSL 到接近自然语言。
- 不建议让大模型直接生成 SQL。
- 不建议只靠分区裁剪或物化视图宣称 10 倍加速。
- 不建议一次性实现几十上百个指标，应先把 20 到 30 个高频指标做深、做准、做可测试。

