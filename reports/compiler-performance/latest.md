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
|parse|0.034|0.065|0.104|3.931|
|semantic|0.008|0.019|0.035|0.112|
|rewrite|0.000|0.000|0.000|0.001|
|planning|0.001|0.002|0.003|0.055|
|sqlGeneration|0.063|0.135|0.224|2.441|
|total|0.109|0.206|0.328|4.638|

Allocated bytes/compile: P50=90808.000, P95=161632.000, P99=162032.000, Max=163616.000.

## BOUNDED_CACHE_HOT_PATH

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.000|0.000|0.000|0.000|
|semantic|0.000|0.000|0.000|0.000|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.000|0.000|0.000|0.000|
|sqlGeneration|0.000|0.000|0.000|0.000|
|total|0.001|0.001|0.002|0.063|

Allocated bytes/compile: P50=120.000, P95=120.000, P99=120.000, Max=120.000.


## 有界缓存

| AST | Semantic | SQL template | Capacity | SQL hits/misses |
|---:|---:|---:|---:|---:|
|10|10|10|256|6000/10|

指标定义解析缓存：size=9 / capacity=512, hits/misses=45144/9。注册表文件仅在基准启动时加载一次。
