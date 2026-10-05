"""Publish this stage only after correctness, source identity and strict gates agree."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from validate_project_sources import ROOT, digest


def main():
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);args=p.parse_args();folder=args.folder.resolve()
    if (folder/'performance-summary.json').exists():raise ValueError('Preserve published summary')
    def read(name):return json.loads((folder/name).read_text(encoding='utf-8-sig'))
    jar=digest(ROOT/'target/dsl-doris-compiler.jar');cert=digest(folder/'source-validation-final/project-validation.json')
    source=read('source-validation-final/source-validation-report.json');certificate=read('source-validation-final/project-validation.json')
    baseline=read('baseline/result.json');mixed=read('mixed-final/result.json');matrix=read('matrix-final/result.json')
    before=read('timing-before/result.json');after=read('timing-after/result.json')
    junit=read('selftest-verified/junit-results.json');automation=read('selftest-verified/automation/latest.json')
    integration=read('selftest-verified/integration-result.json');precision=read('selftest-verified/numeric-precision-boundaries.json')
    synthetic=read('synthetic-final/result.json');gates=read('strict-gates/controlled-execution-gate.json');formal=read('formal-gate/result.json')
    assert source['status']=='PROJECT_READY_WITH_LIMITATIONS' and source['jarSha256']==jar and source['certificateSha256']==cert
    for name,report in [('mixed',mixed),('matrix',matrix),('after',after),('integration',integration),('precision',precision),('synthetic',synthetic),('gates',gates)]:
        assert report['status']=='PASS',name
        if name in ['mixed','matrix','after','synthetic']:assert report['jarSha256']==jar,name+' JAR'
        if name in ['mixed','matrix','after']:assert report['certificateSha256']==cert,name+' certificate'
    assert mixed['total']==72 and mixed['passed']==72 and len(matrix['executions'])==91 and matrix['passed']==matrix['total']==188
    assert mixed['rounds']==3 and mixed['environment']==matrix['environment']==after['environment']==dict(containerMemoryBytes=10737418240,beMemoryShare='60%')
    for report in [before,after]:assert report['status']=='PASS' and report['total']==report['passed']==16 and report['rounds']==8
    assert before['jarSha256']==baseline['jarSha256'] and before['jarSha256']!=jar
    assert before['oracleSha256']==after['oracleSha256']==mixed['oracleSha256']==digest(ROOT/'scripts/doris/project_matrix_reference.py')
    assert read('timing-before/matrix.json')==read('timing-after/matrix.json')
    assert baseline['total']==23 and baseline['passed']==7 and baseline['status']=='FAIL'
    assert all(v['failures']==v['errors']==v['skipped']==0 for v in junit.values())
    assert all(automation['checks'][key]['status']=='PASS' for key in ['maven-all-tests','executor-module-tests','project-matrix-reference-tests','project-window-boundaries','project-rsi-tail-boundaries','formal-compiler-p95'])
    boundaries=read('selftest-verified/portable-boundaries/project-window-boundaries.json');rsi=read('selftest-verified/portable-boundaries/project-rsi-tail-boundaries.json')
    preflight=read('environment-preflight.json');ci=read('ci-configuration.json')
    assert preflight['status']=='PASS' and preflight['passed']==preflight['total']==3
    assert ci['status']=='PASS' and ci['remoteCiExecuted'] is False
    for report,total in [(boundaries,48),(rsi,16),(synthetic,38),(integration,18),(precision,42),(gates,9)]:assert report['status']=='PASS' and report['passed']==report['total']==total
    assert boundaries['jarSha256']==rsi['jarSha256']==jar
    assert formal['status']=='BLOCKED' and len(formal['cases'])==0 and formal['overall']['accuracy'] is None
    assert formal['artifactHashes']['compilerJarSha256']==jar and formal['physicalSnapshotMatchesManifest'] is True
    timings={};plan_counts={}
    def stats(report,name):
        samples=[e for e in report['executions'] if e['case']==name]
        def percentile(values):return sorted(values)[math.ceil(len(values)*.95)-1]
        return dict(samples=len(samples),p95TotalMillis=percentile([e['timings']['totalMillis'] for e in samples]),
            p95ValidationMillis=percentile([e['validationMillis'] for e in samples]),p95MainSqlMillis=percentile([e['timings']['dorisExecutionMillis'] for e in samples]))
    for name in ['position3','rsi5']:
        b,a=stats(before,name),stats(after,name);timings[name]=dict(before=b,after=a,totalP95ReductionPercent=100*(1-a['p95TotalMillis']/b['p95TotalMillis']))
        old=read('timing-before/'+name+'-1-plans.json');new=read('timing-after/'+name+'-1-plans.json')
        def scans(plan):return sum('TABLE: newzl.hsj_stock_hq_basic(' in line for line in plan['explain'])
        assert scans(old['main'])==scans(old['sql'])==scans(old['samplesSql'])==scans(new['main'])==scans(new['combinedSql'])==1
        plan_counts[name]=dict(beforeStatements=3,afterStatements=2,beforeDiagnosticHistoryScans=2,afterDiagnosticHistoryScans=1)
    evidence={str(path.relative_to(folder)).replace('\\','/'):digest(path) for path in sorted(folder.rglob('*')) if path.is_file()}
    compiler=read('selftest-verified/compiler-performance/latest.json')
    summary=dict(status='PROJECT_WINDOW_PERFORMANCE_PASS_FORMAL_BLOCKED',officialAcceptanceEligible=False,completedAtUtc=datetime.now(timezone.utc).isoformat(),
        jarSha256=jar,certificateSha256=cert,manifestSha256=certificate['manifestSha256'],baselinePassed=7,baselineTotal=23,
        mixedPassed=72,mixedTotal=72,matrixExecutions=91,matrixChecks=188,timings=timings,planCounts=plan_counts,
        javaTests=sum(v['tests'] for v in junit.values()),referenceUnitTests=13,windowBoundaryChecks=48,rsiBoundaryChecks=16,
        syntheticChecks=38,integrationChecks=18,numericChecks=42,strictGateChecks=9,formalStatus='BLOCKED',formalAccuracy=None,
        environment=mixed['environment'],queryBudget=dict(memoryBytes=2147483648,timeoutSeconds=10,maxEstimatedScanRows=100000000),
        compilerPerformance=compiler,evidenceSha256=evidence,implementationSha256={name:digest(ROOT/name) for name in [
            'src/main/java/com/acme/dorisdsl/stockslot/StockSlotAdvancedSqlCompiler.java','src/main/java/com/acme/dorisdsl/stockslot/StockSlotCoveragePlan.java',
            'src/main/java/com/acme/dorisdsl/stockslot/DorisQueryExecutor.java','scripts/doris/check_project_window_performance.py',
        'scripts/doris/check_project_window_boundaries.py','scripts/doris/project_matrix_reference.py','scripts/doris/summarize_project_window_performance.py',
        'scripts/doris/run_wsl_integration.py','scripts/doris/requirements-selftest.txt','.github/workflows/automated-tests.yml','.github/workflows/doris-acceptance.yml']})
    (folder/'performance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 窗口性能优化与自测报告','',f"状态：`{summary['status']}`。原始官方数据可以继续按已验证来源运行；默认正式验收仍 BLOCKED。",'',
        '## 已完成的修复','',
        '1. 以一次只读 SQL 同时取得缺失总数和最多 20 行样本，统计发生在筛选、THEN、排名和 LIMIT 之前。空行情仍返回零统计。旧分离 SQL 仅用于独立对照。',
        '2. 对混合有限窗口和 CONS/EXIST 计算完整的观察行依赖。RSI(N) 额外保留一条前驱价格；次数窗口再增加其观察范围减一；函数间比较同时考虑两个操作数。例如 RSI5 + EXIST>=3日需要 25 条价格，MA20 + 同条件需要 39 条。NULL 行与停牌间隔均保留。',
        '3. 基础观察行裁剪后再左关联衍生数据，解决 RSI + 资金查询因完整历史关联估算超出扫描门禁而被拒绝的问题。完整三键、缺失值和当日证券范围保持一致。',
        '4. 保留 FULL_SCAN_REFERENCE。无限历史、queryData、代码/行业关联及未验证特征仍使用完整历史。修正 Windows 测试输出编码及统一自测的 Python 解释器传递；增加缺依赖前置拒绝，并将固定依赖及新边界检查加入 CI。','',
        '## 官方数据正确性与资源验证','',
        '优化前 23 组：7 组通过，14 组 Doris 错误、1 组超时、1 组扫描上限拒绝，全部失败证据保留。仅凭错误类别不能把 14 次 Doris 错误都归为同一种内存故障。',
        '最终 24 组查询重复 3 轮，共 72/72 次通过，包含 RSI+MA/position/极值/交叉/资金、三种窗口各自的 CONS>=/= 与 EXIST>=/=、双次数窗口、THEN+排名、多日期及无行情。每次比较原始行独立参考的完整有序证券列表、未截断标记、全部缺失计数和样本标记。',
        '既有 67 组矩阵也重新运行：91 次执行、188/188 项检查通过，包括两次诊断容器重启后的来源、配置和结果核验。',
        '每条查询仍 2GiB、10 秒、1 亿行估算扫描上限、最多 10,000 条结果；诊断容器 10GiB、BE 60% 与此前一致。通过证明测试查询在受控预算内可完成，报告没有逐条实际峰值内存测量。原始 CSV 哈希、三张原表共 19,826,855 行及来源定义重新验证一致。249,480 条未关联衍生行及 3,487 条价格范围警告保留，快照登记表仍为空。','',
        '## 同一查询的前后计时','',
        '两种查询分别 8 次顺序 HTTP 请求，每次均核对正确性；P95 用 nearest-rank，因此 8 次样本的 P95 为最大值。计时包含首个服务请求，无独立预热剔除；没有清空 OS 页缓存。它是小样本本地诊断，不代表正式冷缓存、并发或集群性能验收。','',
        '| 查询 | 总 P95 前 / 后（ms） | 诊断 P95 前 / 后（ms） | 总 P95 降低 |','|---|---:|---:|---:|']
    for name,t in timings.items():lines.append(f"| {name} | {t['before']['p95TotalMillis']:.1f} / {t['after']['p95TotalMillis']:.1f} | {t['before']['p95ValidationMillis']:.1f} / {t['after']['p95ValidationMillis']:.1f} | {t['totalP95ReductionPercent']:.1f}% |")
    lines += ['', '原生 EXPLAIN 在两种查询中均确认：缺失统计与样本原来分别扫描基础历史，各 1 个扫描节点；合并后诊断仅 1 个节点。加上主查询，执行语句从 3 条变为 2 条。尾部裁剪仍需扫描基础历史来选择观察行，不能将它解释为全部原始数据读取量按窗口比例下降。validationMillis 包含来源核验及 EXPLAIN，与 explainMillis 有重叠，不相加。','',
        '## 自测与失败追踪','',f"Java {summary['javaTests']} 项、独立参考单元 13 项、混合窗口边界 48 项、RSI 尾部边界 16 项、项目临时库入口 38 项、真实 Doris 严格集成 18 项、数值边界 42 项、严格门禁 9 项全部通过。Java 无失败、错误或跳过。统一测试及编译器 P95 检查通过；新增 3 项 Python 环境前置检查通过。CI 配置仅完成本地 YAML 解析，没有触发 GitHub CI；外部盲测和正式 19 年矩阵没有运行。",'',
        '- baseline：保存优化前 23 组结果，FAIL。',
        '- attempt-001：21 组基础行情相关查询通过，资金混合仍因扫描估算过大失败；funds-attempt-002 保存调整关联后的计划与通过结果。',
        '- mixed-boundaries-attempt*：保留新测试开发阶段的编码、视图名、缺行参考构造和跨引擎日期函数适配错误。最终统一自测保存 48 项完整通过记录。',
        '- selftest-final / selftest-release：分别因系统 Python 缺 DuckDB、虚拟环境缺 openpyxl 停止；最终 selftest-verified 使用现有 Python 3.12 虚拟环境与已安装同版本库，完成所有检查，无下载或系统软件改动。',
        '- source-validation-final、mixed-final、matrix-final、timing-before/after、synthetic-final、strict-gates、formal-gate 为本轮证据；performance-summary.json 保存文件哈希及版本。','',
        '## 下一步','',
        '补充可用性解释：为同一指标的不同周期提供稳定窗口标识，列出样本证券窗口内的具体缺失日期，并区分观察行不足、NULL/哨兵、无衍生行、零分母和平坦区间。沿用本轮单次诊断与资源限制，再以手工边界和官方数据自测。','',
        f"最终 JAR SHA256：`{jar}`；证据 SHA256：`{cert}`。正式报告为 BLOCKED、0 条用例、accuracy=null；项目内部通过不能替代官方口径确认和外部验收。",'',
        '复跑命令：','', '```powershell',
        '& .tools/data-audit-venv/Scripts/python.exe -X utf8 scripts/doris/check_project_window_performance.py `',
        '  --certificate reports/project-performance/2026-10-05/source-validation-final/project-validation.json `',
        '  --output-dir reports/project-performance/新批次/mixed --rounds 3 --explain',
        '```','']
    (folder/'窗口性能优化与自测报告.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['status','mixedPassed','matrixChecks','javaTests']},ensure_ascii=False))


if __name__=='__main__':main()
