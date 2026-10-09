#!/usr/bin/env bash
# Provision one project-only read account. Keep credentials in the owned WSL FS.
set -euo pipefail
container=dsl-doris-official
root=/var/lib/dsl-doris
[ "$(docker info --format '{{.DockerRootDir}}')" = "$root/docker" ]
[ "$(docker inspect -f '{{index .Config.Labels "com.acme.dorisdsl.purpose"}}' "$container")" = official-data-diagnostic ]
if [ -f "$root/reader.cnf" ]; then
  docker cp "$root/reader.cnf" "$container:/run/dsl-reader.cnf" >/dev/null
  docker exec "$container" mysql --defaults-extra-file=/run/dsl-reader.cnf -N -e 'SELECT COUNT(*) FROM newzl.hsj_stock_code_info;'
  echo 'PROJECT_READER_ALREADY_READY'
  exit 0
fi
umask 077
password=$(openssl rand -hex 24)
port=$(sed -n 's/^port=//p' "$root/client.cnf")
[[ "$port" =~ ^[0-9]+$ ]] && (( port > 0 && port <= 65535 ))
printf "CREATE USER 'dsl_project_reader'@'%%' IDENTIFIED BY '%s'; GRANT SELECT_PRIV ON newzl.* TO 'dsl_project_reader'@'%%';\n" "$password" |
  docker exec -i "$container" mysql --defaults-extra-file=/run/dsl-client.cnf
printf '[client]\nuser=dsl_project_reader\npassword=%s\nhost=127.0.0.1\nport=%s\ndefault-character-set=utf8mb4\n' "$password" "$port" >"$root/reader.cnf"
docker cp "$root/reader.cnf" "$container:/run/dsl-reader.cnf" >/dev/null
docker exec "$container" mysql --defaults-extra-file=/run/dsl-reader.cnf -N \
  -e "SHOW GRANTS; SELECT COUNT(*) FROM newzl.hsj_stock_code_info;"
echo 'PROJECT_READ_ONLY_ACCOUNT_READY'
