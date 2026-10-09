#!/usr/bin/env bash
# Load all original records into the project's isolated diagnostic instance.
# Never inserts a VALIDATED snapshot, even when the SQL itself executes.
set -euo pipefail
repo=${1:?Pass the project path as a WSL /mnt path}
container=dsl-doris-official
root=/var/lib/dsl-doris
purpose=$(docker inspect -f '{{index .Config.Labels "com.acme.dorisdsl.purpose"}}' "$container")
[ "$purpose" = official-data-diagnostic ] || { echo 'Refusing a container without the diagnostic ownership label'; exit 1; }
sql() { docker exec -i "$container" mysql --defaults-extra-file=/run/dsl-client.cnf --batch --raw; }
run_dir=${2:-"$repo/reports/data-inspection/$(date +%Y-%m-%d_%H%M%S)/wsl-doris"}
[ "$(docker info --format '{{.DockerRootDir}}')" = "$root/docker" ] || { echo 'Refusing a non-project daemon'; exit 1; }
[ ! -e "$run_dir" ] || { echo 'Refusing to overwrite prior evidence'; exit 1; }
objects=$(printf "SELECT COUNT(*) FROM information_schema.tables WHERE TABLE_SCHEMA='newzl';\n" | sql | tail -n 1)
[ "$objects" = 0 ] || { echo 'Refusing to rebuild a non-empty database; use the guarded recovery workflow'; exit 1; }
mkdir -p "$run_dir"
umask 077
password=$(sed -n 's/^password=//p' "$root/client.cnf")
printf 'user = "root:%s"\n' "$password" >"$root/curl.conf"
sql <"$repo/data/doris/ddl/001_rebuild_tables.sql" >"$run_dir/create-tables.log"
for table in hsj_stock_code_info hsj_stock_hq_basic hsj_stock_hq_ext; do
  file="$repo/.tools/wsl-doris/normalized/$table.normalized.csv"
  [ -s "$file" ]
  header=$(head -n 1 "$file" | tr -d '\r')
  label="diagnostic_${table}_$(date +%s)"
  echo "Loading $table (strict mode, zero filtered rows allowed)"
  curl --config "$root/curl.conf" --fail-with-body --silent --show-error \
    -X PUT -H 'Expect: 100-continue' -H "label:$label" -H 'format:csv' \
    -H 'skip_lines:1' -H 'column_separator:,' -H 'strict_mode:true' \
    -H 'max_filter_ratio:0' -H 'timeout:3600' -H "columns:$header" \
    --upload-file "$file" "http://127.0.0.1:8040/api/newzl/$table/_stream_load" \
    >"$run_dir/$table.response.json"
  # jq is intentionally unnecessary. Windows verifies detailed response counts.
  grep -Eq '"Status"[[:space:]]*:[[:space:]]*"Success"' "$run_dir/$table.response.json"
  grep -Eq '"NumberFilteredRows"[[:space:]]*:[[:space:]]*0[[:space:]]*,' "$run_dir/$table.response.json"
done
sql <"$repo/data/doris/ddl/002_semantic_view.sql" >"$run_dir/semantic-views.log"
sql <"$repo/data/doris/ddl/005_performance_features.sql" >"$run_dir/features.log"
printf '%s\n' 'SELECT COUNT(*) AS registered_snapshots FROM newzl.data_snapshot_registry;' | sql >"$run_dir/registered-snapshots.tsv"
echo 'DIAGNOSTIC_LOAD_COMPLETE_NO_VALIDATED_SNAPSHOT'
