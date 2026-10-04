"""Validate final feature, regression and performance evidence before writing the report."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from summarize_performance import verify as verify_performance

ROOT=Path(__file__).resolve().parents[2]


def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args()
    folder=args.folder.resolve();tests=folder/'final-selftest';build=read(folder/'final-build/build-report.json')
    catalog=read(folder/'final-build/catalog.json'); jar=digest(ROOT/'target/dsl-doris-compiler.jar')
    performance=verify_performance(folder/'hot-30')
    evidence_test=read(folder/'hot-30/evidence-selftest.json')
    assert evidence_test['status']=='PASS' and len(evidence_test['checks'])==8 and all(r['status']=='PASS' for r in evidence_test['checks'])
    assert build['status']=='PASS' and build['officialRegistryUnchanged'] and build['acceptanceEligible'] is False
    assert build['jarSha256']==jar==performance['hashes']['compilerJar']
    assert digest(folder/'final-build/catalog.json')==build['publishedCatalogSha256']==performance['hashes']['historicalFeatureCatalog']
    assert catalog==performance['historicalFeatures']
    assert len(build['dates'])==len(catalog['completeDates'])==2
    assert all(r['rows']==r['expectedCurrentRows']==catalog['completeDates'][r['date']] and r['windowValueDifferences']==0 for r in build['dates'])
    junit={}
    for name in ('junit-main','junit-executor'):
        xmls=list((tests/name).glob('TEST-*.xml'));assert xmls
        junit[name]={key:sum(int(ET.parse(p).getroot().get(key,'0')) for p in xmls) for key in ('tests','failures','errors','skipped')}
        assert junit[name]['tests']>0 and all(junit[name][k]==0 for k in ('failures','errors','skipped'))
    automation=read(tests/'automation.json')
    assert not any(r['status']=='FAIL' for r in automation['checks'].values())
    bounds={}
    for name in ('portable','doris'):
        data=read(tests/(name+'-historical-boundaries.json'))
        assert data['passed']==data['total']==14 and data['jarSha256']==jar
        assert all(len(r['paths'])==6 and all(p['status']=='PASS' for p in r['paths'].values()) for r in data['results'])
        if name=='doris':assert data['fixtureCleanup']=='DONE' and data['officialRegistryUnchanged']
        bounds[name]={'cases':data['total'],'executions':sum(len(r['paths']) for r in data['results'])}
    local=read(tests/'本地真实数据结果对比.json');native=read(tests/'Doris真实数据诊断结果.json')
    assert local['passed']==local['total']==native['passed']==native['total']==34
    assert local['jarSha256']==native['jarSha256']==jar
    assert native['registeredSnapshots']==0 and native['extensionWithoutBasic']==249480
    assert native['functionSmoke']['passed']==native['functionSmoke']['total']==15 and all(v=='PASS' for v in native['explain'].values())
    integration=read(tests/'integration-result.json'); gate=read(tests/'controlled-execution-gate.json')
    assert integration['status']=='PASS' and integration['passed']==integration['total']==17 and integration['fixtureCleanup']=='DONE'
    assert integration['compilerJarSha256']==jar and gate['status']=='PASS' and gate['passed']==gate['total']==9
    formal=read(tests/'formal-gate/result.json')
    assert formal['status']=='BLOCKED' and formal['snapshotVerified'] is False and formal['cases']==[] and formal['overall']['accuracy'] is None
    compiler=read(tests/'compiler-performance.json');assert compiler['passed']
    manifest_path=ROOT/'data/doris/snapshots'/catalog['snapshotId']/'manifest.json';manifest=read(manifest_path)
    assert digest(manifest_path)==catalog['manifestSha256']==native['manifestSha256']==local['manifestSha256']
    integrity=[]
    for name,item in manifest['files'].items():
        path=ROOT.parent/item['relativePath'];actual=digest(path)
        assert actual==item['sha256'] and path.stat().st_size==item['bytes']
        integrity.append({'table':name,'sha256':actual,'bytes':path.stat().st_size,'status':'PASS'})
    (folder/'source-integrity.json').write_text(json.dumps(integrity,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    history=[r for r in performance['measurements']['results'] if r.get('historicalFeatureSelected')]
    assert len(history)==5 and performance['measurements']['iterationsPerPath']==30
    ratios=[r['p95Ratio'] for r in history]
    summary={'status':'PASS','purpose':'DIAGNOSTIC_ONLY','acceptanceEligible':False,'formalAcceptanceStatus':'BLOCKED',
        'snapshotId':catalog['snapshotId'],'manifestSha256':catalog['manifestSha256'],'jarSha256':jar,
        'registryFingerprint':catalog['registryFingerprint'],'junit':junit,'boundaries':bounds,'localAndDorisCases':34,
        'nativeSmokeCases':15,'positiveCliHttpChecks':17,'executionGateChecks':9,'sourceHashesVerified':3,
        'completeDates':catalog['completeDates'],'historyP95RatioMin':min(ratios),'historyP95RatioMax':max(ratios),
        'historyDiagnostic10xReached':min(ratios)>=10,'unmatchedExtensionRows':249480,
        'compilerUncachedP95Millis':compiler['uncachedPipeline']['stages']['total']['p95'],
        'timedQueries':sum(len(r['samples'])*2 for r in performance['measurements']['results']),
        'nextStep':'Build multi-date MA20/MA120/MA250 features using strict observed-row windows and verify fallback, incremental maintenance and results.',
        'completedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (folder/'feature-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 历史极值特征与自测报告','',
        '已实现显式日期/快照绑定的历史极值特征，在独立 Doris 数据库构建并完成自测。当前仅开放 SQL 编译和诊断入口；正式验收仍为 **BLOCKED**。','',
        '## 本轮实现','',
        '- 保存当日收盘/最高/最低价，以及各字段截至当日的历史 MIN/MAX，共 9 个数值字段。两个评估日各 5,614 条，共 11,228 条；当前行缺失的证券不生成特征。',
        '- 必须匹配快照 ID、源清单 SHA-256、字段配置指纹和已完整构建的日期，才能选择特征。NULL、并列极值、证券/市场、行业过滤和输出排序沿用原语义。',
        '- 未给清单哈希、快照不符、配置变化、日期未构建或指标缺失时回退到聚合。计数、有限窗口和混合调用沿用窗口；参考模式始终读取原表。缓存键包含快照及清单身份，避免跨上下文复用。',
        '- 构建在新命名空间中进行；各日期完整行数和全部 9 字段与有序窗口比对，差异 0。完成统计收集后才发布目录，部分构建失败会清理未发布表。','',
        '## 最终自测','',
        f"- Java 主模块 {junit['junit-main']['tests']} 项、执行器 {junit['junit-executor']['tests']} 项全部通过，零失败、零跳过。完整 JDBC/CLI/HTTP 正向检查 17/17，未验证快照执行门禁 9/9。",
        '- 14 个手工标注边界在 SQLite、Doris 各跑 6 种路径，共 168 次结果/排序检查，全通过。覆盖全 NULL、当日 NULL、并列极值、缺当日行、未来行、市场/行业、计数和混合回退；新增 Java 检查还覆盖未构建日期和过期配置。',
        '- 真实 CSV 独立参考和真实 Doris 各 34/34；原生功能 15/15，执行计划 3/3。回归不以两条路径一致替代独立参考。',
        f"- 编译全流程禁用结果缓存，5,000 次样本 P95 {summary['compilerUncachedP95Millis']:.4f} ms，低于 50 ms 门槛。",
        '- 原始三份 CSV 重新计算 SHA-256，3/3 与冻结清单一致。正式源登记表始终为空，测试账号和临时边界/执行数据库已清理。','',
        '性能证据校验器另做 8 项自测：有效证据被接受，错误分位数、缺失样本、结果不一致、账号未清理、错误特征清单、日期未发布和错误分区均被拒绝。','',
        '## 真实数据热缓存性能','',
        '每条路径重复 30 次并交替先执行，共 360 次计时查询，逐次核对完整结果和排序。计时为 JDBC 准备、执行和完整读取，排除编译、EXPLAIN、进程启动和特征构建。SQL 结果缓存关闭；本机单节点、单连接、OS/BE 热缓存。','',
        '| 查询 | 返回行 | 窗口参考 P95 ms | 特征/控制 P95 ms | 比值 |',
        '|---|---:|---:|---:|---:|']
    for r in performance['measurements']['results']:
        lines.append(f"| {r['id']} | {r['rows']} | {r['baseline']['p95Millis']:.3f} | {r['optimized']['p95Millis']:.3f} | {r['p95Ratio']:.3f}x |")
    lines += ['',f"五个历史用例 P95 比值 {min(ratios):.1f}–{max(ratios):.1f}x；本诊断的历史 10x 目标{'达到' if min(ratios)>=10 else '未达到'}。MA60 为原有特征控制项，不计作本轮历史优化收益。历史特征计划只读 1/2 日期分区，没有基础历史扫描或分析窗口。",
        '', '构建耗时与查询成本分开记录：'+ '；'.join(f"{r['date']} 约 {r['buildSecondsIncludingWslTransport']:.3f} 秒" for r in build['dates'])+'，包含 WSL 传输、排除后续全量校验和统计收集。收益来自预先计算并复用特征，不能据此推断端到端首次构建、冷缓存或并发性能。',
        '', '## 路线修正与下一步','',
        '首次构建的两日期全量值已通过，但统计收集使用了错误的 ANALYZE 语法，导致发布前失败。未发布数据库已清理，修正为 ANALYZE TABLE 后重新构建，最终发布和全量校验均通过；失败及重试记录保留。',
        '', '下一步扩展 MA20、MA120、MA250 的多日期特征，先按原有严格 COUNT 窗口生成，保留 NULL 和实际观察行，再验证停牌/稀疏证券及增量更新与全量重算一致。完成后再次自测并独立测量 30 次性能。',
        '', '官方规则问题继续保留：249,480 条衍生行情缺少同键基础行情，价格/关联/缺值口径尚待官方确认。收到说明或补丁后创建新快照并重跑源门禁，再进行正式冷/热缓存、并发和外部盲测。当前特征不改变这一验收状态。',
        '', '## 复现证据','',
        '- [特征构建与全部字段验证](final-build/build-report.json)、[显式特征目录](final-build/catalog.json)、[热缓存性能及逐次样本](hot-30/性能诊断与下一步.md)。',
        '- [统一自测日志](final-selftest/unified-integration.log)、[真实 Doris 结果](final-selftest/Doris真实数据诊断结果.json)、[边界六路径结果](final-selftest/doris-historical-boundaries.json)、[正式入口 BLOCKED](final-selftest/formal-gate/result.json)。',
        '- [机器汇总](feature-summary.json)、[源文件完整性](source-integrity.json)、[工具源码及哈希](tool-sources.json)。操作命令见 [运行说明](../../../docs/runtime-guide.md)。','']
    (folder/'历史极值特征与自测报告.md').write_text('\n'.join(lines),encoding='utf-8')
    sources=[Path(__file__),ROOT/'scripts/doris/build_history_features.py',ROOT/'scripts/doris/HistoryFeatureRegistry.java',
        ROOT/'scripts/doris/DorisPerformanceDiagnostic.java',ROOT/'scripts/doris/diagnose_performance.py',ROOT/'scripts/doris/summarize_performance.py',
        ROOT/'scripts/doris/test_performance_evidence.py',
        ROOT/'scripts/accuracy/check_historical_extrema.py',ROOT/'scripts/accuracy/run_correctness.py',
        ROOT/'src/main/java/com/acme/dorisdsl/stockslot/HistoricalExtremaFeatureCatalog.java',
        ROOT/'src/main/java/com/acme/dorisdsl/stockslot/StockSlotAdvancedSqlCompiler.java',
        ROOT/'src/main/java/com/acme/dorisdsl/stockslot/StockSlotSqlCompiler.java',ROOT/'src/main/java/com/acme/dorisdsl/stockslot/StockSlotRegistry.java',
        ROOT/'src/main/java/com/acme/dorisdsl/cli/Main.java',ROOT/'src/test/java/com/acme/dorisdsl/HistoryFeatureTest.java',
        ROOT/'benchmarks/history-matrix-v1.json',ROOT/'accuracy/fixtures/historical-extrema-v1.json']
    archive=folder/'tool-sources';archive.mkdir(exist_ok=True)
    for path in sources:shutil.copyfile(path,archive/path.name)
    (folder/'tool-sources.json').write_text(json.dumps({str(p.relative_to(ROOT)):digest(p) for p in sources},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: feature, final JAR, all regressions, sample statistics and original CSV hashes verified')


if __name__=='__main__':main()
