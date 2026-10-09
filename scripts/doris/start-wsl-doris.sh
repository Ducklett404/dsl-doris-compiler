#!/usr/bin/env bash
# Run only inside the dedicated project WSL distribution. No production target.
set -euo pipefail
repo=${1:?Pass the project path as a WSL /mnt path}
container=dsl-doris-official
image=apache/doris:all-in-one-4.1.3
root=/var/lib/dsl-doris
query_port=${DSL_DORIS_QUERY_PORT:-9030}
fe_http_port=${DSL_DORIS_FE_HTTP_PORT:-8030}
be_http_port=${DSL_DORIS_BE_HTTP_PORT:-8040}
port_offset=${DSL_DORIS_PORT_OFFSET:-0}
memory=${DSL_DORIS_MEMORY:-5g}
cpus=${DSL_DORIS_CPUS:-4}
fe_heap=${DSL_DORIS_FE_HEAP:-768m}
be_heap=${DSL_DORIS_BE_HEAP:-128m}
be_memory_percent=${DSL_DORIS_BE_MEMORY_PERCENT:-60}
[[ "$port_offset" =~ ^[0-9]{1,5}$ ]] || { echo 'Invalid port offset'; exit 1; }
declare -A used_ports=()
for port in "$query_port" "$fe_http_port" "$be_http_port" "$((9010+port_offset))" "$((9020+port_offset))" "$((9050+port_offset))" "$((9060+port_offset))" "$((8060+port_offset))" "$((8070+port_offset))" "$((8050+port_offset))"; do
  [[ "$port" =~ ^[0-9]+$ ]] && (( port > 0 && port <= 65535 )) || { echo 'Invalid Doris port'; exit 1; }
  [ -z "${used_ports[$port]:-}" ] || { echo 'Duplicate Doris listen port'; exit 1; }
  used_ports[$port]=1
done
[[ "$memory" =~ ^[1-9][0-9]*[mg]$ ]] || { echo 'Invalid memory limit'; exit 1; }
[[ "$cpus" =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid CPU limit'; exit 1; }
[[ "$fe_heap" =~ ^[1-9][0-9]*m$ && "$be_heap" =~ ^[1-9][0-9]*m$ ]] || { echo 'Invalid JVM heap'; exit 1; }
[[ "$be_memory_percent" = 40 || "$be_memory_percent" = 60 ]] || { echo 'Invalid BE process memory percentage'; exit 1; }
mkdir -p "$root/fe-meta" "$root/be-storage" /var/log/dsl-doris
if ! docker info >/dev/null 2>&1; then
  nohup dockerd --host unix:///var/run/docker.sock --config-file /etc/docker/daemon.json \
    >/var/log/dsl-doris/docker.log 2>&1 </dev/null &
  for attempt in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi
[ "$(docker info --format '{{.DockerRootDir}}')" = "$root/docker" ] || { echo 'Refusing a non-project Docker daemon'; exit 1; }
if ! docker image inspect "$image" >/dev/null 2>&1; then
  docker load -i "$repo/.tools/wsl-doris/image/apache-doris-all-in-one-4.1.3-amd64.tar"
fi
sysctl -w vm.max_map_count=2000000
if [ ! -f "$root/client.cnf" ]; then
  umask 077
  password=$(openssl rand -hex 24)
  printf '[client]\nuser=root\npassword=%s\nhost=127.0.0.1\nport=%s\ndefault-character-set=utf8mb4\n' "$password" "$query_port" >"$root/client.cnf"
fi
if docker container inspect "$container" >/dev/null 2>&1; then
  purpose=$(docker inspect -f '{{index .Config.Labels "com.acme.dorisdsl.purpose"}}' "$container")
  [ "$purpose" = official-data-diagnostic ] || { echo 'Refusing a container without the diagnostic ownership label'; exit 1; }
  [ "$(sed -n 's/^port=//p' "$root/client.cnf")" = "$query_port" ] || { echo 'Existing query port differs; use start-project-environment.ps1 or the matching explicit port settings'; exit 1; }
  docker start "$container" >/dev/null
else
  for port in "$query_port" "$fe_http_port" "$be_http_port" "$((9010+port_offset))" "$((9020+port_offset))" "$((9050+port_offset))" "$((9060+port_offset))" "$((8060+port_offset))" "$((8070+port_offset))" "$((8050+port_offset))"; do
    if ss -H -ltn "sport = :$port" | grep -q .; then echo "Refusing occupied port $port"; exit 1; fi
  done
  [ -e "$root/credentials-initialized" ] || install -m 600 /dev/null "$root/credentials-initialized"
  docker run -d --name "$container" --network host --memory="$memory" --cpus="$cpus" \
    --label com.acme.dorisdsl.purpose=official-data-diagnostic \
    --restart unless-stopped \
    --env "DSL_DORIS_FE_HTTP_PORT=$fe_http_port" --env "DSL_DORIS_BE_HTTP_PORT=$be_http_port" \
    --env "FE_QUERY_PORT=$query_port" --env "FE_HTTP_PORT=$fe_http_port" \
    --env "FE_EDIT_LOG_PORT=$((9010+port_offset))" \
    --env "BE_HTTP_PORT=$be_http_port" --env "BE_HEARTBEAT_PORT=$((9050+port_offset))" \
    --env "FE_HEAP=$fe_heap" --env "BE_HEAP=$be_heap" \
    --env "DSL_DORIS_BE_MEMORY_PERCENT=$be_memory_percent" \
    --env "FE_CONFIG_EXTRA=$(printf 'query_port = %s\nhttp_port = %s\nedit_log_port = %s\nrpc_port = %s\narrow_flight_sql_port = %s\n' "$query_port" "$fe_http_port" "$((9010+port_offset))" "$((9020+port_offset))" "$((8070+port_offset))")" \
    --env "BE_CONFIG_EXTRA=$(printf 'webserver_port = %s\nheartbeat_service_port = %s\nbe_port = %s\nbrpc_port = %s\narrow_flight_sql_port = %s\nmem_limit = %s%%\n' "$be_http_port" "$((9050+port_offset))" "$((9060+port_offset))" "$((8060+port_offset))" "$((8050+port_offset))" "$be_memory_percent")" \
    --ulimit nofile=65536:65536 \
    --mount "type=bind,source=$root/fe-meta,target=/opt/apache-doris/fe/doris-meta" \
    --mount "type=bind,source=$root/be-storage,target=/opt/apache-doris/be/storage" \
    --mount "type=bind,source=$root/client.cnf,target=/run/dsl-client.cnf,readonly" \
    --mount "type=bind,source=$root/credentials-initialized,target=/run/dsl-credentials-initialized,readonly" \
    --mount "type=bind,source=$repo/scripts/doris/wsl-doris-entrypoint.sh,target=/run/dsl-entrypoint.sh,readonly" \
    --mount "type=bind,source=$repo/scripts/doris/wsl-doris-internal-mysql.sh,target=/run/dsl-internal-mysql.sh,readonly" \
    --entrypoint /usr/bin/tini "$image" -- bash /run/dsl-entrypoint.sh
fi
for attempt in $(seq 1 120); do
  status=$(docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' "$container")
  if [ "$status" = 'running healthy' ]; then break; fi
  if [[ "$status" != running* ]]; then
    docker logs --tail 30 "$container"
    exit 1
  fi
  sleep 1
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$container")" = healthy ]
if [ ! -s "$root/credentials-initialized" ]; then
  # First startup: replace the official image's empty root password.
  password=$(sed -n 's/^password=//p' "$root/client.cnf")
  if ! printf "SET PASSWORD FOR 'root'@'%%' = PASSWORD('%s');\n" "$password" |
    docker exec -i "$container" mysql --defaults-extra-file=/run/dsl-client.cnf 2>/dev/null; then
    printf "SET PASSWORD FOR 'root'@'%%' = PASSWORD('%s');\n" "$password" |
      docker exec -i "$container" mysql --no-defaults -uroot -h127.0.0.1 -P"$query_port"
  fi
  printf 'initialized\n' >"$root/credentials-initialized"
fi
docker exec "$container" mysql --defaults-extra-file=/run/dsl-client.cnf -N \
  -e 'SELECT VERSION(); SHOW BACKENDS;'
echo 'WSL_DORIS_HEALTHY'
