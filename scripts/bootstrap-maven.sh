#!/usr/bin/env sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=3.9.16
TOOLS_DIR="$PROJECT_DIR/.tools"
ARCHIVE="${TMPDIR:-/tmp}/apache-maven-$VERSION-bin.tar.gz"
CHECKSUM="$ARCHIVE.sha512"

mkdir -p "$TOOLS_DIR"
curl -fL --retry 3 -o "$ARCHIVE" "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/$VERSION/apache-maven-$VERSION-bin.tar.gz"
curl -fL --retry 3 -o "$CHECKSUM" "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/$VERSION/apache-maven-$VERSION-bin.tar.gz.sha512"
EXPECTED=$(tr -d '[:space:]' < "$CHECKSUM")
ACTUAL=$(shasum -a 512 "$ARCHIVE" | awk '{print $1}')
[ "$EXPECTED" = "$ACTUAL" ] || { echo "SHA-512 mismatch" >&2; exit 1; }
tar -xzf "$ARCHIVE" -C "$TOOLS_DIR"
"$TOOLS_DIR/apache-maven-$VERSION/bin/mvn" -version
