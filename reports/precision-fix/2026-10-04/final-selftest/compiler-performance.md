# 正式 DSL 编译性能报告

| 项目 | 值 |
|---|---|
| Compiler | 0.1.0 |
| Registry | stock-slot-registry-v1.0.2 |
| Corpus | stock-slot-complex-v1 / 10 cases |
| Warmup | 1000 |
| Required uncached P95 | < 50.0 ms |
| Result | PASS |

## UNCACHED_PHASES_AFTER_JVM_WARMUP

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.039|0.087|0.133|1.810|
|semantic|0.010|0.027|0.047|0.222|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.001|0.004|0.006|0.063|
|sqlGeneration|0.033|0.100|0.162|1.408|
|total|0.086|0.209|0.333|2.279|

Allocated bytes/compile: P50=71120.000, P95=100248.000, P99=103048.000, Max=103744.000.

## BOUNDED_CACHE_HOT_PATH

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.000|0.000|0.000|0.000|
|semantic|0.000|0.000|0.000|0.000|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.000|0.000|0.000|0.000|
|sqlGeneration|0.000|0.000|0.000|0.000|
|total|0.000|0.001|0.003|0.047|

Allocated bytes/compile: P50=120.000, P95=120.000, P99=120.000, Max=120.000.


## 有界缓存

| AST | Semantic | SQL template | Capacity | SQL hits/misses |
|---:|---:|---:|---:|---:|
|10|10|10|256|6000/10|

指标定义解析缓存：size=9 / capacity=512, hits/misses=31298/9。注册表文件仅在基准启动时加载一次。
