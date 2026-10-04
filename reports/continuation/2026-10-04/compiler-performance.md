# 正式 DSL 编译性能报告

| 项目 | 值 |
|---|---|
| Compiler | 0.1.0 |
| Registry | stock-slot-registry-v1.0.1 |
| Corpus | stock-slot-complex-v1 / 10 cases |
| Warmup | 1000 |
| Required uncached P95 | < 50.0 ms |
| Result | PASS |

## UNCACHED_PHASES_AFTER_JVM_WARMUP

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.039|0.084|0.134|1.504|
|semantic|0.010|0.027|0.048|3.822|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.001|0.004|0.007|0.057|
|sqlGeneration|0.030|0.094|0.147|1.731|
|total|0.085|0.202|0.323|3.988|

Allocated bytes/compile: P50=72024.000, P95=97880.000, P99=98232.000, Max=100752.000.

## BOUNDED_CACHE_HOT_PATH

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.000|0.000|0.000|0.000|
|semantic|0.000|0.000|0.000|0.000|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.000|0.000|0.000|0.000|
|sqlGeneration|0.000|0.000|0.000|0.000|
|total|0.001|0.001|0.002|0.175|

Allocated bytes/compile: P50=112.000, P95=112.000, P99=112.000, Max=112.000.


## 有界缓存

| AST | Semantic | SQL template | Capacity | SQL hits/misses |
|---:|---:|---:|---:|---:|
|10|10|10|256|6000/10|

指标定义解析缓存：size=9 / capacity=512, hits/misses=29492/9。注册表文件仅在基准启动时加载一次。
