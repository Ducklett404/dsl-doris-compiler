"""Publish expanded project evidence only after final artifact identities and gates agree."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]


def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def p95(values): return sorted(values)[math.ceil(.95*len(values))-1]


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('folder', type=Path)
    parser.add_argument('--matrix-directory', default='matrix-stable')
    args = parser.parse_args(); folder = args.folder.resolve()
    if (folder/'expanded-summary.json').exists(): raise ValueError('Preserve the published report')
    paths = dict(matrix=args.matrix_directory+'/result.json', cases=args.matrix_directory+'/matrix.json',
        expected=args.matrix_directory+'/independent-expected.json', sources='source-validation-final/source-validation-report.json',
        certificate='source-validation-final/project-validation.json', junit='selftest-final/junit-results.json',
        integration='selftest-final/integration-result.json', numeric='selftest-final/numeric-precision-boundaries.json',
        automation='selftest-final/automation/latest.json', scope='selftest-final/scope/phase1-scope-validation.json',
        compiler='selftest-final/compiler-performance/latest.json', reference='reference-selftest.json', rsi='rsi-tail-boundaries-final.json',
        synthetic='synthetic-release/result.json', strict='strict-gates/controlled-execution-gate.json', formal='formal-gate/result.json', memory='memory-budget-final/result.json')
    evidence = {key: read(folder/path) for key, path in paths.items()}
    jar = digest(ROOT/'target/dsl-doris-compiler.jar'); matrix = evidence['matrix']; cases = evidence['cases']
    assert matrix['purpose'] == 'PROJECT_EXPANDED_OFFICIAL_DATA_MATRIX' and not matrix['officialAcceptanceEligible']
    assert matrix['status'] == 'PASS' and matrix['passed'] == matrix['total'] == 188
    assert matrix['matrixCases'] == len(cases) == 67 and len(matrix['executions']) == 91 and len(matrix['restart']) == 2
    assert matrix['restartRequested'] and matrix['cleanup'] == 'DONE' and matrix['jarSha256'] == jar
    assert matrix['environment'] == dict(containerMemoryBytes=10737418240, beMemoryShare='60%')
    assert all(r['environmentAfter'] == matrix['environment'] for r in matrix['restart'])
    assert evidence['memory']['status'] == 'PASS' and evidence['memory']['runtimeBeShare'] == '60%' and evidence['memory']['sourceStateUnchanged']
    assert evidence['memory']['queryMaxExecutionMemoryBytes'] == 2147483648
    assert matrix['oracleSha256'] == digest(ROOT/'scripts/doris/project_matrix_reference.py')
    assert matrix['runnerSha256'] == digest(ROOT/'scripts/doris/check_expanded_project_matrix.py')
    assert matrix['policySha256'] == digest(ROOT/'config/acceptance/project-data-policy-v1.json')
    assert len({c['date'] for c in cases}) == 7 and matrix['seed'] == 20261005
    assert sum(e['phase'] == 'matrix' for e in matrix['executions']) == 67
    assert sum(e['phase'] == 'repeat' for e in matrix['executions']) == 16
    assert sum(e['phase'] == 'restart' for e in matrix['executions']) == 8
    assert all(all(e['checks'].values()) for e in matrix['executions'])
    for key, count in [('integration', 18), ('numeric', 42), ('synthetic', 38), ('strict', 9)]:
        assert evidence[key]['status'] == 'PASS' and evidence[key]['passed'] == evidence[key]['total'] == count, key
    for key in ['numeric', 'synthetic', 'sources', 'rsi']: assert evidence[key]['jarSha256'] == jar, key
    assert evidence['rsi']['status'] == 'PASS' and evidence['rsi']['passed'] == evidence['rsi']['total'] == 16
    assert evidence['integration']['compilerJarSha256'] == jar
    assert evidence['integration']['fixtureCleanup'] == evidence['numeric']['fixtureCleanup'] == evidence['synthetic']['cleanup'] == 'DONE'
    for key, count in [('main', 289), ('executor', 3)]:
        data = evidence['junit'][key]
        assert data['tests'] == count and data['failures'] == data['errors'] == data['skipped'] == 0
    assert evidence['reference']['status'] == 'PASS' and evidence['reference']['tests'] == 11
    assert evidence['scope']['status'] == 'PASS' and evidence['compiler']['passed']
    assert all(c['status'] in ('PASS', 'NOT_RUN') for c in evidence['automation']['checks'].values())
    assert evidence['formal']['status'] == 'BLOCKED' and evidence['formal']['overall']['accuracy'] is None and not evidence['formal']['cases']
    assert evidence['formal']['artifactHashes']['compilerJarSha256'] == jar and evidence['formal']['physicalSnapshotMatchesManifest']
    sources = evidence['sources']; cert = evidence['certificate']
    assert sources['status'] == 'PROJECT_READY_WITH_LIMITATIONS' and sources['officialRegistryUnchanged']
    assert len(sources['sourceIntegrity']) == 3 and all(i['status'] == 'PASS' for i in sources['sourceIntegrity'])
    assert sum(sources['rawSourceRows'].values()) == 19826855
    assert cert['extensionWithoutBasic'] == 249480 and cert['closeOutsideRange'] == 3487
    assert matrix['certificateSha256'] == sources['certificateSha256'] == digest(folder/paths['certificate'])
    assert matrix['manifestSha256'] == sources['manifestSha256'] == cert['manifestSha256']
    timings = defaultdict(list)
    for execution in matrix['executions']:
        if execution['phase'] == 'repeat': timings[execution['case']].append(execution)
    timing_summary = {name: dict(samples=len(rows), **{field: dict(p50=statistics.median(r[field] for r in rows), p95=p95([r[field] for r in rows]), maximum=max(r[field] for r in rows))
                        for field in ['totalMillis', 'validationMillis', 'dorisExecutionMillis']}) for name, rows in timings.items()}
    inputs = evidence['expected']
    summary = dict(status='PROJECT_EXPANDED_PASS_FORMAL_BLOCKED', officialAcceptanceEligible=False,
        completedAtUtc=datetime.now(timezone.utc).isoformat(), jarSha256=jar,
        certificateSha256=matrix['certificateSha256'], manifestSha256=matrix['manifestSha256'], registryFingerprint=cert['registryFingerprint'],
        matrixCases=67, actualExecutions=91, checks=188, dates=7, markets=['沪', '深', '京'],
        sourceRows=19826855, javaTests=292, referenceTests=11, projectSyntheticChecks=38, rsiTailBoundaryChecks=16,
        numericChecks=42, strictIntegrationChecks=18, strictNegativeChecks=9, diagnosticEnvironment=matrix['environment'],
        repeatTimings=timing_summary, compilerUncachedP95Millis=evidence['compiler']['uncachedPipeline']['stages']['total']['p95'],
        evidence={key: dict(path=value, sha256=digest(folder/value)) for key, value in paths.items()},
        codeHashes={str(p.relative_to(ROOT)): digest(p) for p in [ROOT/'scripts/doris/project_matrix_reference.py',
            ROOT/'scripts/doris/check_expanded_project_matrix.py', ROOT/'scripts/doris/test_project_matrix_reference.py',
            ROOT/'scripts/doris/ProjectExecutionProbe.java', ROOT/'scripts/test-all.ps1', Path(__file__).resolve(),
            ROOT/'scripts/doris/check_project_rsi_tail.py', ROOT/'scripts/doris/ProjectWindowCompile.java', ROOT/'scripts/doris/configure_project_be_memory.py',
            ROOT/'src/main/java/com/acme/dorisdsl/stockslot/StockSlotAdvancedSqlCompiler.java', ROOT/'src/test/java/com/acme/dorisdsl/ProjectDataValidationTest.java',
            ROOT/'src/main/java/com/acme/dorisdsl/stockslot/DorisQueryExecutor.java', ROOT/'src/test/java/com/acme/dorisdsl/stockslot/DorisExplainEstimateTest.java']})
    lines = ['# 扩展官方数据验证与自测报告', '', '日期：2026-10-05。', '',
        '**67 组官方数据查询、91 次实际执行、188 项检查全部通过。** 覆盖 7 个日期、沪深京三市场、市场并集/排除和 12 个固定种子组合；完整证券列表、排序、未截断状态、条件之前的输入缺失数量及最多 20 条缺失样本标记均与原始行独立计算一致。', '',
        '本轮修复了旧日期资金查询被 Doris 空结果计划误拒绝的问题，解决纯 RSI 查询在 2GiB 预算内耗尽内存的问题，并调整诊断实例的 BE 总内存配额以消除整组运行时的资源压力。运行入口仍使用项目冻结的字段及 NULL 规则，完整快照正式验收继续 BLOCKED。', '',
        '## 验证与自测', '', '| 项目 | 结果 |', '|---|---|',
        '| 官方扩展矩阵 | 67/67，CLI 完整结果与原始 DuckDB/Python 对比 |',
        '| 重复与进程重启 | 同一 HTTP 服务 16 次重复执行；容器重启两次后新 HTTP 服务共 8 次执行 |',
        '| 扩展检查 | 188/188；所有执行维持 2GiB、单语句 10 秒、扫描估算 1 亿行、返回 1 万行限制 |',
        '| Java | 主模块 289、执行器 3，0 失败、0 跳过 |',
        '| 独立参考手工边界 | 11/11，三值逻辑、观察行、含 NULL 次数、重复标签/样本、稳定排序等 |',
        '| 项目入口隔离自测 | 38/38 |',
        '| 原严格执行集成 / 负向门禁 | 18/18、9/9 |',
        '| Decimal/数值边界 | 42/42 |',
        '| RSI 明细尾部边界 | 16/16，生成 SQL 的项目路径与完整参考均在 DuckDB 执行，与手工预期一致 |',
        '| 原始文件与行数 | 3 份 CSV 哈希一致，19,826,855 行保持原样 |',
        f'| 编译器 P95 | {summary["compilerUncachedP95Millis"]:.4f} ms，5,000 次禁用结果缓存的样本 |',
        '| 正式验收 | BLOCKED，正式用例未执行、准确率 null |', '',
        '完整 Java/Python 回归也通过。新增独立参考边界测试已加入 `scripts/test-all.ps1` 并在最终完整自测中执行；自动化记录中的正式黄金集/函数/19 年性能矩阵仍为 NOT_RUN，没有计作通过。', '',
        '## 覆盖范围', '',
        '- 日期：2006-01-04、2010-05-13、2018-08-20、2020-02-03、2025-01-02、2026-04-14、2026-04-12（无行情日）。',
        '- 当前指标：价格、成交量、资金、加法、AND/OR 的 NULL 组合；资金来源不存在及 -999999 保留为不可用。',
        '- 窗口：MA3/MA20、RSI5、3/20 条观察行 position、两个不同 position 窗口、有限高低点、上穿/下穿/贴近，以及首日历史不足。',
        '- 次数：CONS>=3、CONS=3、EXIST>=3、EXIST=3，同时检查当前字段、观察行不足与整个条件窗口的不明输入。',
        '- 横截面：三种排名、稳定并列排序、资金先筛选后排名及 LIMIT、指定/缺失/不在市场中的目标证券。',
        '- 固定随机种子 `20261005`；输入调用重复标签按多重集合和样本缺失标记对比，避免旧脚本把同名输入覆盖而漏检。', '',
        '预期计算直接读取锁定快照的原始表，价格使用原始整数缩放；没有使用 Doris 语义视图或编译 SQL 反推预期。全部用例与预期列表分别保存于矩阵和独立参考 JSON。', '',
        '## 发现并修复的问题', '',
        '2006 年的资金条件在当时没有衍生来源。Doris 将最终条件优化为纯 VEMPTYSET，不输出 cardinality；执行器把该计划误认为扫描量未知而拒绝。现在只对明确编号、仅包含 EMPTYSET/VEMPTYSET 节点的计划返回零估算；未知计划、空节点与扫描/其他算子同时出现且没有估算时仍拒绝。来源验证与条件之前的可用性查询继续执行。', '',
        f'修复后的 2006-01-04 资金条件返回 0 条证券；实际基础证券 {inputs["funds-2006-01-04"]["observed"]} 个，资金字段和当日衍生来源均缺失，状态为 PARTIAL_INPUTS。它与无行情日的 NO_OBSERVATIONS 明确区分。', '',
        '第二轮矩阵在 RSI5 处触发真实 MEM_LIMIT_EXCEEDED；根因是窗口及可用性统计保留完整历史。项目路径对纯 RSI 调用按证券保留最大 N+1 条实际观察行，再计算 LAG 和 N 个差值。NULL 行不删除、停牌不按日历裁剪、缺少评价日不替补。两个 RSI 周期取最大需求；带次数及混合窗口仍走完整历史，FULL_SCAN_REFERENCE 不裁剪。稀疏、NULL、短历史、平坦/无损失、未来行、双窗口和计数回退都有手工预期的 SQL 执行检查。没有增加查询内存。', '',
        '随后 `matrix-final` 在 position 处又出现通用 1105 拒绝。失败时间段的容器日志确认：查询峰值约 785MiB、当前约 713MiB，未达到 2GiB，但 BE 进程约 4.07GiB 超过 4GiB 总配额，被全局内存回收取消。后续探针也复现了同类取消。把该实例既有 10GiB 容器中的 BE 配额从 40% 调为 60%（6GiB），FE 堆继续 2GiB，查询预算仍 2GiB；没有扩大容器或单查询限制。', '',
        '首次直接修改 be.conf 后，重启脚本从 be.conf.orig 恢复 40%，因此验证失败。路线改为备份并修改该模板，运行配置和随后两次重启都核对为 60%。配置证据及回滚命令见 memory-budget-final/result.json；重新创建容器时需要重新配置 BE_CONFIG_EXTRA 或模板，当前证据覆盖容器重启。', '',
        '失败证据保存在 `matrix-attempt-001`、`empty-plan-diagnostic`、`matrix-release`、`matrix-final`、`memory-budget-fix`；RSI 单条修复检查保存于 `rsi-tail-recheck`。没有自动重试将失败计为通过，最终整组采用 `matrix-stable` 新目录。上轮那次拒绝的完整原因不能仅凭本轮日志追溯确定。', '',
        '## 稳定性与开销', '',
        '重复样本只代表这台机器上的诊断。两次重启停止并重新启动项目专属 Doris 容器，然后检查原始表/登记表并新建 HTTP 服务；未清空宿主机页缓存，来源准备检查也会读取数据，不能称为正式冷缓存测试。', '',
        '| 重复查询 | 样本 | 总耗时 P95 | 验证诊断 P95 | 主 SQL P95 |', '|---|---:|---:|---:|---:|']
    for name, result in timing_summary.items():
        lines.append(f'| {name} | {result["samples"]} | {result["totalMillis"]["p95"]:.1f} ms | {result["validationMillis"]["p95"]:.1f} ms | {result["dorisExecutionMillis"]["p95"]:.1f} ms |')
    lines += ['', '各列是分别计算的分位数，不能相加。validationMillis 与 EXPLAIN 耗时重叠；单语句 10 秒限制不等于整个请求最多 10 秒。全部原始计时保存于 result.json。8 次重复样本不足以替代正式性能矩阵。', '',
        '## 下一步', '',
        '按查询类别测量并优化可用性统计和缺失样本的重复历史扫描，优先处理有限窗口及组合查询；RSI 与其它窗口或次数的完整历史组合尚未在全量官方数据上验证本机资源预算，应作为下一阶段重点。优化前后保持证券列表、顺序、NULL、诊断数量和来源身份一致。补充输入窗口标识及具体缺失日期，让同一指标的多个窗口更容易解释。再运行这套扩展矩阵、资源限制与重启回归。', '',
        '行业与无来源财务功能仍拒绝；全快照 249,480 条未关联衍生记录及 3,487 条价格范围警告保留。项目验证不替代官方字段口径确认、外部盲测或正式快照认可。', '',
        '## 复跑与证据', '',
        '在仓库中运行，输出目录应更换为新的批次：', '', '```powershell',
        '& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_expanded_project_matrix.py `',
        '  --certificate reports/project-expanded/2026-10-05/source-validation-final/project-validation.json `',
        '  --output-dir reports/project-expanded/新批次/matrix --restart', '```', '',
        f'- [完整矩阵检查]({paths["matrix"]})、[67 组 DSL]({paths["cases"]})、[原始行预期]({paths["expected"]})。',
        '- [自测归档](selftest-final/junit-results.json)、[来源核验](source-validation-final/source-validation-report.json)、[RSI 尾部边界](rsi-tail-boundaries-final.json)。',
        '- [BE 配置及回滚](memory-budget-final/result.json)、[失败时间段内存日志](memory-diagnostic/docker-memory-cancellations.log)。',
        '- [身份、证据哈希与计时汇总](expanded-summary.json)。临时账号、库及 HTTP 进程均由各脚本关闭清理。', '',
        f'最终 JAR SHA-256：`{jar}`。', '']
    (folder/'expanded-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (folder/'扩展官方数据验证与自测报告.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ['status', 'matrixCases', 'actualExecutions', 'checks', 'javaTests']}, ensure_ascii=False))


if __name__ == '__main__': main()
