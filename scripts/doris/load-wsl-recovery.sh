#!/usr/bin/env bash
# Load an owned EMPTY instance. Preserve sources, old reports and existing data.
# A diagnostic load is never an official VALIDATED snapshot.
set -euo pipefail
repo=${1:?Pass the project path as a WSL /mnt path}
prepared=${2:?Pass the prepared-snapshot directory}
run_dir=${3:?Pass a NEW report directory}
container=dsl-doris-official
root=/var/lib/dsl-doris
[ "$(docker info --format '{{.DockerRootDir}}')" = "$root/docker" ] || { echo 'Refusing non-project daemon'; exit 1; }
purpose=$(docker inspect -f '{{index .Config.Labels "com.acme.dorisdsl.purpose"}}' "$container")
[ "$purpose" = official-data-diagnostic ] || { echo 'Refusing a container without the diagnostic ownership label'; exit 1; }
[ ! -e "$run_dir" ] || { echo 'Report directory exists; refusing to overwrite evidence'; exit 1; }
[ -s "$prepared/prepared-snapshot.json" ] || { echo 'Prepared source certificate missing'; exit 1; }
sql() { docker exec -i "$container" mysql --defaults-extra-file=/run/dsl-client.cnf --batch --skip-column-names --raw; }
objects=$(printf "SELECT COUNT(*) FROM information_schema.tables WHERE TABLE_SCHEMA='newzl';\n" | sql)
[ "$objects" = 0 ] || { echo 'Refusing to rebuild a non-empty database; use a fresh dedicated instance'; exit 1; }
mkdir -p "$run_dir"
trap 'echo "Load failed at line $LINENO; responses and failure details are preserved" | tee -a "$run_dir/failed-loads.log" >&2' ERR
umask 077
password=$(sed -n 's/^password=//p' "$root/client.cnf")
printf 'user = "root:%s"\n' "$password" >"$root/curl.conf"
be_port=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" | sed -n 's/^DSL_DORIS_BE_HTTP_PORT=//p')
be_port=${be_port:-8040}
[[ "$be_port" =~ ^[0-9]+$ ]] && (( be_port > 0 && be_port <= 65535 )) || { echo 'Invalid BE port'; exit 1; }
python3 - "$prepared" "$run_dir" "$repo/data/doris/snapshots/stock-20060104-20260414-v1/manifest.json" <<'PY'
import hashlib,json,re,sys
from pathlib import Path
base,run,manifest_path=map(Path,sys.argv[1:])
snapshot=json.loads((base/'prepared-snapshot.json').read_text())
assert snapshot['status']=='PASS'
manifest=json.loads(manifest_path.read_text())
assert snapshot['snapshotId']==manifest['snapshotId']
assert snapshot['manifestSha256']==hashlib.sha256(manifest_path.read_bytes()).hexdigest()
expected={table:item['rows'] for table,item in manifest['files'].items()}
records=[]
for table,total in expected.items():
    item=snapshot['files'][table]
    assert item['sourceSha256']==manifest['files'][table]['sha256']
    assert item['header']==manifest['files'][table]['header']
    assert item['rows']==total and sum(p['rows'] for p in item['parts'])==total
    for part in item['parts']:
        assert re.fullmatch(r'part-[0-9]{5}\.csv',part['file'])
        path=base/table/part['file']
        with path.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        assert digest==part['sha256']
        records.append((table,str(path),part['rows'],part['sha256']))
with (run/'load-parts.tsv').open('x') as output:
    for record in records:output.write('\t'.join(map(str,record))+'\n')
PY
sql <"$repo/data/doris/ddl/001_rebuild_tables.sql" >"$run_dir/create-tables.log"
while IFS=$'\t' read -r table file rows sha; do
  part=$(basename "$file" .csv)
  response="$run_dir/$table.$part.response.json"
  header=$(head -n 1 "$file" | tr -d '\r')
  python3 - "$file" "$sha" "$prepared/$table/parts.json" <<'PY'
import csv,hashlib,json,sys
from pathlib import Path
path=Path(sys.argv[1])
with path.open('rb') as stream:
    assert hashlib.file_digest(stream,'sha256').hexdigest()==sys.argv[2], 'Part changed before upload'
with path.open(encoding='utf-8',newline='') as stream:
    assert next(csv.reader(stream))==json.loads(Path(sys.argv[3]).read_text())['header'], 'Part header differs'
PY
  label="restore_${table}_${part}_${sha:0:20}"
  echo "Loading $table / $part ($rows rows; strict, zero filtered)"
  curl --config "$root/curl.conf" --connect-timeout 10 --max-time 3600 --fail-with-body --silent --show-error \
    -X PUT -H 'Expect: 100-continue' -H "label:$label" -H 'format:csv' \
    -H 'skip_lines:1' -H 'column_separator:,' -H 'strict_mode:true' \
    -H 'max_filter_ratio:0' -H 'timeout:3600' -H "columns:$header" \
    --upload-file "$file" "http://127.0.0.1:$be_port/api/newzl/$table/_stream_load" \
    >"$response" 2>"$run_dir/$table.$part.stderr.log"
  python3 "$repo/scripts/doris/verify_recovery_load_response.py" "$response" "$rows" \
    >>"$run_dir/verified-parts.log"
done <"$run_dir/load-parts.tsv"
for entry in 'hsj_stock_code_info:5686' 'hsj_stock_hq_basic:13650347' 'hsj_stock_hq_ext:6170822'; do
  table=${entry%%:*}; expected=${entry##*:}
  for attempt in $(seq 1 60); do
    actual=$(printf 'SELECT COUNT(*) FROM newzl.%s;\n' "$table" | sql)
    [ "$actual" = "$expected" ] && break
    sleep 1
  done
  [ "$actual" = "$expected" ] || { echo "Visible row count mismatch: $table $actual/$expected"; exit 1; }
  printf '%s\t%s\n' "$table" "$actual" >>"$run_dir/source-counts.tsv"
done
sql <"$repo/data/doris/ddl/002_semantic_view.sql" >"$run_dir/semantic-views.log"
printf '%s\n' 'SELECT COUNT(*) FROM newzl.data_snapshot_registry;' | sql >"$run_dir/registered-snapshots.tsv"
[ "$(cat "$run_dir/registered-snapshots.tsv")" = 0 ]
echo 'DIAGNOSTIC_LOAD_COMPLETE_NO_VALIDATED_SNAPSHOT'
