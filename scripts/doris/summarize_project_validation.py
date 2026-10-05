"""Publish project-scoped evidence only after final identities, coverage checks and strict gates agree."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args();folder=args.folder.resolve()
    jar=digest(ROOT/'target/dsl-doris-compiler.jar')
    paths=dict(sources='source-validation-release/source-validation-report.json',certificate='source-validation-release/project-validation.json',
        integration='final-selftest-release/integration-result.json',numeric='final-selftest-release/numeric-precision-boundaries.json',
        junit='final-selftest-release/junit-results.json',automation='final-selftest-release/automation/latest.json',
        compiler='final-selftest-release/compiler-performance/latest.json',scope='final-selftest-release/scope/phase1-scope-validation.json',
        synthetic='synthetic-release/result.json',official='official-release-final/result.json',strict='strict-gates/controlled-execution-gate.json',formal='formal-gate/result.json')
    evidence={key:read(folder/path) for key,path in paths.items()}
    for key,count in [('integration',18),('numeric',42),('synthetic',38),('official',32),('strict',9)]:
        data=evidence[key];assert data['status']=='PASS' and data['passed']==data['total']==count,key
    for key in ['sources','numeric','synthetic','official']:
        assert evidence[key]['jarSha256']==jar,key
    assert evidence['integration']['compilerJarSha256']==jar
    assert evidence['integration']['fixtureCleanup']==evidence['numeric']['fixtureCleanup']=='DONE'
    assert evidence['synthetic']['cleanup']==evidence['official']['cleanup']=='DONE'
    sources=evidence['sources'];certificate=evidence['certificate']
    assert sources['status']=='PROJECT_READY_WITH_LIMITATIONS' and sources['officialRegistryUnchanged']
    assert all(s['status']=='PROJECT_READY' for s in certificate['sources'].values())
    assert len(sources['sourceIntegrity'])==3 and all(s['status']=='PASS' for s in sources['sourceIntegrity'])
    assert certificate['extensionWithoutBasic']==249480 and certificate['closeOutsideRange']==3487
    assert sum(sources['rawSourceRows'].values())==19826855
    assert sources['certificateSha256']==evidence['official']['certificateSha256']==digest(folder/paths['certificate'])
    manifest=digest(ROOT/'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json')
    assert certificate['manifestSha256']==evidence['official']['manifestSha256']==manifest
    formal=evidence['formal'];assert formal['status']=='BLOCKED' and not formal['snapshotVerified'] and not formal['cases'] and formal['overall']['accuracy'] is None
    assert formal['artifactHashes']['compilerJarSha256']==jar
    junit=evidence['junit']
    for key,count in [('main',284),('executor',3)]:
        assert junit[key]['tests']==count and not any(junit[key][f] for f in ['failures','errors','skipped']),key
    assert all(c['status'] in ['PASS','NOT_RUN'] for c in evidence['automation']['checks'].values())
    assert evidence['scope']['status']=='PASS'
    p95=evidence['compiler']['uncachedPipeline']['stages']['total']['p95'];assert p95<50
    official=evidence['official'];assert len(official['cases'])==12 and not official['officialAcceptanceEligible']
    latest=read(folder/'official-release-final/net.json')['dataQuality']
    assert latest['observedSecurities']==5614 and latest['currentMissingExtensionRows']==0
    assert latest['inputs'][0]['unavailableSecurities']==347
    assert all(c.get('keysEqual',True) and c.get('coverageEqual',True) for c in official['checks'])
    summary=dict(status='PROJECT_SCOPED_PASS_FORMAL_BLOCKED',officialAcceptanceEligible=False,completedAtUtc=datetime.now(timezone.utc).isoformat(),
        jarSha256=jar,manifestSha256=manifest,registryFingerprint=certificate['registryFingerprint'],certificateSha256=sources['certificateSha256'],
        policySha256=digest(ROOT/'config/acceptance/project-data-policy-v1.json'),rawRows=19826855,sourceCsvHashesVerified=3,
        unmatchedExtensionRows=249480,priceRangeWarnings=3487,officialRegistryRows=0,
        junit={key:{field:data[field] for field in ['tests','failures','errors','skipped']} for key,data in junit.items()},
        projectIntegrationChecks=38,officialControlledChecks=32,officialCliQueries=12,officialHttpResultComparison=1,
        strictIntegrationChecks=18,numericBoundaryChecks=42,strictNegativeGateChecks=9,compilerUncachedP95Millis=p95,
        automationNotRun=[name for name,c in evidence['automation']['checks'].items() if c['status']=='NOT_RUN'],
        evidenceHashes={key:digest(folder/path) for key,path in paths.items()})
    (folder/'project-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 分能力验收与自测报告','', '日期：2026-10-05。结论：**现有官方数据可以通过新增项目入口运行本轮所测查询，并明确披露缺失影响；严格完整快照验收仍为 BLOCKED。** 未修改原始数据、补造价格或登记官方 VALIDATED。',
        '', '## 本轮完成', '',
        '1. CLI 和 HTTP 新增可信本地 `--project-validation` 配置。基础行情、衍生行情、证券代码按实际依赖分别验证；行业与无来源功能明确拒绝。默认严格入口和正式性能入口继续保留原门禁。',
        '2. 结果新增数据可用性：筛选前实际行情证券数、当日衍生缺行、各输入 NULL、完整窗口不足、次数窗口条件不明及最多 20 个样本。数量在用户条件、排名及分页前统计，各输入可能重叠，不能相加。',
        '3. 每次查询使用只读元数据和行数核对来源身份，保留超时、扫描、内存、排队、返回上限与认证控制。发布时重查三份官方 CSV 哈希、日期、唯一键和字段。',
        '4. 修正路线：无需继续等待官方补丁才能推进项目验证。有限 position 单独使用真实观察行尾部，保持 NULL 与停牌间隔，解决本轮完整历史覆盖统计的内存问题。原完整参考路径仍保留。',
        '', '## 最终自测', '', '| 检查 | 结果 |','|---|---|',
        '| 主模块 / 执行器 Java | 284 / 3，全部通过，无跳过 |',
        '| 新入口真实 CLI/HTTP、缺失与变更拦截 | 38/38，含跨月稀疏观察、平坦区间、NULL、哨兵和来源阻断 |',
        '| 官方数据受控验证 | 32/32；12 条 CLI 完整结果及输入统计、1 条 HTTP 完整结果独立对比 |',
        '| 原严格运行集成 / 负向门禁 | 18/18、9/9 |',
        '| 数值边界 | 42/42 |',
        '| 原始文件 / 范围冻结 | 3 份 CSV 哈希一致；v1.0.2 冻结通过 |',
        f'| 禁用结果缓存的编译 P95 | {p95:.4f} ms，5,000 次样本，门槛 50 ms |',
        '| 正式完整快照 | BLOCKED；正式准确率为 null，正式用例未执行 |',
        '', 'Python、窗口、旧功能与编译回归随完整自测通过。自动化脚本内的正式黄金验收、函数烟测及完整 19 年性能矩阵仍标记 NOT_RUN，未计为通过；本轮另运行了实际项目入口及隔离边界检查。没有把项目数据验证改称官方验收。',
        '', '## 官方查询结果', '',
        '独立参考读取绑定清单的原始 DuckDB 数据，按真实观察行计算；没有使用编译器输出反推期望。逐项比较完整证券列表、排序、未截断状态、观察证券数及所有输入缺失数。',
        '', '| 查询 | 评价日 | 返回证券数 | 输入状态 |', '|---|---|---:|---|']
    titles=dict(close='收盘价',net='主力净流入',mixed='价格与资金组合',ma5='MA5',cons3='连续 3 次',exist3='20 条观察中的至少 3 次',position3='3 条观察位置高',cross='上穿',rank='前三个价格档位排名',queryData='与指定证券比较',
                **{'first-basic':'最早日基础行情','early-extension':'衍生起始日资金'})
    statuses={'PARTIAL_INPUTS':'有输入缺失','COMPLETE_QUERY_INPUTS':'当前查询输入完整','NO_OBSERVATIONS':'评价日无行情'}
    for row in official['cases']:
        lines.append(f"| {titles.get(row['name'],row['name'])} | {row['evaluationDate']} | {row['rows']} | {statuses[row['coverageStatus']]} |")
    lines += ['', '2026-04-14 基础范围实际有行情的证券为 **5,614**。当日每个基础行情证券都有对应衍生行，但主力净流入仍有 **347** 个不可计算输入（字段 NULL/哨兵）；所以当日关联完整不等于字段可用。收盘价有 41 个 NULL 输入。全快照另有 249,480 条衍生记录没有对应基础行情，均保留。',
        '', '## 遇到的问题与路线修正', '',
        '- 只读账号的 SHOW CREATE 被 Doris 权限拒绝。改用 information_schema 的视图 SQL 哈希及有序列定义；真实视图变更后的 CLI 和 HTTP 都拒绝继续使用旧证据。没有增加写权限。',
        '- 次数条件沿用冻结规则，将 NULL 条件按未命中计数；另列窗口条件不明数量，避免把历史 NULL 隐藏在次数结果中。',
        '- 完整历史 position 覆盖统计触发 2GB MEM_LIMIT_EXCEEDED。项目路径仅对有限、无次数、纯 position 查询保留最大所需实际观察行；历史或混合查询仍走完整参考。首次修正复验仍遇到一次通用 Doris 拒绝，单独探针全部 SQL 通过，随后单独与整组复验通过；该次原因没有充分诊断，不计作通过。保留记录，后续性能与稳定性检查需继续覆盖。',
        '- 官方 queryData 的最终组首次因测试期望使用驼峰函数名、实际规范名为小写而失败；修正测试标签后整组复验。WSL 地址读取的诊断文本编码也已修正。先前失败报告未覆盖。',
        '', '## 保留的边界', '',
        '这是项目已冻结字段公式与缺值约定下的计算证据；官方单位、价格口径、关联定义及哨兵语义没有额外确认。行业字段、无来源财务功能、外部盲测和正式完整快照认可仍未完成。3,487 条收盘价超出高低范围的警告原样记录。',
        '', '运行时核验行数、视图 SQL 和列定义，不能检测同一结构、同一行数的数据内容替换。依赖不可变装载快照和只读账号，外部数据写入后必须重新验证。覆盖样本尚不包含窗口内每个缺失日期。明细窗口和额外诊断有资源成本，本轮单次计时不能代表正式性能验收。',
        '', '## 下一步', '',
        '基于现有文件扩大多日期、多市场、随机组合查询与缺失边界验收，逐项保存结果列表和可用性参考；再测量诊断的资源开销、位置路径重复/冷启动稳定性，优化已有数据支持的访问路径与功能。继续保留明确的项目验证层级，正式门禁不放宽。',
        '', '## 复现与证据', '',
        '- 操作说明：[按查询依赖验证指南](../../../docs/project-scoped-validation.md)。',
        '- 来源证据：[project-validation.json](source-validation-release/project-validation.json)。',
        '- 官方完整检查：[result.json](official-release-final/result.json)。',
        '- HTTP 可读输出：[official-http-result.md](official-release-final/official-http-result.md)。',
        '- 汇总身份与证据哈希：[project-summary.json](project-summary.json)。',
        '- 所有临时测试库、测试账号及 HTTP 进程均由脚本关闭清理；官方数据和登记表保持原状态。',
        '', f'最终 JAR SHA-256：`{jar}`。',f'清单 SHA-256：`{manifest}`。',f'字段注册表语义指纹：`{certificate["registryFingerprint"]}`。','']
    (folder/'分能力验收与自测报告.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({key:summary[key] for key in ['status','projectIntegrationChecks','officialControlledChecks','compilerUncachedP95Millis']}))


if __name__=='__main__': main()
