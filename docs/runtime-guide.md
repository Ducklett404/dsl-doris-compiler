# CLI、HTTP、Docker 与数据装载运行手册

## 环境

- JDK 21；Maven 3.9+；Python 3；Windows PowerShell 5.1+。
- Doris 本机验收使用 `apache/doris:all-in-one-4.1.3`，端口 `9030/8030/8040`。
- 密码只通过 `DORIS_PASSWORD` 环境变量传入，不进入命令历史或仓库。

## 一键建表、导入和快照验收

以下命令会校验三份 CSV 的 SHA-256，重建三张真实表，规范化空值，使用严格 Stream Load
导入，创建语义视图，校验行数、日期范围、唯一键和表间关联，最后登记 `VALIDATED` 快照。
默认重建会删除同名旧表；保留表结构时显式使用 `-NoRebuild`。

```powershell
$env:DORIS_PASSWORD = '<装载账号密码>'
./scripts/doris/setup-load-validate.ps1 `
  -DataRoot 'D:\path\to\Doris A股行情数据集' `
  -MySqlContainer doris -User dsl_loader
```

需要同时建立冻结日性能特征时追加 `-BuildPerformanceFeatures`。装载响应、失败记录和失败行保存在
`data/doris/runs/<snapshot>/<run-id>/`。

## 一键构建、测试和启动

前台 HTTP：

```powershell
./scripts/build-test-start.ps1 -MavenExecutable mvn.cmd -Mode Http
```

Docker 后台：

```powershell
./scripts/build-test-start.ps1 -MavenExecutable mvn.cmd -Mode Docker
docker compose logs -f compiler
docker compose down
```

只验证构建和性能门禁使用 `-Mode VerifyOnly`。

## CLI

```powershell
# 编译正式 DSL
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql `
  examples/registry-smoke.dsl --format json

# 受控执行（只读账号、VALIDATED 快照、EXPLAIN 扫描门禁）
$env:DORIS_PASSWORD = '<只读账号密码>'
java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql `
  examples/registry-smoke.dsl --user dsl_runtime_reader `
  --snapshot-id stock-20060104-20260414-v1 --format markdown `
  -o reports/final/query.md

# 复杂正式语料编译性能
java -jar target/dsl-doris-compiler.jar benchmark-stock-slot-compiler `
  --warmup 1000 --iterations 5000 --p95-threshold-ms 50
```

## HTTP

编译服务：

```powershell
java -jar target/dsl-doris-compiler.jar serve --host 127.0.0.1 --port 8080
```

```bash
curl -X POST http://127.0.0.1:8080/compile \
  -H 'Content-Type: application/json' \
  --data-binary '{"dslVersion":"stock-slot-v1","dsl":"indicator('\''沪'\'', '\'''\'', '\''收盘价'\'', '\''2026-04-14'\'', '\'''\'', '\'''\'', '\'''\'') > 10"}'
```

带 Doris 执行的 HTTP 服务使用 `serve-doris`。该入口启动时检查只读授权，提供 `/compile`、
`/execute` 和 `/health`。Docker Compose 默认只启动无数据库依赖的编译服务；将数据库密码放入
镜像或 Compose 文件属于禁止做法。

## Docker

```powershell
mvn.cmd -B -DskipTests package
docker compose up -d --build
curl.exe http://127.0.0.1:8080/health
```

容器为只读根文件系统并仅挂载临时 `/tmp`。`docker-compose.yml` 固定暴露 `8080`，
`Dockerfile` 固定使用 JRE 21 和已构建的 fat JAR。
