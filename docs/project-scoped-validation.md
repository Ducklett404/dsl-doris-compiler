# 按查询依赖验证现有官方数据

更新：2026-10-10；首次实现：2026-10-05。状态见 [项目状态](project-status.md)。数据提供方无法继续补充文件时，仍可使用现有数据计算并说明限制。此入口使用**项目内部规则**，不代表官方认可字段口径或正式验收通过。

新项目验收统一使用 `scripts/doris/run_project_acceptance.py --report-dir 新目录`；完整真实模式显式 `--with-doris --restart --distribution 环境名 --data-root 原始目录 --reference-database 独立DuckDB`。它绑定实际源码、JAR、配置、矩阵和输出哈希，核对各阶段退出码与报告状态；`--resume` 只复用校验通过的工件。普通便携结果为 `PASS_OFFLINE_REAL_NOT_RUN`，真实项目全程通过才为 `PROJECT_PASS_FORMAL_BLOCKED`，缺少环境为 `NOT_RUN`，真实错误为 `FAIL`。命令、能力边界、交付及恢复见 [项目能力与交付 v1](project-capabilities-v1.md)。

## 运行规则

以评价日、指定市场中实际存在的基础行情证券为筛选范围。基础价格、成交量等查询只验证基础行情；资金等查询另验证衍生行情；按名称读取证券时再验证证券代码表。未关联基础行情的衍生记录完整保留，不能补造价格，也不挪用其他日期的行情。

字段单位、数学公式和资金哨兵规则不变；现行冻结修订为 v1.0.4（注册表仍为 v1.0.2），将六个 BIGINT 价格字段和均价通过显式 DECIMAL 边界规范化，并保留 v1.0.2、v1.0.3 历史范围。真实执行前需重建语义视图并生成新证书。行业字段全空、无来源的财务字段等明确拒绝。缺失指标与不足窗口遵守既有 NULL 规则。CONS/EXIST 中 NULL 条件不计为命中，观察行不足时次数结果为 NULL；同时另列窗口条件缺失统计。

政策单独保存为 [project-data-policy-v1.json](../config/acceptance/project-data-policy-v1.json)，没有变更正式快照门禁。

## 生成运行证据

在项目目录中运行（使用已有隔离 WSL/Doris 环境）：

```powershell
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/validate_project_sources.py `
  --output-dir build/project-sources/new-run
```

输出目录必须是新的。脚本核对原始 CSV 哈希与大小，再检查 Doris 行数、日期、主键和注册字段，记录未关联行及价格警告。发布 `project-validation.json`，不写入快照登记表。

证据属于可信本地配置，HTTP 请求不能自行指定它。基础来源通过、附加来源被阻断时，基础查询仍可执行，依赖被阻断来源的查询拒绝。

## 执行与 HTTP

密码及令牌使用环境变量，不写进命令或仓库。`HOST` 与 `USER` 替换为实际地址及只读账号；输入 DSL 使用现有文件。

```powershell
java -jar target/dsl-doris-compiler.jar execute-stock-slot-sql examples/project-basic.dsl `
  --host HOST --user USER --password-env DORIS_PASSWORD `
  --project-validation build/project-sources/new-run/project-validation.json `
  --max-scan-rows 100000000 --max-exec-memory-bytes 2147483648

java -jar target/dsl-doris-compiler.jar serve-doris `
  --host HOST --user USER --password-env DORIS_PASSWORD --auth-token-env DSL_HTTP_TOKEN `
  --project-validation build/project-sources/new-run/project-validation.json `
  --max-scan-rows 100000000 --max-exec-memory-bytes 2147483648
```

扫描和内存配置来自本次本地验证范围，部署时应按资源调整。默认不加新参数的执行入口仍要求完整快照 `VALIDATED`；正式正确性和性能入口没有这个参数。

Windows 上的统一长时验收入口在进程存续期间申请 `ES_CONTINUOUS | ES_SYSTEM_REQUIRED`，只阻止因空闲计时触发的系统自动休眠，并在正常退出或异常退出的 `finally` 作用域中清除。该请求不要求显示器常亮，也不能覆盖用户手动休眠、合盖策略、关机或断电；因此机器报告将此项记为运行条件，不把它当作查询正确性证据。非 Windows 明确记录为不适用。

## 如何理解结果

JSON 新增 `dataQuality`，Markdown 新增“数据可用性”。

| 字段 | 含义 |
|---|---|
| `validationLevel=PROJECT_SCOPED` | 项目内部按来源依赖验证 |
| `officialAcceptanceEligible=false` | 不能据此宣布官方验收通过 |
| `observedSecurities` | 条件、排名、分页之前，实际有行情的证券数 |
| `currentMissingExtensionRows` | 查询依赖衍生来源时，当前范围中缺少当日衍生行情的证券数；基础查询不检查此项 |
| `inputs` | 各输入为 NULL 的证券数；次数窗口另列条件不明统计。多项可能重叠，不能相加 |
| `inputs[].inputId/window/role/requiredObservations` | 稳定输入标识、实际观察窗口、VALUE/COUNT_RESULT/COUNT_INPUT 角色与所需观察数。相同指标不同周期分开；相同值输入的重复调用可共用标识，样本标记仍按输入数组位置对应 |
| `unavailableSamples` | 最多 20 行，依次为市场、代码、当日衍生缺行标记、与 `inputs` 对应的缺失标记。1 表示缺失 |
| `sampleDetails` | 同顺序样本的结构化原因及实际相关日期，包含当前衍生缺行、历史是否截断和各输入的 EXPLAINED/PARTIAL_DETAIL 状态 |
| `coverageStatus` | `NO_OBSERVATIONS` 无行情；`PARTIAL_INPUTS` 有输入缺失；`COMPLETE_QUERY_INPUTS` 当前查询输入可计算 |
| `snapshotExtensionWithoutBasic` | 全快照保留的未关联衍生行数，与当前查询缺失不同 |
| `validationMillis` | 来源核验、EXPLAIN 与可用性诊断耗时，已包含在总耗时中；与 `timings.explainMillis` 有重叠，不相加 |

输入完整只描述当前查询，不能证明整个快照或所有字段完整。空返回可能是条件未命中、没有行情或输入未知，需结合统计查看。

输入标识基于注册表指纹、评价日、输入角色及表达式，忽略源码位置、SQL 别名和 LIMIT；值输入忽略次数参数，次数标识保留条件与阈值。它用于区分语义输入；不是排序序号。原 `function/indicator` 字段、缺失统计和样本标记保持兼容。

样本解释区分观察记录不足、来源指标 NULL、字段级哨兵、该观察日衍生缺行、平坦区间、RSI 下跌均值为零及其他零分母。COUNT_RESULT 仅说明次数结果的观察行是否完整；COUNT_INPUT 按每个历史观察日检查指标窗口，NULL 条件仍按既有规则不计为命中。

观察不足只报告所需数、已有数及实际评价记录日期，不推测不存在于数据中的交易日。`relatedDates` 是真实相关日期：对 NULL/哨兵/衍生缺行，它表示对应观察日；对平坦或零分母，它表示证据区间，不能称为缺失日期。每个原因展示前 20 个日期，并保留总数与截断标记。

Doris 将不可能命中的条件优化为空源计划时，只对完整识别的 `EMPTYSET/VEMPTYSET` 和已知纯排序、窗口、PartitionTopN、交换包装器判定零扫描；节点名称必须严格匹配，不能按前缀放行。仍核验来源、计算条件之前的输入可用性，并真实执行参数化查询，不直接合成空结果。含 Scan、Join、Union、表函数、未知算子、未知后缀或畸形编号节点且没有资源估算时，继续拒绝执行；资源预算不变。

## 核验强度与限制

每次执行复核所需来源行数及只读元数据指纹：视图包含 SQL 定义，表与视图都包含列名、类型、可空性及顺序。真实 Doris 只读账号无法使用 `SHOW CREATE`，因此采用 `information_schema`，执行账号保持只读。

这些检查能拦截行数或视图/列定义变化，不能检测同一行数、同一结构的数据内容替换。依赖不可变装载快照和只读查询账号，任何外部修改后都必须重新验证。当前使用原始明细，不读取未经此入口验证的特征表。

完整历史的窗口覆盖统计曾超过本机 2GB 查询内存限制。项目路径按每个函数的实际观察行依赖保留历史：MA/有限 position/极值需 N 条，RSI 需 N+1 条，交叉需 2 条。次数条件将每个比较操作数的依赖再增加“次数观察范围减一”，取整个查询的最大需求。例如 RSI(5) 的 EXIST>=3日采用 20 条条件观察记录，需要 25 条价格；MA20 的同类条件需要 39 条。两个函数比较时同时考虑两边，不能仅保留带次数参数的函数所需行。

保留行包括 NULL 与停牌间隔，不按固定日历天数截断；有限窗口混合、CONS/EXIST、当前横截面排名可使用这条路径。先裁剪基础观察行，再按完整三键左关联衍生来源；不能因缺失衍生行删除基础观察。无限历史、queryData、行业/代码关联及未验证特征组合保留完整参考计算。`FULL_SCAN_REFERENCE` 路径原样保留。

项目执行器用一次有界只读查询取得输入缺失总数与前 20 个缺失样本。总数在条件、THEN、排名、LIMIT 和样本裁剪前计算；没有观察记录时返回零统计。旧的分离 SQL 保留用于参考核对，生产执行不再分别重算统计和样本。裁剪仍需要扫描基础历史以找到实际最后 N 条，不能将窗口计算减少等同于原始表读取量按比例减少。可用性统计及来源身份核验仍有开销，单次耗时不能作为正式性能验收。

有缺失样本时，再执行一次参数绑定的只读历史查询，最多读取 20 只证券、每只 10001 条观察和 1 条截断探测记录、32 个指标字段；先保留基础观察，再按市场/代码/日期三键关联衍生行情。沿用 10 秒、2GiB 与一亿估算扫描行预算。无缺失样本时跳过该查询。主结果的 10000 行上限独立有效。

解释每个输入最多执行 250000 步；跨证券目标查询、超过读取/计算预算或解释查询失败时，返回 `PARTIAL_DETAIL` 与具体原因代码。辅助解释失败不改变 SQL 已确认的缺失统计及主结果；完全解释状态也只适用于最多 20 个样本。该读取增加可用性检查耗时，性能报告需包含这项开销。

官方单位、哨兵及价格范围口径未获额外确认；外部盲测与正式完整快照验收仍未完成。

## 分项自测与组合矩阵

统一 `scripts/test-all.ps1` 和普通 GitHub CI 现在执行独立多指标与排名／queryData／CONS/EXIST 参考，以及便携组合 SQL 边界；原 94 组逐字段场景保留。正式的两份组合矩阵固定在 `config/acceptance/project-combination-matrix-v1.json` 和 `config/acceptance/project-rank-matrix-v1.json`，其哈希与实际执行工件同时保存。需要真实官方行时显式触发 `project-data-acceptance` 工作流或上述统一真实命令；没有环境时保存 `NOT_RUN`，不把普通 CI 成功当成真实数据通过。

```powershell
python scripts/doris/test_project_combination_reference.py
python scripts/doris/test_project_rank_reference.py
python scripts/doris/check_project_combinations.py --java java --output target/new-combinations.json
python scripts/doris/check_project_rank_combinations.py --java java --output target/new-rank-combinations.json
```

每个输出路径须新建。两种边界入口增加 `--native-fixture --distribution 环境名` 时使用隔离原生 Doris 夹具，清理失败保留为失败。对已保存真实执行结果使用 `--execution-dir` 及本轮证书独立核对；统一入口组织这些步骤和结果汇总，便携／夹具／真实数据的证据类型分别注明。

临时库测试：`scripts/doris/check_project_execution.py --output-dir 新目录`。

官方原始行独立对比：`scripts/doris/check_official_project_execution.py --certificate 证据JSON --output-dir 新目录`。只创建并清理临时只读账号，不修改官方行。

扩展日期、市场、固定种子组合、完整排序和缺失样本对比：

```powershell
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/test_project_matrix_reference.py
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_expanded_project_matrix.py `
  --certificate build/project-sources/new-run/project-validation.json `
  --output-dir reports/project-expanded/新批次/matrix --restart
```

`--restart` 在重复执行之后重启项目专属诊断容器两次，并重新建立 HTTP 服务；不清空宿主机页缓存。它验证进程重启后的数据及结果稳定性，不代表正式冷缓存评测。脚本记录全部尝试，失败不自动重试计为通过；诊断单条使用 `--only-case`，不能据此宣称完整矩阵通过。

整组诊断的环境为既有 10GiB/6CPU 容器、FE 2GiB 堆及 BE 60%（6GiB）总配额；每条查询仍限制 2GiB。原 BE 40% 配额曾因进程总占用而取消低于单查询预算的任务。CI 镜像重启会从 `be.conf.orig` 重新生成配置，因此修正该模板并保留备份；回滚步骤在 `reports/project-expanded/2026-10-05/memory-budget-final/result.json`。重新创建容器时，应设置 `BE_CONFIG_EXTRA` 或重新配置模板，不能假定容器文件修改属于镜像。

有限窗口及混合次数验证入口：

```powershell
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_window_boundaries.py `
  --output target/新批次窗口边界.json
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_window_performance.py `
  --certificate reports/project-performance/2026-10-05/source-validation-final/project-validation.json `
  --output-dir reports/project-performance/新批次/mixed --rounds 3 --explain
```

`--timing-subset` 仅重复 position3 和 RSI5，不能代表全矩阵。`--baseline` 保存所有失败并继续测量，报告仍为 FAIL；最终复验默认在失败后停止。对比使用原始字段独立参考，并核对未截断的完整结果、缺失计数和全部样本标记。所有输出必须使用新路径。统一集成脚本明确沿用调用它的 Python 环境，需安装已有项目虚拟环境中的 DuckDB。

窗口解释独立核对入口：

```powershell
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_availability.py `
  --output target/新批次解释边界.json
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_availability.py `
  --execution-dir reports/project-explanations/新批次/native-matrix `
  --output reports/project-explanations/新批次/native-explanations.json
```

第二条检查已保存的真实 Doris 执行工件，并从原始表独立核对样本原因、相关日期、观察数及缺失标记；不会只比较 Java 自己生成的预期。`check_project_window_performance.py --matrix 自定义矩阵JSON` 可运行包含成交量/资金 position、资金次数及 close_together 的扩展矩阵，默认性能矩阵仍为原 24 组。

逐字段规则见 [19 项指标来源与缺值规则](project-field-rules.md)。逐字段便携测试、隔离 Doris 边界和项目入口真实数据复验使用以下命令；每次选择新目录，来源证书先通过 `validate_project_sources.py` 生成。

```powershell
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/test_project_field_reference.py
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_fields.py `
  --output reports/project-fields/新批次/portable.json `
  --matrix-output reports/project-fields/新批次/field-matrix.json
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_fields.py `
  --native-fixture --output reports/project-fields/新批次/native-fixture.json
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_window_performance.py `
  --field-oracle --matrix reports/project-fields/新批次/field-matrix.json `
  --certificate reports/project-fields/新批次/source-validation/project-validation.json `
  --output-dir reports/project-fields/新批次/native-matrix --rounds 1
& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_fields.py `
  --execution-dir reports/project-fields/新批次/native-matrix --values-native `
  --certificate reports/project-fields/新批次/source-validation/project-validation.json `
  --output reports/project-fields/新批次/official-field-verification.json
```

94 组场景包含全部 19 项指标的三个日期点查询、全部指标的 3 条观察 position、6 项派生指标的计数及另外两个日期的点查询。隔离边界额外覆盖零分母、每个原始计算字段 NULL、非平凡复权乘加数、合法负资金、哨兵、未来行和观察不足。真实数据数值对比采用相对容差 `1e-10 * max(1, abs(expected))`；结果证券列表、顺序、NULL、缺值标记、原因和日期要求完全一致。五个日期的数值检查不表示全历史逐行验算。

此前证据见 [分能力验收与自测报告](../reports/project-scoped/2026-10-05/分能力验收与自测报告.md)、[扩展官方数据验证与自测报告](../reports/project-expanded/2026-10-05/扩展官方数据验证与自测报告.md)、[窗口性能优化与自测报告](../reports/project-performance/2026-10-05/窗口性能优化与自测报告.md)、[逐字段验证与自测报告](../reports/project-fields/2026-10-05/逐字段验证与自测报告.md)。这些为当时版本的历史结果；当前新增组合及实时环境的最终结论需读取新批次 `project-summary.json`，正式门禁保持不变。
