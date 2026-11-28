#!/usr/bin/env sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
./mvnw test
./mvnw -DskipTests package
java -jar target/dsl-doris-compiler.jar compile examples/screen-v1/basic.dsl --format sql >/dev/null
java -jar target/dsl-doris-compiler.jar compile examples/screen-v1/plugins/plugin.dsl --plugin examples/screen-v1/plugins/custom-plugin.json --format json >/dev/null
java -jar target/dsl-doris-compiler.jar benchmark examples/screen-v1/basic.dsl --warmup 200 --iterations 1000
echo "SELF_TEST_OK"
