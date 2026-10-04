"""Validate route artifacts and render a reproducible project/official status report."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
from run_official_data_route import read,digest,ROOT
from summarize_performance import verify


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args();folder=args.folder.resolve()
    state=read(folder/'route-status.json');assert state['status']=='DIAGNOSTIC_PASS_FORMAL_BLOCKED'
    assert state['acceptanceEligible'] is False and state['officialRegistryUnchanged']
    expected_phases={'full-selftest','rolling-build','history-build','rolling-independent',
        'rolling-native-boundaries','history-native-boundaries','local-real-results','native-real-results',
        'official-execution-gate','formal-correctness-gate','hot-performance','performance-evidence',
        'evidence-selftest','restart-persistence'}
    assert len(state['phases'])==len(expected_phases) and {p['phase'] for p in state['phases']}==expected_phases
    assert all(p['status']==('EXPECTED_BLOCKED' if p['phase']=='formal-correctness-gate' else 'PASS')
        and p['exitCode']==(3 if p['phase']=='formal-correctness-gate' else 0) for p in state['phases'])
    jar=digest(ROOT/'target/dsl-doris-compiler.jar');assert state['jarSha256']==jar
    tests=folder/'final-selftest';performance=verify(folder/'hot-30');assert performance['hashes']['compilerJar']==jar
    assert performance['measurements']['iterationsPerPath']==30 and performance['measurements']['total']==28
    matrix=read(folder/'matrix.json');assert performance['hashes']['matrix']==digest(folder/'matrix.json')
    assert {r['id'] for r in performance['measurements']['results']}=={c['id'] for c in matrix['cases']}
    load=performance['measurements']['concurrentReadDiagnostic'];assert load['requests']==60 and load['status']=='PASS'
    rolling=read(folder/'rolling-build/build-report.json');history=read(folder/'history-build/build-report.json')
    for build in (rolling,history):assert build['status']=='PASS' and build['jarSha256']==jar and build['officialRegistryUnchanged']
    assert len(rolling['dates'])==3 and [r['mode'] for r in rolling['dates']]==['FULL','INCREMENTAL','INCREMENTAL']
    assert all(r['fullWindowDifferences']==0 and r['previousFeaturesUnchanged'] and r['maxTailRowsPerSecurity']<=249
        and len(r['fullHistoryChecks'])==6 and all(c['differences']==0 for c in r['fullHistoryChecks']) for r in rolling['dates'])
    independent=read(folder/'independent-rolling.json');assert independent['status']=='PASS' and independent['jarSha256']==jar
    assert independent['totalNumericValuesChecked']==sum(r['rows']*10 for r in rolling['dates'])
    assert independent['catalogSha256']==rolling['catalogSha256']==digest(folder/'rolling-build/catalog.json')
    assert digest(folder/'history-build/catalog.json')==history['publishedCatalogSha256']
    independent_cases={r['id'] for r in performance['measurements']['results']} & set(independent['queryExpectations'])
    assert len(independent_cases)==14
    for case_id in independent_cases:
        assert read(folder/'hot-30'/case_id/'result-rows.json')==[
            [str(m),code] for m,code in independent['queryExpectations'][case_id]]
    limited_expectations={f'ma{n}':independent['queryExpectations'][f'ma{n}-2026-04-14-沪'][:100]
        for n in (20,60,120,250)}
    for kind in ('high','low'):
        limited_expectations['record-'+kind]=[key for key in independent['queryExpectations'][
            f'record-{kind}-2026-04-14-all'] if key[0]==1][:100]
    for case_id,expected in limited_expectations.items():
        assert read(folder/'hot-30'/case_id/'result-rows.json')==[[str(m),code] for m,code in expected]
    regression={}
    for engine in ('portable','doris'):
        for kind,count,paths in [('historical',14,6),('rolling',16,5)]:
            data=read(tests/(engine+'-'+kind+'-boundaries.json'))
            assert data['jarSha256']==jar and data['total']==data['passed']==count
            assert all(len(r['paths'])==paths and all(v['status']=='PASS' for v in r['paths'].values()) for r in data['results'])
            if engine=='doris':assert data['fixtureCleanup']=='DONE' and data['officialRegistryUnchanged']
            regression[engine+'-'+kind]={'cases':count,'executions':count*paths}
    local=read(tests/'本地真实数据结果对比.json');native=read(tests/'Doris真实数据诊断结果.json')
    assert local['jarSha256']==native['jarSha256']==jar and local['passed']==local['total']==native['passed']==native['total']==34
    assert native['functionSmoke']['passed']==native['functionSmoke']['total']==15 and all(v=='PASS' for v in native['explain'].values())
    assert native['extensionWithoutBasic']==249480 and native['registeredSnapshots']==0
    execution=read(tests/'integration-result.json');gate=read(tests/'controlled-execution-gate.json');formal=read(tests/'formal-gate/result.json')
    assert execution['compilerJarSha256']==jar and execution['passed']==execution['total']==17 and execution['fixtureCleanup']=='DONE'
    assert gate['status']=='PASS' and gate['passed']==gate['total']==9
    assert formal['status']=='BLOCKED' and formal['overall']['accuracy'] is None and formal['cases']==[]
    restart=read(folder/'restart-persistence.json');assert restart['status']=='PASS' and len(restart['checks'])==4 and all(r['status']=='PASS' for r in restart['checks'])
    compiler=read(tests/'compiler-performance.json');assert compiler['passed']
    automation=read(tests/'automation.json')
    not_run=[name for name,check in automation['checks'].items() if check['status']=='NOT_RUN']
    assert set(not_run)=={'doris-golden-result-differential','doris-12-function-smoke','doris-19-year-matrix'}
    assert all(check['status'] in ('PASS','NOT_RUN') for check in automation['checks'].values())
    evidence=read(folder/'hot-30/evidence-selftest.json')
    assert evidence['status']=='PASS' and len(evidence['checks'])==16 and all(c['status']=='PASS' for c in evidence['checks'])
    source=read(folder/'source-integrity.json');assert len(source)==3 and all(r['status']=='PASS' for r in source)
    manifest_path=ROOT/'data/doris/snapshots'/state['snapshotId']/'manifest.json';manifest=read(manifest_path)
    for item in manifest['files'].values():assert digest(ROOT.parent/item['relativePath'])==item['sha256']
    assert digest(manifest_path)==state['manifestSha256']
    summary={'status':'DIAGNOSTIC_PASS_FORMAL_BLOCKED','acceptanceEligible':False,'jarSha256':jar,
        'snapshotId':state['snapshotId'],'manifestSha256':state['manifestSha256'],'sourceRows':sum(r['rows'] for r in manifest['files'].values()),
        'junit':state['junit'],'boundaryChecks':regression,'independentNumericValues':independent['totalNumericValuesChecked'],
        'independentResultSets':len(independent_cases)+len(limited_expectations),
        'localAndDorisCases':34,'nativeSmokeCases':15,'positiveExecutionChecks':17,'gateChecks':9,
        'performanceCases':28,'timedQueries':state['timedQueries'],'concurrentRequests':60,
        'compilerUncachedP95Millis':compiler['uncachedPipeline']['stages']['total']['p95'],
        'formalChecksNotRun':not_run,
        'unmatchedExtensionRows':249480,'closeOutsideHighLowWarningRows':3487,
        'completedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (folder/'route-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 官方数据路线执行与自测报告','',
        '**项目侧计算、优化和可复跑流程已通过本轮自测；官方数据正式验收仍为 BLOCKED。** 当前结果依据项目冻结字段规则，不能替代官方字典、关联定义或外部标准答案。','',
        '## 已完成的路线','',
        '- 原始三份 CSV 全文 SHA-256 与冻结清单一致，现有 Doris 全量加载行数核对为 19,826,855。没有删除未关联衍生行、补造价格或把缺失值回填。',
        '- 完成 MA20/MA60/MA120/MA250 与 250 观察行高低点的显式多日期特征，以及原有历史极值特征。访问必须匹配快照、清单、字段配置指纹和完整构建日期。',
        '- 首日按证券取得最近 250 条实际观察行；后续保留所有证券最后 249 行（包含 NULL）并追加全部新行情。停牌间隔不按日历裁剪。各日期与完整历史分组窗口核验差异为 0，旧日期特征不变。',
        '- 修复 MA60 与原始指标/其他窗口混合时的拒绝问题，改为完整窗口回退。计数、未构建日期、配置不符和不支持的特征保持原始计算。',
        '- 新增一条命令持续完成源码自测、特征构建、独立参考、原生结果、门禁、性能、并发和重启持久性检查；可按最终 JAR 和构建哈希安全恢复已完成阶段。','',
        '## 自测证据','',
        f"- Java 主模块 {state['junit']['junit-main']['tests']} 项、执行器 {state['junit']['junit-executor']['tests']} 项，零失败、零错误、零跳过。",
        '- 历史边界 14×6 路径、滚动窗口边界 16×5 路径，在 SQLite 与 Doris 共 328 次结果/排序验证通过；覆盖不足窗口、NULL、并列值、稀疏行、证券/市场、未来数据、混合调用和快照回退。',
        f"- 从原始 closePx/highPx/lowPx 独立用 Decimal 计算三个日期的 {independent['totalNumericValuesChecked']:,} 个数值，逐证券核对 NULL 和数值容差，全部通过。",
        '- 真实数据原有独立参考与 Doris 各 34/34，函数/计数变体 15/15，EXPLAIN 3/3；正向 JDBC/CLI/HTTP 17/17，未验证快照门禁 9/9。',
        '- 统一脚本的正式黄金差分、正式函数冒烟及正式 19 年矩阵仍记为 NOT_RUN。上述真实数据、函数和性能由独立诊断运行验证；正式结果不能在未验证快照上补造。',
        '- 性能证据校验器接受完整记录，并拒绝 15 类人为损坏的样本、分位数、返回结果、清理状态、历史/滚动特征来源、分区和并发记录。',
        f"- 编译全流程 5,000 次禁用结果缓存，P95 {summary['compilerUncachedP95Millis']:.4f} ms。",
        '- 隔离容器重启后原始表行数、登记表及两个完整特征表的有序全文结果哈希不变。测试账号和临时边界/执行数据库已清理。','',
        '## 多日期与性能','',
        '| 构建日期 | 行数 | 模式 | 完整历史差异 | 旧结果变化 |',
        '|---|---:|---|---:|---|']
    for r in rolling['dates']:lines.append(f"| {r['date']} | {r['rows']} | {r['mode']} | {r['fullWindowDifferences']} | 无 |")
    lines+=['',f"28 组查询每条路径重复 30 次，共 {state['timedQueries']:,} 次计时查询，结果和顺序逐次一致。独立 Decimal 参考另核对 20 组多日期全量及沪市 LIMIT 查询的完整返回证券和顺序。4 个只读连接并发执行 60 次特征查询，结果一致。",
        '', '计时包含 JDBC 准备、执行与完整读取，排除编译、进程启动、EXPLAIN 和预计算构建。SQL 结果缓存关闭，OS/BE 热缓存；重启只证明持久性，未清理主机缓存，不能称为正式冷缓存验收。并发结果只适用于当前机器和本次负载。','',
        '| 查询 | 行数 | 窗口参考 P95 ms | 优化/回退 P95 ms | 比值 | 访问 |',
        '|---|---:|---:|---:|---:|---|']
    for r in performance['measurements']['results']:
        access='滚动特征' if r.get('rollingFeatureSelected') else '历史特征' if r.get('historicalFeatureSelected') else '原始路径'
        ratio='相同 SQL，不计收益' if r['sameSql'] else f"{r['p95Ratio']:.2f}x"
        lines.append(f"| {r['id']} | {r['rows']} | {r['baseline']['p95Millis']:.3f} | {r['optimized']['p95Millis']:.3f} | {ratio} | {access} |")
    lines+=['','## 实施中修正的路线','',
        '一次同时计算完整历史多个均线和区间字段触发本机 Doris 内存上限。未发布表已清理，改为足够的实际观察行构建，并将完整历史参考分成 6 组校验，最终每组差异 0。没有通过提高容错、截断日历天数或跳过参考计算解决。',
        '', '独立校验工具曾把 audit_source_lock 引用到错误 schema，已修正为实际审计表；错误发生在比对前，没有虚构正确结果。重启工具曾对未排序 UNION 行数结果做有序哈希，因返回顺序变化误报；两份哈希均对应相同三表行数，已加显式排序并重启复验。失败构建、流程日志及重启失败记录保留，成功阶段经工件核验后复用。','',
        '## 尚不能宣称正式跑通的原因','',
        '1. 249,480 条衍生记录没有同键基础行情，当前正式契约要求完整关联。没有官方补丁或允许独立记录的条件，无法合理改写关联或登记 VALIDATED。',
        '2. 3,487 条收盘价超出高低价范围仍为警告；价格单位、日期口径及 -999999 字段含义尚待官方确认。行业字段全空、分类及复权缺少区分度，不能据空结果声称业务正确。',
        '3. 官方保管的标准答案/外部盲测及正式冷缓存、集群验收仍缺前置条件。本轮项目自测和性能诊断不能替代这些要求。','',
        '下一步必须取得数据方关于关联键、独立衍生行、缺文件和字段口径的说明或补丁。依据说明选择补齐、正确映射或条件化例外，创建新快照/契约，再重跑数据门禁及完整流程。当前所有原始记录保留，正式 CLI/HTTP 未验证快照仍拒绝执行。','',
        '## 复跑入口','',
        '```powershell',
        '.tools/data-audit-venv/Scripts/python.exe scripts/doris/run_official_data_route.py `',
        '  --report-dir reports/official-route/new-run',
        '# 若途中失败，修复原因后在同一目录恢复：',
        '.tools/data-audit-venv/Scripts/python.exe scripts/doris/run_official_data_route.py `',
        '  --resume --report-dir reports/official-route/new-run',
        '.tools/data-audit-venv/Scripts/python.exe scripts/doris/summarize_official_route.py `',
        '  reports/official-route/new-run','```','',
        '此入口使用已准备的项目 WSL/Doris 隔离实例及当前冻结源。DIAGNOSTIC_PASS_FORMAL_BLOCKED 表示计算诊断通过、正式源门禁未解除。日志不会保存临时密码；目录必须新建以保留证据。','',
        '证据：[机器汇总](route-summary.json)、[阶段状态](route-status.json)、[独立数值](independent-rolling.json)、[构建及增量](rolling-build/build-report.json)、[逐次性能及计划](hot-30/性能诊断与下一步.md)、[正式门禁](final-selftest/formal-gate/result.json)、[重启验证](restart-persistence.json)、[工具源码哈希](tool-sources.json)。','']
    (folder/'官方数据路线执行与自测报告.md').write_text('\n'.join(lines),encoding='utf-8')
    sources=[ROOT/'scripts/doris'/name for name in ['run_official_data_route.py','summarize_official_route.py','build_rolling_features.py',
        'check_real_rolling_features.py','build_history_features.py','check_route_restart.py','DorisPerformanceDiagnostic.java',
        'diagnose_performance.py','summarize_performance.py','test_performance_evidence.py']]
    sources +=[ROOT/'scripts/accuracy/check_rolling_averages.py',ROOT/'scripts/accuracy/check_historical_extrema.py',
        ROOT/'src/main/java/com/acme/dorisdsl/stockslot/RollingAverageFeatureCatalog.java',
        ROOT/'src/main/java/com/acme/dorisdsl/stockslot/StockSlotAdvancedSqlCompiler.java',
        ROOT/'src/main/java/com/acme/dorisdsl/stockslot/StockSlotSqlCompiler.java',ROOT/'src/test/java/com/acme/dorisdsl/RollingFeatureTest.java']
    archive=folder/'tool-sources';archive.mkdir(exist_ok=True)
    for p in sources:shutil.copyfile(p,archive/p.name)
    (folder/'tool-sources.json').write_text(json.dumps({str(p.relative_to(ROOT)):digest(p) for p in sources},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: complete route evidence, current artifact, independent values and original source hashes verified')


if __name__=='__main__':main()
