#!/usr/bin/env sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LOCAL_MAVEN="$PROJECT_DIR/.tools/apache-maven-3.9.16/bin/mvn"

if [ -x "$LOCAL_MAVEN" ]; then
  exec "$LOCAL_MAVEN" -Dmaven.repo.local="$PROJECT_DIR/.mvn-cache" "$@"
fi
if command -v mvn >/dev/null 2>&1; then
  exec mvn "$@"
fi
echo "Maven not found. Run scripts/bootstrap-maven.sh or install Maven 3.9+." >&2
exit 1
