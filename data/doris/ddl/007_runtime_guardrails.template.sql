-- Replace all runtime/benchmark user and password placeholders before execution.
-- Do not commit the substituted file.
-- This script requires an administrator and creates a SELECT-only runtime identity.

CREATE USER IF NOT EXISTS '__RUNTIME_USER__'@'%' IDENTIFIED BY '__RUNTIME_PASSWORD__';
GRANT SELECT_PRIV ON newzl.* TO '__RUNTIME_USER__'@'%';

CREATE WORKLOAD GROUP IF NOT EXISTS dsl_runtime
PROPERTIES (
  "max_memory_percent"="20%",
  "max_concurrency"="4",
  "max_queue_size"="16",
  "queue_timeout"="2000",
  "scan_thread_num"="4"
);

GRANT USAGE_PRIV ON WORKLOAD GROUP 'dsl_runtime' TO '__RUNTIME_USER__'@'%';
SET PROPERTY FOR '__RUNTIME_USER__'
  'query_timeout' = '10',
  'exec_mem_limit' = '536870912',
  'default_workload_group' = 'dsl_runtime';

CREATE WORKLOAD POLICY IF NOT EXISTS dsl_runtime_scan_rows
CONDITIONS(be_scan_rows > 1000000) ACTIONS(cancel_query)
PROPERTIES('workload_group'='dsl_runtime', 'priority'='100', 'enabled'='true');

CREATE WORKLOAD POLICY IF NOT EXISTS dsl_runtime_query_time
CONDITIONS(query_time > 10000) ACTIONS(cancel_query)
PROPERTIES('workload_group'='dsl_runtime', 'priority'='100', 'enabled'='true');

-- A separate SELECT-only identity prevents the acceptance baseline from being
-- cancelled by the 10-second online-serving policy.
CREATE USER IF NOT EXISTS '__BENCHMARK_USER__'@'%' IDENTIFIED BY '__BENCHMARK_PASSWORD__';
GRANT SELECT_PRIV ON newzl.* TO '__BENCHMARK_USER__'@'%';

CREATE WORKLOAD GROUP IF NOT EXISTS dsl_benchmark
PROPERTIES (
  "max_memory_percent"="40%",
  "max_concurrency"="1",
  "max_queue_size"="1",
  "queue_timeout"="120000",
  "scan_thread_num"="8"
);

GRANT USAGE_PRIV ON WORKLOAD GROUP 'dsl_benchmark' TO '__BENCHMARK_USER__'@'%';
SET PROPERTY FOR '__BENCHMARK_USER__'
  'query_timeout' = '120',
  'exec_mem_limit' = '2147483648',
  'default_workload_group' = 'dsl_benchmark';

CREATE WORKLOAD POLICY IF NOT EXISTS dsl_benchmark_query_time
CONDITIONS(query_time > 120000) ACTIONS(cancel_query)
PROPERTIES('workload_group'='dsl_benchmark', 'priority'='100', 'enabled'='true');
