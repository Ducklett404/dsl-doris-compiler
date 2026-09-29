# 正式 DSL 编译性能报告

| 项目 | 值 |
|---|---|
| Compiler | 0.1.0 |
| Registry | stock-slot-registry-v1.0.0 |
| Corpus | stock-slot-complex-v1 / 10 cases |
| Warmup | 1000 |
| Required uncached P95 | < 50.0 ms |
| Result | PASS |

## UNCACHED_PHASES_AFTER_JVM_WARMUP

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.028|0.054|0.083|2.685|
|semantic|0.006|0.014|0.025|0.215|
|rewrite|0.000|0.000|0.000|0.002|
|planning|0.001|0.002|0.003|0.059|
|sqlGeneration|0.024|0.053|0.105|1.805|
|total|0.062|0.113|0.200|2.902|

Allocated bytes/compile: P50=66664.000, P95=90064.000, P99=90064.000, Max=91760.000.

## BOUNDED_CACHE_HOT_PATH

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.000|0.000|0.000|0.000|
|semantic|0.000|0.000|0.000|0.000|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.000|0.000|0.000|0.000|
|sqlGeneration|0.000|0.000|0.000|0.000|
|total|0.000|0.001|0.002|0.026|

Allocated bytes/compile: P50=112.000, P95=112.000, P99=112.000, Max=112.000.


## 有界缓存

| AST | Semantic | SQL template | Capacity | SQL hits/misses |
|---:|---:|---:|---:|---:|
|10|10|10|256|6000/10|

指标定义解析缓存：size=9 / capacity=512, hits/misses=29492/9。注册表文件仅在基准启动时加载一次。
