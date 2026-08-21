# GitHub 更新代码 Bug 清单

检查日期：2026-08-12  
仓库：`Ducklett404/dsl-doris-compiler`  
远端主分支基线：`origin/main @ 679e42e`  
检查范围：远端 15 个 `feature/*` 更新分支，以及这些分支与 `main` 的集成状态。

## 结论

本次确认 **7 个缺陷/发布阻断项**：P0 1 个、P1 4 个、P2 2 个。

需要特别说明：远端 `main` 本身没有包含这些更新；更新分散在 15 个尚未合并的功能分支。因此，当前从 `main` 克隆、构建或发布时，用户不会得到这些新功能。各分支已有 Maven 测试全部通过（合计 172 个测试，0 failure / 0 error），但现有测试没有覆盖下述反例，也没有覆盖全部功能合并后的版本。

## 缺陷明细

### BUG-001（P0）HTTP 编译接口信任客户端自报权限，可直接伪造授权

- 影响分支：`feature/api-compilation-cache @ b3eb5af`
- 位置：
  - `src/main/java/com/acme/dorisdsl/server/CompileHttpServer.java:39-44`
  - `src/main/java/com/acme/dorisdsl/server/PermissionGate.java:12-18`
- 现象：服务端从请求 JSON 的 `context` 直接读取 `userId` 和 `permissions`，`PermissionGate` 仅检查其中是否包含字符串 `COMPILE_DSL`，没有可信身份认证、签名校验或服务端权限查询。
- 已复现：向默认服务发送以下未认证请求，返回 HTTP `200`：

```json
{
  "dsl": "SCREEN ON 2026-08-07 WHERE CLOSE > 10 LIMIT 5",
  "context": {
    "userId": "attacker",
    "permissions": ["COMPILE_DSL"]
  }
}
```

- 影响：任何能访问端口的调用方都可以自行授予编译权限；新增的权限门禁实际上可绕过。
- 建议：认证信息只能来自可信层（例如反向代理验证后的身份、签名令牌或服务端会话），再由服务端授权器查询权限；不要接受正文里的权限列表作为授权依据。

### BUG-002（P1）`CROSS_UP/CROSS_DOWN` 直接作用于基础字段时没有回看历史，结果恒为未知/空

- 影响分支：`feature/standard-indicator-pack @ eb1775d`；该逻辑也继承自基础编译器。
- 位置：`src/main/java/com/acme/dorisdsl/sql/DorisSqlGenerator.java:50-53, 83-98`
- 根因：`hasCross` 只有在 `maxWindow > 0` 时才额外增加一天回看。`CROSS_UP(CLOSE, OPEN)` 不含窗口函数，所以 `maxWindow == 0`，最终只扫描目标日；随后对单行数据做 `LAG`，`prev_close`、`prev_open` 均为 `NULL`。
- 已复现 DSL：

```text
SCREEN ON 2026-08-07 WHERE CROSS_UP(CLOSE, OPEN) LIMIT 5
```

生成 SQL 的基础层为 `WHERE q.trade_date = ?`，但信号层又使用 `LAG(close/open)`。最终条件中的历史比较为 `NULL`，合法的穿越信号无法被选中。
- 建议：只要存在跨越函数就至少回看 1 个交易日；窗口跨越则回看 `maxWindow + 1`。为基础字段与窗口指标分别增加差分用例。

### BUG-003（P1）标准指标包把 EMA 错误实现成简单移动平均 MA

- 影响分支：`feature/standard-indicator-pack @ eb1775d`
- 位置：`src/main/java/com/acme/dorisdsl/sql/DorisSqlGenerator.java:312-324`
- 根因：`WINDOW_EMA` 分支直接返回 `AVG(...) OVER (... ROWS BETWEEN N-1 PRECEDING ...)`，与 `WINDOW_AVG` 完全相同，并不是指数移动平均。
- 已复现 DSL：

```text
SCREEN ON 2026-08-07 WHERE EMA(CLOSE, 20) > 10 LIMIT 5
```

生成片段：

```sql
AVG(`close`) OVER (... ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS `ema_close_20`
```

- 影响：所有 EMA 策略被静默按 MA 计算，结果数值错误，且调用方无法从编译成功状态察觉。
- 建议：实现明确的 EMA 递推/预计算特征 lowering；在无法保证语义时拒绝编译，而不是退化为 MA。增加已知序列数值断言。

### BUG-004（P1）RSI 生成嵌套窗口函数，产出 SQL 无法按设计执行

- 影响分支：`feature/standard-indicator-pack @ eb1775d`
- 位置：`src/main/java/com/acme/dorisdsl/sql/DorisSqlGenerator.java:143-152`
- 根因：RSI 表达式在 `AVG(...) OVER (...)` 的参数内部再次放入 `LAG(...) OVER (...)`。这违背项目自身采用 `base → metrics → signals` 分层以避免嵌套窗口的约束，也会被常规 SQL 窗口语义拒绝。
- 已复现 DSL：

```text
SCREEN ON 2026-08-07 WHERE RSI(CLOSE, 14) > 50 LIMIT 5
```

生成片段包含：

```sql
AVG(GREATEST(`close` - LAG(`close`) OVER (...), 0)) OVER (...)
```

- 影响：编译器返回成功，但 Doris 执行阶段会失败；现有测试只断言 SQL 文本包含关键字，没有做 SQL 解析或真实 Doris 验证。
- 建议：先在独立 CTE 计算日变化 `LAG`，下一层再计算涨跌均值及 RSI；增加 Doris `EXPLAIN` 集成测试。

### BUG-005（P1）插件模板占位符与函数参数数量不一致时未校验，生成残缺 SQL

- 影响分支：`feature/plugin-contract @ eee3171`
- 位置：
  - `src/main/java/com/acme/dorisdsl/registry/RegistryLoader.java:50-95, 119-125`
  - `src/main/java/com/acme/dorisdsl/sql/DorisSqlGenerator.java:247-250`
- 根因：插件验证会检查危险 token、函数元数据和 arity，但不检查 `{0}`、`{1}` 等模板占位符是否连续、是否落在合法参数范围内。生成器仅替换实际传入参数对应的占位符，其余内容原样保留。
- 已复现插件：函数声明 `minArgs=maxArgs=1`，模板为 `ABS({1})`。加载和编译均成功，输出：

```sql
AND (ABS({1}) > ?)
```

- 影响：错误插件直到 SQL 执行阶段才失败；若模板来自外部团队，定位成本高。
- 建议：加载时解析所有 `{n}`，要求索引非负、严格小于 `maxArgs`，并校验每个必需参数的使用策略；生成完成后断言不存在未解析占位符。

### BUG-006（P2）更新未集成到 `main`，且关键功能分支之间已有真实合并冲突

- 影响范围：全部远端更新分支。
- 现象：`origin/main` 仍为 `679e42e`；15 个 `feature/*` 分支均未合入。以 API 缓存分支和 DSL 类型系统分支做虚拟合并时，`CompileHttpServer.java` 出现内容冲突。
- 影响：
  - 从默认分支构建仍是旧版本，新功能对正常用户不可见。
  - 单分支测试全绿不能证明最终组合版本可编译或正确。
  - 多个分支同时修改 `DslCompiler`、`DorisSqlGenerator`、`RegistryConfig`、`RuleEngine` 等核心文件，后续集成需要人工语义合并，不能简单依次合并。
- 建议：建立专用集成分支，按依赖顺序合并；解决冲突后重新执行完整测试、差分测试、SQL 解析/EXPLAIN 与端到端自测，再更新 `main`。

### BUG-007（P2）Doris 执行器模块未进入根构建，且提交了 26 个 `target/` 构建产物

- 影响分支：`feature/doris-explain-profile @ a6ddbd4`
- 位置：`executor-doris/pom.xml` 以及 `executor-doris/target/**`
- 现象：根 `pom.xml` 没有声明多模块聚合，执行根目录 `mvn test` 不会测试 `executor-doris`；同时该分支把 `.class`、Surefire 报告和 Maven 状态文件等 26 个生成文件提交到了 Git。
- 影响：默认 CI/本地根构建可能漏测执行器；二进制产物会污染评审、造成平台/JDK 差异和无意义冲突。
- 建议：把根工程改为显式多模块或在 CI 中单独执行 `mvn -f executor-doris/pom.xml test`；删除已跟踪的 `target/`，并确保 `.gitignore` 覆盖所有子模块构建目录。

## 兼容性问题（合并时必须一并处理）

`feature/api-compilation-cache` 的原始 DSL 安全正则会扫描整段源码，因而会把合法字符串字面量中的 SQL 关键字误判为攻击。例如：

```text
SCREEN ON 2026-08-07 WHERE MARKET IN ['SELECT'] LIMIT 5
```

当前该分支会返回 `DSL_UNSAFE_TOKEN`。若与 `feature/dsl-syntax-type-system` 合并，后者允许 `USING USER='...'`，包含 `select`、`drop` 等普通子串的合法用户或分类值也会被拒绝。建议删除基于整段文本的 SQL 关键字黑名单，依赖 ANTLR 文法和受控 lowering；若仍需预过滤，应先正确词法化并排除字符串字面量。

## 验证记录

- 拉取并检查远端引用，确认本地 `main` 与 `origin/main` 一致、工作区未被修改。
- 对 15 个功能分支分别从 Git 对象导出隔离副本并运行根 Maven 测试。
- 对 `executor-doris` 子模块额外单独运行 Maven 测试。
- 总计：172 tests，0 failures，0 errors，0 skipped。
- 额外执行 5 组针对性复现：伪造权限请求、基础字段 `CROSS_UP`、EMA、RSI、插件非法占位符；均复现上述问题。
- 执行 `git diff --check`；除两个窗口测试 CSV 的尾部空行外未发现补丁格式错误。
- 未连接真实 Doris 集群，因此 RSI 的执行错误依据生成 SQL 结构与项目既定的禁止嵌套窗口设计确认；上线前仍应补跑目标 Doris 版本的 `EXPLAIN`。

## 修复优先级建议

1. 立即修复 BUG-001，修复前不要把更新后的 HTTP 服务暴露到不可信网络。
2. 修复 BUG-002～BUG-005，并为每个复现补回归测试。
3. 创建集成分支处理 BUG-006，得到一个可构建、可测试的候选版本。
4. 清理并纳管执行器模块（BUG-007），最后在目标 Doris 环境做端到端验收。
