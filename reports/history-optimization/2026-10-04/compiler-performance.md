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
|parse|0.041|0.089|0.129|1.927|
|semantic|0.010|0.028|0.046|0.157|
|rewrite|0.000|0.000|0.000|0.008|
|planning|0.001|0.004|0.006|0.113|
|sqlGeneration|0.035|0.105|0.162|2.367|
|total|0.091|0.219|0.314|2.430|

Allocated bytes/compile: P50=70440.000, P95=96368.000, P99=99168.000, Max=99536.000.

## BOUNDED_CACHE_HOT_PATH

Iterations: 5000

| Stage | P50 ms | P95 ms | P99 ms | Max ms |
|---|---:|---:|---:|---:|
|parse|0.000|0.000|0.000|0.000|
|semantic|0.000|0.000|0.000|0.000|
|rewrite|0.000|0.000|0.000|0.000|
|planning|0.000|0.000|0.000|0.000|
|sqlGeneration|0.000|0.000|0.000|0.000|
|total|0.000|0.001|0.002|0.017|

Allocated bytes/compile: P50=112.000, P95=112.000, P99=112.000, Max=112.000.


## 有界缓存

| AST | Semantic | SQL template | Capacity | SQL hits/misses |
|---:|---:|---:|---:|---:|
|10|10|10|256|6000/10|

指标定义解析缓存：size=9 / capacity=512, hits/misses=29492/9。注册表文件仅在基准启动时加载一次。
