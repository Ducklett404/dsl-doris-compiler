#!/usr/bin/env bash
# Execute only inside the dedicated project WSL distribution.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
image_archive=${1:-}
apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 update
apt-get -y --no-install-recommends -o Acquire::Retries=2 -o Acquire::http::Timeout=20 install ca-certificates curl docker.io openssl python3
mkdir -p /var/lib/dsl-doris/docker /var/log/dsl-doris
daemon_config=$(realpath "$(dirname "$0")/../../config/doris/private-daemon.json")
if [ -e /etc/docker/daemon.json ]; then
  cmp -s "$daemon_config" /etc/docker/daemon.json || { echo 'Existing daemon configuration differs; preserved without modification'; exit 1; }
else
  install -m 644 "$daemon_config" /etc/docker/daemon.json
fi
if docker info >/dev/null 2>&1 && [ "$(docker info --format '{{.DockerRootDir}}')" != /var/lib/dsl-doris/docker ]; then
  [ "$(docker info --format '{{.DockerRootDir}}')" = /var/lib/docker ] && \
    [ -z "$(docker ps -aq)$(docker images -q)$(docker volume ls -q)" ] || { echo 'Refusing to replace an existing populated daemon'; exit 1; }
  # Only the just-installed empty Ubuntu daemon, never Docker Desktop.
  systemctl stop docker.service docker.socket
fi
if command -v systemctl >/dev/null && systemctl is-system-running >/dev/null 2>&1; then
  systemctl enable --now docker.service
fi
if ! docker info >/dev/null 2>&1; then
  nohup dockerd --host unix:///var/run/docker.sock --config-file /etc/docker/daemon.json \
    >/var/log/dsl-doris/docker.log 2>&1 </dev/null &
  for attempt in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi
[ "$(docker info --format '{{.DockerRootDir}}')" = /var/lib/dsl-doris/docker ] || { echo 'Refusing non-project daemon'; exit 1; }
docker info --format '{{.ServerVersion}}'
if [ -n "$image_archive" ]; then
  [ -s "$image_archive" ] || { echo 'Image archive missing'; exit 1; }
  docker load -i "$image_archive"
else
  docker pull apache/doris:all-in-one-4.1.3
fi
echo 'DORIS_IMAGE_READY'
