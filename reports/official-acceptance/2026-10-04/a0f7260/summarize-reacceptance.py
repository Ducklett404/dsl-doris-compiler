"""Verify the evidence and describe failures without converting them to PASS."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
folder = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/doris'))
from summarize_performance import verify

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def link(name, path):
    return f'[{name}](<{path.resolve().as_posix()}>)'

audit = load(folder/'source-audit/全量数据检查.json')
local = load(folder/'local-results/本地真实数据结果对比.json')
native = load(folder/'local-results/Doris真实数据诊断结果.json')
rolling = load(folder/'independent-rolling.json')
fields = load(folder/'independent-fields-and-functions.json')
tolerance = load(folder/'all-field-tolerance.json')
rise = load(folder/'precision-boundary-probe.json')
position = load(folder/'position-boundary-probe.json')
coverage = load(folder/'corpus-coverage/executable-corpus-summary.json')
gate = load(folder/'execution-gate/controlled-execution-gate.json')
formal = load(folder/'formal-gate/result.json')
scope = load(ROOT/'target/official-acceptance-a0f7260/scope/phase1-scope-validation.json')
source_issues = load(folder/'source-issue-exports.json')
jar_hash = sha(ROOT/'target/dsl-doris-compiler.jar')
manifest = ROOT/'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json'
manifest_hash = sha(manifest)
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
assert head.startswith('a0f7260')
assert subprocess.check_output(['git', 'diff', '--name-only'], cwd=ROOT, text=True).strip() == ''
assert all(r['jarSha256'] == jar_hash for r in [local, native, rolling, fields, rise, coverage])
assert local['manifestSha256'] == native['manifestSha256'] == fields['manifestSha256'] == manifest_hash
assert fields['oracleSha256'] == tolerance['oracleSha256'] == sha(ROOT/'scripts/doris/check_official_field_acceptance.py')
assert fields['sourceAuditSha256'] == sha(folder/'source-audit/全量数据检查.json')
assert local['passed'] == local['total'] == native['passed'] == native['total'] == 34
assert native['functionSmoke']['passed'] == native['functionSmoke']['total'] == 15
assert all(v == 'PASS' for v in native['explain'].values())
assert rolling['status'] == 'PASS' and rolling['totalNumericValuesChecked'] == 168460
assert native['extensionWithoutBasic'] == audit['relationships']['extensionWithoutBasic']['rows'] == 249480
assert gate['status'] == 'PASS' and gate['passed'] == gate['total'] == 9
assert formal['status'] == 'BLOCKED' and formal['overall']['accuracy'] is None and not formal['cases']
assert scope['status'] == 'PASS'
assert fields['queryTotal'] == 233 and fields['queryPassed'] == 231 and fields['status'] == 'FAIL'
failed_queries = [r['id'] for r in fields['queries'] if r['status'] != 'PASS']
assert set(failed_queries) == {'position-低-2026-04-14','position-中-2026-04-14'}
assert tolerance['failedFields'] == ['涨跌幅'] and tolerance['totalValuesChecked'] == 403104 and tolerance['totalMismatches'] == 14327
assert rise['bugReproduced'] and rise['proposedExpressionVerified'] and not rise['changesApplied']
assert position['actualGeneratedCategory'] == '中' and position['expectedCategory'] == '低' and not position['changesApplied']
assert coverage['total'] == 5799 and coverage['sqlCompiled'] == 1 and coverage['rejected'] == 5798 and coverage['internalErrors'] == 0
assert coverage['inputSha256'] == sha(ROOT/coverage['input'])
assert fields['registeredSnapshotsAfter'] == native['registeredSnapshots'] == 0

old = ROOT/'reports/official-route/2026-10-04/final'
performance = verify(old/'hot-30')  # Recompute archived statistics/row hashes only.
assert performance['hashes']['compilerJar'] == jar_hash and performance['hashes']['manifest'] == manifest_hash
assert performance['hashes']['rollingFeatureCatalog'] == sha(old/'rolling-build/catalog.json')
assert performance['hashes']['historicalFeatureCatalog'] == sha(old/'history-build/catalog.json')
junit = {}
for name in ['junit-main','junit-executor']:
    paths = list((old/'final-selftest'/name).glob('TEST-*.xml'))
    assert paths
    junit[name] = {k: sum(int(ET.parse(p).getroot().attrib.get(k, 0)) for p in paths) for k in ['tests','failures','errors','skipped']}
assert junit['junit-main']['tests'] == 275 and junit['junit-executor']['tests'] == 3
assert all(v[k] == 0 for v in junit.values() for k in ['failures','errors','skipped'])

summary = {'status':'DIAGNOSTIC_FAILURES_FORMAL_BLOCKED','acceptanceEligible':False,
           'head':head,'jarSha256':jar_hash,'manifestSha256':manifest_hash,
           'sourceRows':sum(t['rows'] for t in audit['tables'].values()),
           'unmatchedExtensionRows':249480,'closeOutsideRangeWarningRows':3487,
           'freshResults':{'local':34,'doris':34,'smokeExecutionOnly':15,'executionGate':9,
                           'independentFeatureValues':168460,'fieldValues':403104,
                           'fieldOutOfTolerance':14327,'resultCases':233,'resultPassed':231,
                           'failedResultCases':failed_queries},
           'newProjectBugs':['risePct-decimal-scale-truncation','position-third-boundary-floating-point'],
           'fullExtractedCorpusSqlCoverage':{'total':5799,'compiledNotExecuted':1,'rejected':5798},
           'reusedEvidence':{'purpose':'REVERIFIED_EXISTING_EVIDENCE_NOT_FRESH_EXECUTION',
                             'junit':junit,'performanceCases':28,'timedQueries':1680,'concurrentRequests':60},
           'evidenceConsistency':'PASS','completedAtUtc':datetime.now(timezone.utc).isoformat()}

lines = [
    '# 官方数据复验与剩余问题', '',
    '**结论：本轮未通过验收。新增两个项目侧数值问题；原始数据关联失败仍然存在，正式验收仍为 BLOCKED。**', '',
    f'复验日期：2026-10-04；Git 基线：`{head}`；官方快照：`{audit["snapshotId"]}`。本轮增加验收脚本和证据，未修改生产代码、原始 CSV、范围冻结文件或 Doris 语义视图；两种修正方向只做了只读实验。', '',
    '## 本轮实际执行结果', '',
    '| 检查 | 结果 | 说明 |', '|---|---|---|',
    '| 三份原始 CSV 全量扫描 | FAIL | 19,826,855 行；文件 SHA、列数、类型、行数、主键及日期匹配原快照；249,480 行衍生数据关联失败 |',
    '| 原有本地 / 真实 Doris 结果对比 | 34/34、34/34 PASS | 使用新建的独立原始数据审计库复算；覆盖有限用例，不能推出完整业务正确 |',
    '| Doris 函数执行与 EXPLAIN | 15/15、3/3 PASS | 函数执行检查证明可运行；行业空结果不能证明行业算法准确 |',
    '| 已发布特征与独立 Decimal 原始计算 | 168,460 个值 PASS | 2026-04-10、04-13、04-14；112,437 个 NULL 也逐项比较 |',
    '| 19 个字段逐值比较 | FAIL | 5 个日期共 403,104 个值；按冻结容差，14,327 个涨跌幅值超差，其余 18 字段无超差 |',
    '| 新增字段与函数结果对比 | 231/233 PASS | 2 个失败用例均为 2026-04-14 的 position 分类边界 |',
    '| 官方源执行门禁 | 9/9 PASS | 未登记的官方快照仍被 CLI / HTTP 拒绝，临时账号和服务已清理 |',
    '| 正式准确率验收 | BLOCKED | 没有 VALIDATED 登记，执行用例数为 0，准确率为 null |',
    '| 范围冻结及篡改检测 | PASS | LF / CRLF 均通过，改动内容被拒绝，原范围没有被放宽 |',
    '| 历史提取 DSL 直接编译覆盖 | 1/5,799 COMPILED | 其余 5,798 条明确拒绝；无内部异常；这是支持范围检查，未运行全部 DSL，也不是结果正确率 |', '',
    '逐值检查的日期为 2006-01-04、2018-08-20、2026-04-10、2026-04-13、2026-04-14。每个日期检查全部当日证券和 19 个字段，最新日期另检查深 / 沪 / 京各市场；新增筛选还覆盖涨幅别名、百分数字面量、queryData 前导零代码及不存在代码、三种排名、交叉、区间高低点、三档 position、CONS / EXIST。', '',
    '## 新发现的项目问题', '',
    '### P1：涨跌幅在 Doris 中截断为五位小数，改变边界筛选结果', '',
    '`002_semantic_view.sql` 中 `(lastPx-preClosePx)*100.0/preClosePx` 被 Doris 推导为 `decimal(28,5)`。原始价格精确计算与视图值不一致，绝对误差最高接近 0.00001 个百分点；冻结容差是绝对 0.000001 / 相对 0.00000001，并不是允许任意四舍五入。', '',
    '| 日期 | 超出冻结容差的涨跌幅值数 |', '|---|---:|',
]
lines += [f'| {r["date"]} | {r["existingOutOfTolerance"]:,} |' for r in rise['dates']]
lines += [
    '', '2026-04-14 的 `000001`：原始计算为 `0.813008130081300813...`，视图返回 `0.81300`。筛选 `涨跌幅 > 0.8130040650406504` 时，该证券被漏选；2026-04-13 的负数案例也出现多选。五个日期均已用实际编译器 SQL 复现返回集合差异。', '',
    '修正方向：将原始价格显式转换为 DOUBLE 后做减法和除法，并保留 NULL / 零昨收价逻辑。只读实验已对五个日期全部证券验证：超差数降为 0，五个边界筛选集合均恢复为独立计算结果。后续正式落地必须更新语义视图，并按版本流程更新 DDL 冻结记录和回归用例。', '',
    '### P1：position 的三等分边界受浮点误差影响', '',
    '2026-04-14，京市 `920895` 的最近 5 个实际观察日收盘价为 `16.35、16.20、16.65、16.41、16.51`（按日期倒序）。最小值 16.20、最大值 16.65，当日 16.35 恰好是 `min+(max-min)/3`，按冻结规则应归为“低”；生成 SQL 返回“中”。', '',
    '直接比较原始整数价格可证明 `3*(163500-162000)=166500-162000`。该错误使“低”筛选从参考的 131 行变成 130 行，“中”从 71 行变成 72 行。', '',
    '修正方向：明确按指标类型与精度处理区间边界，避免二进制浮点除三后直接比较。使用 DECIMAL 和交叉乘法的只读实验已恢复这一个收盘价案例；仍需设计通用实现，验证价格、成交量、市值、均线等量纲的范围、溢出、NULL、平区间及上下边界后才能作为编译器修复。', '',
    '## 仍存在的数据与范围限制', '',
    '- **关联失败仍是正式验收的硬阻塞。** 249,480 行衍生记录没有同市场、同代码、同日期的基础行情；最新日期 2026-04-14 也有 48 行、48 个证券。完整失败键已导出，不能直接丢行或变更键来宣称通过。',
    '- **3,487 行收盘价在高低价区间外。** 保持 WARN，需要数据方解释不同字段价格口径或补丁；仅凭该现象不能断定项目公式错，也不能擅自修正原始价格。',
    '- **官方字段口径尚未补齐。** 价格 / 金额 / 比率缩放、衍生字段单位、-999999 及复权规则仍是项目假设，代码自洽不等于已获官方确认。',
    '- **行业和真实复权变化无法用这批数据验全。** 5,686 个证券行业名全部 NULL；13,650,347 行行情的复权因子均为 `(1,0,1,0)`，无法覆盖因子变化或非平凡复权。',
    '- **三表不能支撑完整 DSL 业务。** 未经改写的历史提取集 5,799 条中，仅 1 条直接通过 SQL 编译；主要首次拒绝原因是日期形式不支持 3,399 条、指标不支持 2,206 条。每条只统计第一次拒绝，不能将这两个数解释成全部缺失能力的数量。之前的 PARSED 只表示语法分类成功。',
    '- **快照是历史数据。** 最新日期为 2026-04-14，不能用于声称已验证 2026-10-04 的实时行情。实际观察日窗口已验证，但缺少官方交易日历和停牌说明，不能把观察缺口直接认定为停牌。',
    '- **完整正式性能矩阵与外部盲测仍待执行。** 本轮没有重新计时，也没有完成正式冷缓存 / 集群验收。', '',
    '## 自测与证据的界限', '',
    '新增原始计算器自测覆盖缩放、NULL / 零分母、哨兵、不同复权因子、数值差异检测、缺失 / 重复键、日期不在当前观察行及不足窗口。失败用例与两项只读实验均可重跑。证据汇总程序重新核对结果数量、源文件锁、JAR / manifest / 脚本哈希，保留所有 FAIL 和 BLOCKED。', '',
    '原生产代码与 JAR 没有变动，因此之前 275 个主项目 + 3 个执行器 JUnit 测试及 1,680 次热缓存性能查询的证据在本轮复核后复用：XML 无失败 / 错误 / 跳过，JAR、manifest 和特征目录哈希一致，性能统计及结果行哈希重新计算通过。这些属于旧证据复用，不能写成新执行通过，也不能抵消新发现的失败。', '',
    '## 下一步按这个顺序做', '',
    '1. 先修复涨跌幅精度和 position 边界，加入本报告中的真实失败证券及合成边界回归；通过版本化流程更新 DDL / 范围冻结，避免直接改哈希来绕过检测。',
    '2. 重跑本轮 19 字段逐值、233 条扩展结果对比、5 个涨跌幅边界、原有 34 条和受控执行自测，再补覆盖其他量纲 / 均线的 position 上下边界。项目侧问题必须先归零。',
    '3. 将关联失败键、异常价格样例和缺失字段定义交给数据提供方核实；取得规则或补丁后生成新的可追踪快照、重建来源锁和相关特征，再尝试正式 VALIDATED 验收。不要清理问题数据来制造通过。',
    '4. 单独推进完整 DSL 的适配范围：确定显式评价日期、相对观察日语义和可用指标映射；金融、行业、板块等能力需新增相应权威源表。在支持范围和数据条件满足后，再跑完整正式准确率 / 性能矩阵。', '',
    '## 证据文件', '',
]
for name, path in [
    ('本轮机器汇总', folder/'acceptance-summary.json'),
    ('全量原始数据审计', folder/'source-audit/全量数据检查.json'),
    ('19 字段 / 233 个筛选结果', folder/'independent-fields-and-functions.json'),
    ('按冻结数值容差复核', folder/'all-field-tolerance.json'),
    ('涨跌幅五日期复现与修正方向验证', folder/'precision-boundary-probe.json'),
    ('position 边界复现', folder/'position-boundary-probe.json'),
    ('完整提取集编译覆盖', folder/'corpus-coverage/executable-corpus-summary.json'),
    ('正式门禁状态', folder/'formal-gate/result.json'),
    ('全部关联失败键（本地，249,480 行）', ROOT/'target/official-acceptance-a0f7260/source-issues/orphan-extension-keys.csv'),
    ('全部异常价格（本地，3,487 行）', ROOT/'target/official-acceptance-a0f7260/source-issues/close-outside-high-low.csv'),
]:
    lines.append('- ' + link(name, path))
lines += ['', f'生产 JAR SHA-256：`{jar_hash}`；源 manifest SHA-256：`{manifest_hash}`。', '']
(folder/'acceptance-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
(folder/'官方数据复验与剩余问题.md').write_text('\n'.join(lines), encoding='utf-8')
artifacts = {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'evidence-selfcheck.json' and '__pycache__' not in p.parts}
(folder/'evidence-selfcheck.json').write_text(json.dumps({'status':'PASS','purpose':'EVIDENCE_CONSISTENCY_NOT_PRODUCT_ACCEPTANCE','artifacts':artifacts}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'evidenceConsistency':'PASS','acceptanceStatus':summary['status'],'newProjectBugs':summary['newProjectBugs']}, ensure_ascii=False))
