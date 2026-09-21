# 行情选股 DSL → Doris SQL 编译器 V1

> 参赛适配提示：原有 `SCREEN ON` 编译入口和演示表结构尚不兼容主办方的槽位 DSL 与 `hsj_stock_*` 表。第二周已新增独立槽位 DSL 解析入口，但尚不生成赛事 SQL。第一周基线见 [比赛资料基线](docs/competition/WEEK1_BASELINE.md)，第二周解析结果见 [第二周解析报告](docs/competition/WEEK2_PARSER.md)。不能把解析率当作 SQL 或结果正确率。

这是报告方案的第一版可运行原型。核心链路为：

`ANTLR4 Parse Tree → 不可变 Typed AST → 语义检查 → 等价规则 → 逻辑计划 → AccessPathPlanner → 分层 Doris SQL`

当前版本重点验证确定性编译、复杂窗口正确分层、声明式扩展和编译延迟；不连接真实 Doris，也不声称已经达到 19 年查询 10 倍加速。SQL 执行性能需要接入比赛数据快照和目标 Doris 集群后验收。

## 已实现

- ANTLR4 大小写不敏感文法、源码位置和结构化语法错误。
- 强类型 AST：价格、比率、百分比、成交量、日期、字符串和布尔类型。
- `BETWEEN`、`IN`、`AND/OR/NOT`、算术、比较、排序、复权和限制。
- `MA`、`CROSS_UP`、`PE_TTM`、`ROE_TTM`，以及 JSON 插件函数。
- 自动生成 `base → metrics → signals → final` CTE，避免嵌套窗口函数。
- 交易日回看范围、点时财务 Join、参数化 SQL、字段/函数白名单。
- 编译产物包含 Typed AST、逻辑计划、访问路径候选、SQL、绑定参数、规则轨迹和诊断。
- CLI、Markdown/JSON/SQL 输出、HTTP `/compile` API、Dockerfile。
- JUnit 单元/集成/安全/插件/性能冒烟测试。

## 环境与构建

要求 JDK 21 或更高版本。仓库内已放置项目本地 Maven；如果移动项目时不携带 `.tools`，可重新下载：

```bash
./scripts/bootstrap-maven.sh
./mvnw test
./mvnw -DskipTests package
```

最终可执行文件为 `target/dsl-doris-compiler.jar`。

## 使用

仅解析主办方槽位 DSL，输出保留槽位原文和源码位置的 AST；不会执行或生成 SQL：

```bash
java -jar target/dsl-doris-compiler.jar parse-slot examples/competition_slot.dsl
java -jar target/dsl-doris-compiler.jar measure-slot-corpus build/competition-corpus/corpus.jsonl --max-failures 100 -o build/competition-corpus/slot-parse-coverage.json
```

赛事入口与下面的旧 `compile` 入口互相独立；`limit x,y` 在赛事入口中只保存两项数值（包括语料里的 `-1`），尚不做数据库分页解释。

生成 Markdown：

```bash
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl --format markdown -o result.md
```

输出 SQL 或完整 JSON：

```bash
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl --format sql
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl --format json
```

加载插件（不修改编译核心）：

```bash
java -jar target/dsl-doris-compiler.jar compile examples/basic.dsl \
  --plugin examples/custom-plugin.json --format json
```

启动 API：

```bash
java -jar target/dsl-doris-compiler.jar serve --host 127.0.0.1 --port 8080
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/compile \
  -H 'Content-Type: application/json' \
  --data-binary '{"dsl":"SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5"}'
```

编译基准与整套自测：

```bash
java -jar target/dsl-doris-compiler.jar benchmark examples/basic.dsl --iterations 5000
./scripts/self-test.sh
```

## DSL 示例

```text
SCREEN ON 2026-08-07
WHERE PE_TTM() BETWEEN 0 AND 20
  AND ROE_TTM() >= 15%
  AND CROSS_UP(MA(CLOSE, 5), MA(CLOSE, 20))
  AND MARKET IN ['SH', 'SZ']
ADJUST FORWARD
ORDER BY TURNOVER_RATE DESC
LIMIT 100
```

## 插件契约

`examples/custom-plugin.json` 演示通过 `TEMPLATE` 注册 `ABS_CHANGE`。插件模板只能是表达式片段；加载器拒绝分号、注释和 `SELECT`，DSL 的字段和函数也必须通过白名单解析。

V1 支持 `COLUMN`、`WINDOW_AVG`、`CROSS_UP` 和 `TEMPLATE` 四类 lowering。下一版应扩展前缀和、特征表新鲜度元数据、Doris 能力矩阵和 EXPLAIN/Profile 闭环。

## 目录

- `src/main/antlr4`：DSL 文法。
- `src/main/java/.../ast`：版本化 AST 数据结构。
- `semantic`、`rewrite`、`plan`、`sql`：确定性编译核心。
- `src/main/resources/registry.json`：字段、指标、表映射和 lowering 元数据。
- `src/test`：正确性、安全性、插件、HTTP 和性能测试。
- `examples`：可运行 DSL 与插件样例。

## 当前边界

- V1 只生成 SQL，不直接执行 Doris，也不接受任意 SQL 片段。
- AccessPathPlanner 会列出特征表和前缀和候选，但在接入新鲜度元数据前安全回退到明细表。
- 表名和列名是演示逻辑模型，接入真实环境时修改注册表并补充数据版本治理。
- 编译 P95 指标只覆盖内存编译链路；查询 10 秒和 10 倍加速必须在同集群、同快照、冷热分离的基准下验证。
