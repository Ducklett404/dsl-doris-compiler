#!/usr/bin/env bash
# The image's internal registration probes use mysql without --defaults-extra-file.
# Supply the persisted root credential on restarts without logging it or baking it
# into the image / Docker environment configuration.
set -euo pipefail
export MYSQL_PWD
MYSQL_PWD=$(sed -n 's/^password=//p' /run/dsl-client.cnf)
[ -n "$MYSQL_PWD" ] || { echo 'Persisted Doris credential is missing'; exit 1; }
install -D -m 700 /run/dsl-internal-mysql.sh /run/dsl-tools/mysql
export PATH="/run/dsl-tools:$PATH"
# The 2GiB per-query budget is independent of the whole BE process. On the
# owned 5GiB container, 40% leaves no room for caches/runtime beside a query.
# A private, validated override supports a retained-data restart and rollback.
# DSL_BE_MEMORY_PERCENT_OVERRIDE_V1
be_memory_percent=${DSL_DORIS_BE_MEMORY_PERCENT:-60}
if [ -f /run/dsl-be-memory-percent ]; then
  be_memory_percent=$(cat /run/dsl-be-memory-percent)
fi
be_memory_percent=${be_memory_percent%$'\r'}
case "$be_memory_percent" in 40|60) ;; *) echo 'Invalid project BE process memory percentage' >&2; exit 1 ;; esac
be_extra=$(printf '%s\n' "${BE_CONFIG_EXTRA:-}" | sed '/^[[:space:]]*mem_limit[[:space:]]*=/d')
export BE_CONFIG_EXTRA
BE_CONFIG_EXTRA=$(printf '%s\nmem_limit = %s%%\n' "$be_extra" "$be_memory_percent")
# Opt-in small-container profile. No user SQL, data, or memory budget changes.
# DSL_BE_BOUNDED_RUNTIME_PROFILE_V1
runtime_profile=disabled-v1
if [ -e /run/dsl-be-runtime-profile ]; then
  [ ! -L /run/dsl-be-runtime-profile ] && [ -f /run/dsl-be-runtime-profile ] || { echo 'Invalid project BE runtime profile file' >&2; exit 1; }
  runtime_profile=$(cat /run/dsl-be-runtime-profile)
  runtime_profile=${runtime_profile%$'\r'}
fi
case "$runtime_profile" in
  disabled-v1) ;;
  bounded-v1)
    BE_CONFIG_EXTRA=$(printf '%s\n' "$BE_CONFIG_EXTRA" | sed -E '/^[[:space:]]*(num_cores|pipeline_executor_size|blocking_pipeline_executor_size|doris_scanner_thread_pool_thread_num|min_active_scan_threads|storage_page_cache_limit|pk_storage_page_cache_limit|je_dirty_decay_ms|JEMALLOC_CONF)[[:space:]]*=/d')
    BE_CONFIG_EXTRA=$(printf '%s\n' "$BE_CONFIG_EXTRA" \
      'num_cores = 4' \
      'pipeline_executor_size = 4' \
      'blocking_pipeline_executor_size = 8' \
      'doris_scanner_thread_pool_thread_num = 8' \
      'min_active_scan_threads = 8' \
      'storage_page_cache_limit = 268435456' \
      'pk_storage_page_cache_limit = 33554432' \
      'je_dirty_decay_ms = 1000' \
      'JEMALLOC_CONF="percpu_arena:disabled,narenas:8,background_thread:true,max_background_threads:4,metadata_thp:auto,muzzy_decay_ms:1000,dirty_decay_ms:1000,oversize_threshold:0,prof:true,prof_active:false,lg_prof_interval:-1,lg_extent_max_active_fit:8,lg_tcache_max:15"')
    ;;
  *) echo 'Invalid project BE runtime profile' >&2; exit 1 ;;
esac
# DSL_FE_BOUNDED_RUNTIME_PROFILE_V1
# Opt-in inherited allocator/JVM CPU bounds. Heap/query limits are untouched.
# Both JVMs inherit the CPU option; BE's explicit jemalloc profile is unchanged.
fe_runtime_profile=disabled-v1
if [ -e /run/dsl-fe-runtime-profile ] || [ -L /run/dsl-fe-runtime-profile ]; then
  [ ! -L /run/dsl-fe-runtime-profile ] && [ -f /run/dsl-fe-runtime-profile ] || { echo 'Invalid project FE runtime profile file' >&2; exit 1; }
  fe_runtime_profile=$(cat /run/dsl-fe-runtime-profile)
  fe_runtime_profile=${fe_runtime_profile%$'\r'}
fi
case "$fe_runtime_profile" in
  disabled-v1) ;;
  bounded-v1)
    [ -z "${MALLOC_ARENA_MAX:-}" ] && [ -z "${JAVA_TOOL_OPTIONS:-}" ] || { echo 'Conflicting inherited JVM runtime options' >&2; exit 1; }
    [ -z "${_JAVA_OPTIONS:-}" ] && [ -z "${JDK_JAVA_OPTIONS:-}" ] && [ -z "${GLIBC_TUNABLES:-}" ] || { echo 'Unreviewed inherited JVM or allocator overrides' >&2; exit 1; }
    export MALLOC_ARENA_MAX=4
    export JAVA_TOOL_OPTIONS='-XX:ActiveProcessorCount=4'
    ;;
  *) echo 'Invalid project FE runtime profile' >&2; exit 1 ;;
esac
exec /opt/doris-ci/entrypoint.sh
