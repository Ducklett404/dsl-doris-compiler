#!/usr/bin/env bash
# Run only inside the dedicated project WSL distribution. No production target.
set -euo pipefail
repo=${1:?Pass the project path as a WSL /mnt path}
container=dsl-doris-official
image=apache/doris:all-in-one-4.1.3
root=/var/lib/dsl-doris
mkdir -p "$root/fe-meta" "$root/be-storage" /var/log/dsl-doris
if ! docker info >/dev/null 2>&1; then
  nohup dockerd --host unix:///var/run/docker.sock --data-root "$root/docker" \
    --iptables=false --ip6tables=false --bridge=none --ip-masq=false \
    >/var/log/dsl-doris/docker.log 2>&1 </dev/null &
  for attempt in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi
if ! docker image inspect "$image" >/dev/null 2>&1; then
  docker load -i "$repo/.tools/wsl-doris/image/apache-doris-all-in-one-4.1.3-amd64.tar"
fi
sysctl -w vm.max_map_count=2000000
if [ ! -f "$root/client.cnf" ]; then
  umask 077
  password=$(openssl rand -hex 24)
  printf '[client]\nuser=root\npassword=%s\nhost=127.0.0.1\nport=9030\ndefault-character-set=utf8mb4\n' "$password" >"$root/client.cnf"
fi
if docker container inspect "$container" >/dev/null 2>&1; then
  purpose=$(docker inspect -f '{{index .Config.Labels "com.acme.dorisdsl.purpose"}}' "$container")
  [ "$purpose" = official-data-diagnostic ] || { echo 'Refusing a container without the diagnostic ownership label'; exit 1; }
  docker start "$container" >/dev/null
else
  docker run -d --name "$container" --network host --memory=10g --cpus=6 \
    --label com.acme.dorisdsl.purpose=official-data-diagnostic \
    --ulimit nofile=65536:65536 \
    --mount "type=bind,source=$root/fe-meta,target=/opt/apache-doris/fe/doris-meta" \
    --mount "type=bind,source=$root/be-storage,target=/opt/apache-doris/be/storage" \
    --mount "type=bind,source=$root/client.cnf,target=/run/dsl-client.cnf,readonly" \
    "$image"
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
if [ ! -f "$root/credentials-initialized" ]; then
  # First startup: replace the official image's empty root password.
  password=$(sed -n 's/^password=//p' "$root/client.cnf")
  if ! printf "SET PASSWORD FOR 'root'@'%%' = PASSWORD('%s');\n" "$password" |
    docker exec -i "$container" mysql --defaults-extra-file=/run/dsl-client.cnf 2>/dev/null; then
    printf "SET PASSWORD FOR 'root'@'%%' = PASSWORD('%s');\n" "$password" |
      docker exec -i "$container" mysql -uroot -h127.0.0.1 -P9030
  fi
  touch "$root/credentials-initialized"
fi
docker exec "$container" mysql --defaults-extra-file=/run/dsl-client.cnf -N \
  -e 'SELECT VERSION(); SHOW BACKENDS;'
echo 'WSL_DORIS_HEALTHY'
