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
|parse|0.039|0.082|0.134|2.255|
|semantic|0.011|0.027|0.048|0.189|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.002|0.004|0.005|0.032|
|sqlGeneration|0.080|0.211|0.321|2.174|
|total|0.135|0.316|0.477|2.564|

Allocated bytes/compile: P50=94352.000, P95=166688.000, P99=169464.000, Max=170016.000.

## BOUNDED_CACHE_HOT_PATH

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.000|0.000|0.000|0.000|
|semantic|0.000|0.000|0.000|0.000|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.000|0.000|0.000|0.000|
|sqlGeneration|0.000|0.000|0.000|0.000|
|total|0.000|0.001|0.001|0.026|

Allocated bytes/compile: P50=120.000, P95=120.000, P99=120.000, Max=120.000.


## 有界缓存

| AST | Semantic | SQL template | Capacity | SQL hits/misses |
|---:|---:|---:|---:|---:|
|10|10|10|256|6000/10|

指标定义解析缓存：size=9 / capacity=512, hits/misses=45144/9。注册表文件仅在基准启动时加载一次。
