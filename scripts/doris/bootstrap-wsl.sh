#!/usr/bin/env bash
# Execute only inside the dedicated project WSL distribution.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 update
apt-get -y --no-install-recommends -o Acquire::Retries=2 -o Acquire::http::Timeout=20 install ca-certificates curl docker.io
mkdir -p /var/lib/dsl-doris/docker /var/log/dsl-doris
if ! docker info >/dev/null 2>&1; then
  nohup dockerd --host unix:///var/run/docker.sock --data-root /var/lib/dsl-doris/docker \
    --iptables=false --ip6tables=false --bridge=none --ip-masq=false \
    >/var/log/dsl-doris/docker.log 2>&1 </dev/null &
  for attempt in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi
docker info --format '{{.ServerVersion}}'
docker pull apache/doris:all-in-one-4.1.3
echo 'DORIS_IMAGE_READY'
