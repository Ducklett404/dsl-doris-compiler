# 正式 DSL 编译性能门禁

基准只验证 SQL 编译，不验证行业等指标的数据可用性或查询结果正确率。归档性能报告按其原工件使用，当前记录见 [项目状态](project-status.md)。复跑前确认输出路径不存在，避免覆盖旧证据。

## 验收口径

性能门禁使用 `stock-slot-complex-v1` 语料，而不是 `SCREEN ON` 演示语法。语料固定在
`benchmarks/compiler/stock-slot-complex-v1.json`，覆盖 `indicator`、`rank/then`、
`queryData`、均线、RSI、交叉、创新高/低、区间位置、行业聚合、`CONS/EXIST`、市场集合、
跨表字段、时间范围、聚合和 `between`。

基准先校验全部语料都能编译，再执行 JVM 预热。验收车道每次绕过 AST、语义模型和 SQL
模板缓存，但复用启动时加载的同一版本注册表；因此门禁不是依靠热缓存过线。另设有界缓存
车道，用于观察生产热路径。每条车道至少执行 5,000 次，逐次记录：

- 解析、语义分析、规则重写、规划、SQL 生成和端到端耗时；
- P50、P95、P99、最大值；
- 当前线程每次编译分配的字节数（JVM 支持该计数器时）；
- AST、语义模型、SQL 模板和指标定义解析缓存的容量、大小及命中统计。

CI 的硬门禁为预热后、缓存旁路的端到端编译 `P95 < 50ms`。缓存容量分别为编译器
实例 256 项、指标定义解析 512 项，均采用同步 LRU。注册表由命令入口加载一次后注入编译器；
热路径不读取配置文件。切换注册表版本时应创建新注册表和新编译器实例，旧实例及缓存整体退役。

## 本机复跑

```powershell
java -jar target/dsl-doris-compiler.jar benchmark-stock-slot-compiler `
  --corpus benchmarks/compiler/stock-slot-complex-v1.json `
  --warmup 1000 --iterations 5000 --p95-threshold-ms 50 `
  --json-output build/compiler-performance-new.json `
  --markdown-output build/compiler-performance-new.md
```

命令在不达标时返回退出码 `4`，输入或执行错误返回 `3`。报告中的绝对耗时只代表该次 JVM、
硬件和负载；是否回归以同一 CI 运行环境中的门禁为准。

## CI

`.github/workflows/compiler-performance.yml` 在正式 DSL 文法、编译器、注册表、复杂语料或构建
配置变化时执行 5,000 次回归测试，并保存 JSON/Markdown 报告作为构建产物。测试同时检查
缓存不会超过容量，复杂语料全部成功，以及报告包含全部阶段与分位数。
