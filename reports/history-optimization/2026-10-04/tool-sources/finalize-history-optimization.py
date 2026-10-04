import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'reports/history-optimization/2026-10-04'
final=folder/'final-selftest'
sys.path.insert(0,str(ROOT/'scripts/doris'))
from summarize_performance import verify

performance=verify(folder/'hot-30')
jar_hash=hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest()
assert performance['hashes']['compilerJar']==jar_hash
reports={name:json.loads((final/path).read_text(encoding='utf-8')) for name,path in {
    'integration':'integration-result.json','portableBoundaries':'portable-historical-boundaries.json',
    'dorisBoundaries':'doris-historical-boundaries.json','localResults':'本地真实数据结果对比.json',
    'dorisResults':'Doris真实数据诊断结果.json','negativeGate':'controlled-execution-gate.json',
    'formalGate':'formal-gate/result.json'}.items()}
for name in ('integration','portableBoundaries','dorisBoundaries','localResults','dorisResults'):
    report=reports[name]
    assert report.get('jarSha256',report.get('compilerJarSha256'))==jar_hash,name
    assert report['passed']==report['total'],name
assert reports['dorisResults']['functionSmoke']['passed']==reports['dorisResults']['functionSmoke']['total']==15
assert reports['negativeGate']['passed']==reports['negativeGate']['total']==9
assert reports['formalGate']['status']=='BLOCKED' and reports['formalGate']['snapshotVerified'] is False
assert reports['dorisBoundaries']['officialRegistryUnchanged'] and reports['dorisBoundaries']['fixtureCleanup']=='DONE'
log=(final/'unified-integration.log').read_text(encoding='utf-8',errors='replace')
totals=[tuple(map(int,m)) for m in re.findall(r'^\[INFO\] Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)\s*$',log,re.M)]
assert totals==[(257,0,0,0),(3,0,0,0)],totals
manifest_path=ROOT/'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'));integrity=[]
for name,item in manifest['files'].items():
    source=(ROOT.parent/item['relativePath']).resolve()
    assert source.is_relative_to(ROOT.parent.resolve())
    with source.open('rb') as file:sha=hashlib.file_digest(file,'sha256').hexdigest()
    assert sha==item['sha256'] and source.stat().st_size==item['bytes'],name
    integrity.append({'table':name,'sha256':sha,'bytes':source.stat().st_size,'matchesManifest':True})
(folder/'source-integrity.json').write_text(json.dumps({'status':'PASS','files':integrity},indent=2)+'\n',encoding='utf-8')
for name in ('json','md'):shutil.copy2(ROOT/('reports/compiler-performance/latest.'+name),folder/('compiler-performance.'+name))
compiler_perf=json.loads((folder/'compiler-performance.json').read_text(encoding='utf-8'))
measurements=performance['measurements'];history=[r for r in measurements['results'] if r['category']=='LONG_RANGE']
plan_checks=[]
for case in history:
    plan=(folder/'hot-30'/case['id']/'optimized-explain.txt').read_text(encoding='utf-8')
    scans=plan.count('VOlapScanNode')
    assert scans==1 and 'VANALYTIC' not in plan,case['id']
    plan_checks.append({'id':case['id'],'baseTableScans':scans,'analyticalWindow':False})
summary={'status':'PROJECT_HISTORY_OPTIMIZATION_PASSED_OFFICIAL_ACCEPTANCE_BLOCKED',
    'completedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'compilerJarSha256':jar_hash,
    'manifestSha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    'goldenSha256':hashlib.sha256((ROOT/'accuracy/golden/stock-slot-executable-v1.0.1.json').read_bytes()).hexdigest(),
    'javaTests':{'main':{'tests':257,'failures':0,'errors':0,'skipped':0},'executor':{'tests':3,'failures':0,'errors':0,'skipped':0}},
    'syntheticIntegration':{'passed':17,'total':17},
    'historicalBoundaries':{'portable':{'passed':14,'total':14},'doris':{'passed':14,'total':14}},
    'realDataDifferential':{'local':{'passed':34,'total':34},'doris':{'passed':34,'total':34}},
    'functionSmoke':{'passed':15,'total':15},'negativeGate':{'passed':9,'total':9},
    'performance':{'cases':measurements['total'],'passed':measurements['passed'],'iterationsPerPath':30,
        'timedQueries':sum(len(r['samples'])*2 for r in measurements['results']),
        'historyP95RatioMin':min(r['p95Ratio'] for r in history),'historyP95RatioMax':max(r['p95Ratio'] for r in history),
        'history10xTargetMet':all(r['p95Ratio']>=10 for r in history),'plans':plan_checks},
    'compilerP95Millis':compiler_perf['uncachedPipeline']['stages']['total']['p95'],
    'evidenceSelftest':json.loads((folder/'hot-30/evidence-selftest.json').read_text(encoding='utf-8')),
    'sourceIntegrity':'PASS','officialRegistryRows':0,'formalAcceptance':'BLOCKED','extensionWithoutBasic':249480,
    'nextStep':'Evaluate snapshot/date-bound historical-extrema features; keep raw fallback and validate multiple dates before MA20/120/250 expansion.'}
(folder/'optimization-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
archive=folder/'tool-sources';archive.mkdir(exist_ok=True)
for source in (ROOT/'scripts/doris/DorisPerformanceDiagnostic.java',ROOT/'scripts/doris/diagnose_performance.py',
    ROOT/'scripts/doris/summarize_performance.py',ROOT/'scripts/accuracy/check_historical_extrema.py',
    ROOT/'src/main/java/com/acme/dorisdsl/stockslot/StockSlotAdvancedSqlCompiler.java',
    ROOT/'src/main/java/com/acme/dorisdsl/cli/Main.java',ROOT/'accuracy/fixtures/historical-extrema-v1.json',
    ROOT/'benchmarks/history-matrix-v1.json',ROOT/'target/performance-evidence-selftest.py',Path(__file__)):
    shutil.copy2(source,archive/source.name)
(folder/'tool-sources.json').write_text(json.dumps([{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(archive.iterdir())],indent=2)+'\n',encoding='utf-8')
lines=['# 历史极值优化与自测报告','',
    f"完成时间：{summary['completedAtUtc']}。本轮项目侧自测通过，正式验收仍为 **BLOCKED**。",'',
    '已将不带历史计数或其他窗口的 `record_high/record_low(...,历史,...)` 改为单次条件聚合：按 `(mktcode,tgtcode)` 计算历史 MIN/MAX，并取评估日的字段值；只有确实存在评估日记录的证券进入结果。历史范围仍截止评估日，NULL 保留为未知，支持并列极值，不补造价格或历史记录。', '',
    '连续计数、排名、有限窗口、position 和混合窗口保留逐行参考路径。CLI 新增 `compile-stock-slot-sql --access-path FULL_SCAN_REFERENCE` 用于输出参考 SQL；执行接口仍要求有效快照。', '',
    '## 本轮自测', '',
    '| 检查 | 结果 |','|---|---|','| Java 主模块 | 257/257，零失败、零跳过 |',
    '| 执行器模块 | 3/3 |','| 隔离合成库的 CLI/HTTP/JDBC 检查 | 17/17 |',
    '| 手工极值边界：SQLite / Doris | 14/14 + 14/14，分别验证参考与优化路径 |',
    '| 全量官方数据参考对比：本地 / Doris | 34/34 + 34/34 |',
    '| Doris 函数冒烟 / 原有 EXPLAIN | 15/15 + 3/3 |',
    '| 正式快照负向入口 / CLI/HTTP 权限门禁 | BLOCKED 符合预期 + 9/9 |',
    '| 性能样本与证据校验 | 6/6，360 次计时查询；5 项证据自测通过 |',
    '| 原始 CSV 字节数与 SHA-256 | 3/3，符合冻结清单 |',
    f"| 编译器完整流水线 P95 | {summary['compilerP95Millis']:.4f} ms，阈值 50 ms |",'',
    '边界覆盖全 NULL、当日 NULL、短历史、负值/零、并列极值、跨市场同代码、当日缺行、未来数据、不同评估日、行业参数顺序、空行业及计数/混合窗口回退。', '',
    '初始手工预期误把 `[2,3,2]` 的末值排除在最低点之外，并使用当前 stock-slot 方言不支持的 `not`。按“当前值等于历史最小值即为最低点”的规则修正并列样例，使用已支持的 `!= True` 验证 NULL 的三值逻辑。旧失败记录保存在 `initial-*-historical-boundaries.json`，原有冻结黄金集未修改。', '',
    '## 性能结果与路线调整', '',
    '| 查询 | 返回行数 | 参考 P95 ms | 优化 P95 ms | 耗时比 |',
    '|---|---:|---:|---:|---:|']
for case in measurements['results']:
    lines.append(f"| {case['id']} | {case['rows']} | {case['baseline']['p95Millis']:.3f} | {case['optimized']['p95Millis']:.3f} | {case['p95Ratio']:.3f}x |")
lines += ['',
    f"五个历史查询的耗时比为 {summary['performance']['historyP95RatioMin']:.2f}–{summary['performance']['historyP95RatioMax']:.2f}x，**尚未达到 10x 目标**。MA60 为已有特征表控制用例，其收益不能代替历史查询指标。",'',
    '第一版“聚合后回连当日行”试跑结果一致；随后改为单次条件聚合以消除第二次扫描。最终五份历史查询计划均为一次基础表扫描、没有分析窗口，但仍遍历历史分区。试跑只有一个样本，不用于两个候选方案之间的稳定性能比较。', '',
    '测量每条路径 30 次，交替执行顺序，关闭 SQL/查询结果缓存；P95 取排序后第 29 个。计时含 JDBC prepare、执行和完整读取，不含编译、进程启动和 EXPLAIN。仅为本机单节点热缓存诊断，未测冷缓存和并发，也不计作正式性能验收。', '',
    '## 下一步', '',
    '1. 优先在隔离诊断环境构建与快照、评估日期绑定的历史极值特征，避免每次重复扫描多年行情，争取达到 10x。至少保存证券日期是否存在、历史 MIN/MAX、当日值或可关联的键，并明确 NULL 规则。',
    '2. 用多日期、完整证券集合及本轮 14 个边界复验；检查新日期或快照不匹配时回退明细路径，再各测 30 次。',
    '3. 该策略验证后扩展 MA20/MA120/MA250；窗口应保留真实观察行和 NULL，禁止以固定日历天数剪掉历史。',
    '4. 官方确认关联规则或补齐数据后生成新快照，再做正式冷/热缓存、并发及外部盲测。当前 249,480 条未关联记录和官方字段待确认事项仍保留，登记表为空。', '',
    '## 复现与证据', '',
    '- [机器汇总](optimization-summary.json)、[最终集成日志](final-selftest/unified-integration.log)、[Doris 边界](final-selftest/doris-historical-boundaries.json)、[本地边界](final-selftest/portable-historical-boundaries.json)。',
    '- [性能证据](hot-30/diagnostic-summary.json)、[逐次样本](hot-30/jdbc-results.json)、[原始文件校验](source-integrity.json)。历史各目录保存两套 SQL/参数、EXPLAIN 及完整返回行。',
    '- [工具与生产源码快照哈希](tool-sources.json)。每次重新构建 JAR 后，必须重新生成与其哈希相符的参考和测量结果。', '',
    '```powershell',
    '.tools/data-audit-venv/Scripts/python.exe scripts/accuracy/check_historical_extrema.py --wsl --output-dir reports/history-optimization/new-selftest',
    '.tools/data-audit-venv/Scripts/python.exe scripts/doris/diagnose_performance.py --matrix benchmarks/history-matrix-v1.json --iterations 30 --report-dir reports/history-optimization/new-hot-run',
    '.tools/data-audit-venv/Scripts/python.exe scripts/doris/summarize_performance.py reports/history-optimization/new-hot-run',
    '```','']
(folder/'历史极值优化与自测报告.md').write_text('\n'.join(lines),encoding='utf-8')
print('PASS: final JAR, all tests, plans, measurement samples and three original source hashes verified')
