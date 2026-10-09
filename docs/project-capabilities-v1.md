# 当前项目能力、演示与交付 v1

版本：`project-capabilities-v1`；DSL：`stock-slot-v1`；范围冻结：`stock-slot-phase1-scope-v1.0.4`（注册表仍为 v1.0.2）。本表描述收到的三份 CSV 和项目内部计算契约。v1.0.4 将六个 BIGINT 价格字段及均价通过显式 DECIMAL 边界规范化，避免精确源倍率经 DOUBLE 舍入；真实运行前须重建语义视图并生成新证书。原始快照与数学定义不变。它不改变正式 `VALIDATED` 门禁；正式数据认可、独立外部盲测和正式目标环境性能验收仍为 `BLOCKED`。

## 数据与 19 项指标

固定快照 `stock-20060104-20260414-v1`：代码表 5,686 行；基础行情 13,650,347 行，2006-01-04 至 2026-04-14；衍生行情 6,170,822 行，2018-08-20 至 2026-04-14。三份原始文件共 19,826,855 行，SHA-256 与大小固定在 [manifest](../data/doris/snapshots/stock-20060104-20260414-v1/manifest.json)。文件不随代码或交付 ZIP 分发，需要单独提供。

| 指标 | 原始定义 | 项目单位 | 依赖与缺值 |
|---|---|---|---|
| 最新价 | `lastPx/10000` | 元 | 基础；原始 NULL 保留 |
| 昨收价 | `preClosePx/10000` | 元 | 基础；0 保留 |
| 开盘价 | `openPx/10000` | 元 | 基础 |
| 最高价 | `highPx/10000` | 元 | 基础 |
| 最低价 | `lowPx/10000` | 元 | 基础 |
| 收盘价 | `closePx/10000` | 元 | 基础 |
| 成交量 | `volume` | 股 | 基础；0 保留 |
| 成交额 | `turnover/100` | 元 | 基础；0 保留 |
| 量比 | `quantRatio/10000` | 比值 | 基础；CSV 字段为 `quantRatio` |
| 换手率 | `turnRatio/10000` | 百分点 | 基础 |
| 真实换手率 | `trueTurnRatio/10000` | 百分点 | 基础 |
| 总市值 | `lastPx/10000*totalShare` | 元 | 任一计算字段 NULL 则 NULL |
| 流通市值 | `lastPx/10000*listedShare` | 元 | 任一计算字段 NULL 则 NULL |
| 涨跌幅／涨幅 | `(lastPx-preClosePx)*100/preClosePx` | 百分点 | 任一字段 NULL 或昨收 0 则 NULL |
| 均价 | `turnover/(100*volume)` | 元 | 任一字段 NULL 或成交量 0 则 NULL；分母先按 DOUBLE 计算，避免分步除法的额外舍入 |
| 前复权收盘价 | `closePx/10000*qfqMulti+qfqAdd` | 元 | 任一价格／乘数／加数 NULL 则 NULL |
| 后复权收盘价 | `closePx/10000*hfqMulti+hfqAdd` | 元 | 任一价格／乘数／加数 NULL 则 NULL |
| 主力净流入 | `ZJLXMainNetTur` | 项目资金金额口径 | 衍生；缺行、NULL、`-999999` 转 NULL；其他负值有效 |
| 振幅 | `amplitude/10000` | 百分点 | 基础；不重复缩放已规范化伴随列 |

单位、复权因子和资金哨兵采用现有项目假设，尚无完整官方口径确认。`2.5%` 表示 2.5 百分点；非资金字段不会统一按 `-999999` 当缺值处理。原始记录保留。249,480 条衍生行无同日基础行情，3,487 条价格范围警告需披露；不能补造价格或改用其他日期关联。来源按 `(mktcode,tgtcode,bizdate)` 关联，证券代码为文本，保留前导零。

指标具体聚合白名单、精确位置区间的 decimal 规则及解释见 [字段规则](project-field-rules.md)、[冻结范围](../config/acceptance/stock-slot-phase1-scope-v1.json)。注册表包含更多可编译概念时，以本冻结范围决定实际可执行能力。

## 窗口、函数和组合

| 能力 | 支持范围及明确限制 |
|---|---|
| `indicator`、四则运算、AND/OR、括号、比较 | 仅注册指标和冻结类型／单位；明确日期；聚合仅配置允许的 MAX/MIN/AVG/SUM |
| `N日均线` | N=1..5000；N 条真实观察行的收盘价平均，完整非 NULL 窗口；语法允许不保证长窗口在本机资源内可执行 |
| `RSI(N)` | N=1..5000；N 个完整价格差值，需要 N+1 条观察；平均下跌为 0 等零分母返回 NULL，沿用冻结公式 |
| `rank`、`then` | 默认 DENSE_RANK；可选 RANK/DENSE_RANK/ROW_NUMBER，升降序；NULL 值不参与排名；THEN 先筛选后排名；ROW_NUMBER 用市场／文本代码稳定破同分；行业分组排除 |
| `limit x,y` | x 是数量下界声明，y 是数量上界；不是 SQL OFFSET；本版 SQL 只用非 -1 的 y 限制结果，执行器仍有独立返回行预算 |
| `queryData` | 一个精确文本代码或当前代码快照名称；同评价日和市场；无目标／目标日期缺行为 NULL；不承诺历史名称生效时间；跨证券样本原因标记 `PARTIAL_DETAIL` |
| `record_high/record_low` | N 条观察或历史区间极值；有限窗口必须完整非 NULL；与极值相等也命中 |
| `position` | 低／中／高三等分，低和高的三分之一边界包含等号；平坦区间 NULL；模式 MA/RSI 不作为 position 直接字段 |
| `cross_above/cross_down` | 当前与前一真实观察记录比较，任一操作数 NULL 则 NULL |
| `close_together/reset/golden_cross` | 相对差不超过 1%；reset 为重新站上；golden_cross 由调用者提供短、长序列；遵守已有固定公式 |
| CONS/EXIST | 仅 `>=N日` 与 `=N日`；CONS=N 需要第 N+1 条判定；EXIST 在最近 max(20,N) 条观察计次；未知条件不计命中，观察不足时次数结果 NULL；次数结果缺值与次数输入未知分别统计 |

单证券窗口固定分区 `(mktcode,tgtcode)`、按 `bizdate ASC` 排序。N日始终指观察记录数；停牌间隔不补行、NULL 不插值、新股不改用短窗口。执行前保留实际窗口依赖行，不能按固定自然日数裁剪。

市场包括深(0)、沪(1)、京(103)，支持 `|`、`&`、`^` 的冻结集合语义；空市场表示实际快照中的证券。筛选范围取评价日真实基础行情。日期支持 `YYYY-MM-DD`、中文绝对日期及允许聚合的 `明确日期近N日`；早于衍生来源的资金可为空，休息日／无行情日返回 `NO_OBSERVATIONS`。

排除财务、行业、概念／指数成分、基金／ETF／债券及海外市场；范围槽和标的类型槽须空。行业代码字段全部为空。`今天`、财报期、开始／前／后偏移、多评价日期、增长聚合等未冻结形式明确拒绝。

## 受控执行与解释

项目矩阵采用只读账号、参数绑定、10 秒查询上限、2GiB 单查询内存、一亿估算扫描行和 10,000 返回行预算；这些是项目诊断设置，不是所有入口的默认值。普通受控默认更小，见运行命令帮助。资源超限需要明确拒绝／超时，不能扩大预算使场景表面通过。

可用性在用户过滤、THEN、排名和 LIMIT 之前计算。各输入的 NULL 人数可重叠；当前衍生缺行、次数输入未知和次数结果未知分列。解释最多展开 20 只缺值证券、每个原因前 20 个真实日期；每只最多读取 10001 条历史观察加截断探测、32 个字段，每输入最多 250000 步。跨证券原因、预算超限或辅助查询失败标 `PARTIAL_DETAIL`；主结果和 SQL 确认的缺失计数仍独立有效。最多 20 个样本的完整解释不等于全量原因分析。

## 一次项目验收与演示

无数据库环境的入口可在本机或普通 CI 运行：

```powershell
python -m pip install -r scripts/doris/requirements-selftest.txt
mvn -B test package
python scripts/doris/run_project_acceptance.py --report-dir reports/project-acceptance/new-portable --java java
```

状态 `PASS_OFFLINE_REAL_NOT_RUN` 表示便携校验通过，真实数据未运行。已具备专用 WSL/Doris、三份原始文件和独立审计 DuckDB 时显式运行：

```powershell
python scripts/doris/run_project_acceptance.py `
  --with-doris --report-dir reports/project-acceptance/new-live --java java `
  --distribution dsl-doris-official-01a104f9 `
  --data-root 'D:\data\Doris A股行情数据集' `
  --reference-database 'target/data-audit/official.duckdb' --rounds 30 --restart
```

`PROJECT_PASS_FORMAL_BLOCKED` 才表示本轮项目验收完整通过；`NOT_RUN` 表示前置环境不足；`FAIL` 是实际失败。输出 JSON 与中文汇总包含本轮状态、源码／JAR／注册表／规则／矩阵／证书／数据清单哈希和各阶段证据。独立原始 DuckDB 必须关闭并完成 checkpoint，无非空 WAL；其文件内容 SHA-256 和大小也绑定身份，完成时重新核对，同路径替换不能复用旧证据。失败目录保留，`--resume` 只复用身份与工件哈希一致的已通过阶段；目录不得覆盖。真实数据工作流仅显式触发 `project-data-acceptance`，普通 CI 的绿色状态不代表这个步骤通过。

演示可先编译 `examples/project-basic.dsl`，展示 AST、规则轨迹、逻辑计划和参数化 SQL；然后对本轮来源证书执行：

完整真实验收必须显式指定 `--restart`，以授权重启已校验所有权的专属诊断容器；未指定时前置检查记录 `NOT_RUN`，不能只测并发和超时便宣称稳定性全部通过。独立资源脚本不带该参数只能用于不含重启的诊断。

```powershell
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/project-basic.dsl --format json
java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql examples/project-basic.dsl `
  --host HOST --user READ_ONLY_USER --password-env DORIS_PASSWORD `
  --project-validation reports/project-acceptance/new-live/sources-attempt-001/project-validation.json `
  --max-scan-rows 100000000 --max-exec-memory-bytes 2147483648 --format markdown
```

证书路径以实际本轮目录为准；来源验证后才能执行。矩阵中的复杂 DSL、全结果顺序及缺值解释保存在同一批工件里。正式七步演示仍用 [正式演示脚本](final-demo.md)，要求合格 `VALIDATED` 快照；当前项目演示不替代其十倍加速与外部正确率结论。

2026-10-04/05 既有报告属于历史证据，里面的计数／P95／加速比仅适用于当时的 JAR、快照和缓存条件。本次结果只引用 `new-live` 等当前目录；没有本轮真实结果时不能展示历史股票列表为刚执行结果。

## 冻结交付与恢复

在最终源码改动完成并完成对应验收后生成一个新交付目录：

```powershell
python scripts/doris/package_project_delivery.py `
  --evidence-dir reports/project-acceptance/new-portable `
  --output-dir reports/project-delivery/new-package --label project-v1
python scripts/doris/package_project_delivery.py --verify-dir reports/project-delivery/new-package
```

它只打包本批次证据、匹配证据哈希的 JAR、实际源码／配置／说明和复跑脚本，附 `delivery-manifest.json`、逐文件 SHA-256 与 ZIP。真实结果完成后将 `--evidence-dir` 换成本轮真实目录。源码或 JAR 在验收后改变时拒绝打包。源码有未提交修改会登记 `WORKTREE_WITH_UNCOMMITTED_CHANGES`、基线提交及实际源码指纹；不能只报 HEAD 并宣称那就是交付源码。提交／推送后的最终远程 CI 需另外运行并绑定到同一版本。

恢复时按顺序执行：

1. 在新目录解压 ZIP，执行 `python payload/source/scripts/doris/package_project_delivery.py --verify-dir .`，核对 JAR、源码、证据及包内完整清单；若收到外层 ZIP，核对与发送方提供的 SHA-256 一致。
2. 源码不包含 `.git`，`payload/source/source-version.json` 保存原基线和实际源码树；统一入口在无 Git 元数据时披露该状态，重新计算源码哈希。如需 Git 提交绑定，在新 Git 克隆中切到 manifest 的 `gitRevision`，覆盖 `payload/source` 的实际文件，再核对 `source-version.json` 的全部文件哈希。保留未提交修改标记；不要把旧证据改为新机器实时结果。
3. 准备 JDK21、Maven3.9+、Python3.12；安装固定 requirements，先构建并运行便携验收。可直接运行包内 JAR 编译；构建出的 JAR需重新验收，不沿用交付 JAR的哈希证明。
4. 单独取得三份原始 CSV，逐个核对 manifest 的 SHA-256、大小、文件名和行数。按 manifest 的相对子目录保存；不能用规范化导入文件替代原文件。空间需另计原始数据、规范化副本、DuckDB、Docker存储和装载临时空间。
5. 专用 WSL环境须单独安装／创建；不得假定私有的 `dsl-doris-official-01a104f9` 已存在。现有 `bootstrap-wsl.sh`、`start-wsl-doris.sh` 用于准备专用环境；其默认容器为 `dsl-doris-official`，10GiB/6CPU。私有 client配置和装载账号在本机新建，不能复制到交付包。使用 [运行手册](runtime-guide.md)的装载说明；原始数据有已披露关联异常，正式验证预计拒绝，不能手工登记 VALIDATED。
6. 重建独立原始行 DuckDB：`python scripts/doris/audit_official_data.py --data-root 数据根目录 --database target/data-audit/official.duckdb --output-dir reports/data-inspection/new-restore`。现有原始异常可能令审计退出码为 1、报告 FAIL；检查具体原因并保留证据，不按正常成功忽略。项目运行只允许已披露且契约中保留的异常，其他变化拒绝。
7. 在已经正确装载的专用 Doris 上运行新的 `run_project_acceptance.py --with-doris`。它重新核对来源和发布证书；旧机器证书不能证明恢复后数据库内容相同。确认完整结果／顺序／缺值／解释和资源报告后，再生成新交付包。

本次打包自测验证了新目录、ZIP 解压、校验和及损坏拒绝；这不等于另一台机器已完成 3GB 原始数据装载恢复。新机器缺少 WSL、Docker镜像、原始文件或独立原始参考时，真实流程报告 `NOT_RUN`。收到的文件和环境补齐之前，不能声称完全一键恢复或正式验收通过。

核心模块索引：[文法／AST／逻辑计划](compiler-architecture.md)、[类型与指标注册](stock-slot-registry-v1.md)、[函数语义](stock-slot-function-semantics-v1.md)、[声明式规则](declarative-rule-engine.md)、[插件与零核心改动](registry-plugin-guide.md)、[运行入口](runtime-guide.md)、[项目执行／解释](project-scoped-validation.md)。
