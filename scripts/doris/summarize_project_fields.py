"""Verify fresh field-stage evidence and write the delivery report."""
import argparse
from datetime import datetime,timezone
import json
from validate_project_sources import ROOT,digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--report-dir',required=True);args=p.parse_args()
    folder=(ROOT/args.report_dir).resolve();destination=folder/'field-summary.json';markdown=folder/'逐字段验证与自测报告.md'
    if destination.exists() or markdown.exists():raise ValueError('Preserve previous summaries')
    def read(path):return json.loads((folder/path).read_text(encoding='utf-8-sig'))
    jar=digest(ROOT/'target/dsl-doris-compiler.jar');cert=digest(folder/'source-validation/project-validation.json')
    junit=read('selftest-final/junit-results.json');assert sum(v['tests'] for v in junit.values())==319
    assert all(v[k]==0 for v in junit.values() for k in ['failures','errors','skipped'])
    checks={}
    for path,total,cleanup in [('native-fixture.json',94,'fixtureCleanup'),('native-matrix/result.json',94,'cleanup'),
        ('official-field-verification.json',94,None),('synthetic-project/result.json',40,'cleanup'),
        ('strict-gates/controlled-execution-gate.json',9,None),('selftest-final/integration-result.json',18,'fixtureCleanup'),
        ('selftest-final/numeric-precision-boundaries.json',42,'fixtureCleanup'),
        ('selftest-final/portable-boundaries/project-field-boundaries.json',94,None),
        ('selftest-final/portable-boundaries/project-availability-explanations.json',28,None),
        ('selftest-final/portable-boundaries/project-window-boundaries.json',48,None),
        ('selftest-final/portable-boundaries/project-rsi-tail-boundaries.json',16,None)]:
        data=read(path);assert data['status']=='PASS' and data['total']==data['passed']==total,path
        if cleanup:assert data[cleanup]=='DONE',path
        for key in ['jarSha256','compilerJarSha256']:
            if key in data:assert data[key]==jar,(path,key)
        checks[path]=dict(passed=total,total=total)
    source=read('source-validation/source-validation-report.json');certified=read('source-validation/project-validation.json')
    assert source['status']=='PROJECT_READY_WITH_LIMITATIONS' and source['officialRegistryUnchanged']
    assert source['jarSha256']==jar and source['certificateSha256']==cert
    assert all(r['status']=='PASS' for r in source['sourceIntegrity'])
    assert source['rawSourceRows']==dict(basic=13650347,extension=6170822,code=5686)
    assert certified['extensionWithoutBasic']==249480 and certified['closeOutsideRange']==3487
    native=read('native-matrix/result.json');fields=read('official-field-verification.json')
    assert fields['certificateSha256']==native['certificateSha256']==cert and fields['sourcesUnchanged']
    assert native['environment']==dict(containerMemoryBytes=10737418240,beMemoryShare='60%')
    assert fields['runnerSha256']==digest(ROOT/'scripts/doris/check_project_fields.py')
    assert len(fields['values'])==5 and all(d['status']=='PASS' and len(d['perField'])==19 for d in fields['values'])
    formal=read('formal-gate/result.json')
    assert formal['status']=='BLOCKED' and formal['overall']['total']==0 and formal['overall']['accuracy'] is None
    assert formal['physicalSnapshotMatchesManifest'] and formal['artifactHashes']['compilerJarSha256']==jar
    compiler=read('selftest-final/compiler-performance/latest.json')
    assert compiler['passed'] and compiler['uncachedPipeline']['iterations']==5000
    automation=read('selftest-final/automation/latest.json');assert all(c['status'] in ['PASS','NOT_RUN'] for c in automation['checks'].values())
    total_values=sum(d['valuesChecked'] for d in fields['values']);null_values=sum(d['nullValuesChecked'] for d in fields['values'])
    latest=next(d for d in fields['values'] if d['date']=='2026-04-14')
    latest_rows='\n'.join(f"| {f['name']} | {f['nonNull']} | {f['nulls']} |" for f in latest['perField'])
    examples=[]
    for metric in ['average','rise','qfq']:
        data=read('native-matrix/field-'+metric+'-2026-04-14-1.json')
        for sample in data['dataQuality']['sampleDetails'][:1]:
            for issue in sample['inputs']:
                examples.append(dict(metric=issue['indicator'],market=sample['marketCode'],code=sample['securityCode'],reasons=issue['reasons']))
    implementation=[
        'src/main/java/com/acme/dorisdsl/stockslot/StockSlotAvailabilityDiagnostics.java',
        'src/test/java/com/acme/dorisdsl/ProjectAvailabilityDiagnosticsTest.java',
        'scripts/doris/project_field_reference.py','scripts/doris/check_project_fields.py','scripts/doris/test_project_field_reference.py',
        'scripts/doris/project_matrix_reference.py','scripts/doris/check_project_availability.py',
        'scripts/doris/check_project_window_performance.py','scripts/doris/ProjectAvailabilityProbe.java',
        'scripts/doris/archive_project_selftest.py','scripts/test-all.ps1','scripts/doris/summarize_project_fields.py',
        '.github/workflows/automated-tests.yml','.github/workflows/doris-acceptance.yml']
    summary=dict(status='PROJECT_FIELDS_PASS_FORMAL_BLOCKED',officialAcceptanceEligible=False,completedAtUtc=datetime.now(timezone.utc).isoformat(),
        jarSha256=jar,certificateSha256=cert,manifestSha256=source['manifestSha256'],javaTests=319,newJavaTests=6,
        manualFieldTests=8,fieldInventory=19,rawValueDates=[d['date'] for d in fields['values']],valuesChecked=total_values,nullValuesChecked=null_values,
        sourceRows=source['rawSourceRows'],sourceIntegrity=source['sourceIntegrity'],checks=checks,examples=examples,
        compilerP95Millis=compiler['uncachedPipeline']['stages']['total']['p95'],environment=native['environment'],
        queryBudget=dict(memoryBytes=2147483648,timeoutSeconds=10,maxEstimatedScanRows=100000000,maxReturnRows=10000),
        formalStatus='BLOCKED',formalCases=0,formalAccuracy=None,remoteCiExecuted=False,restartRepeated=False,
        implementationHashes={path:digest(ROOT/path) for path in implementation},
        evidenceHashes={str(path.relative_to(folder)).replace('\\','/'):digest(path) for path in sorted(folder.rglob('*.json'))})
    destination.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    example_text='\n'.join('- '+e['metric']+'，'+e['market']+'/'+e['code']+'：'+
        '；'.join(r['code']+'（'+r['indicator']+'，'+','.join(r['relatedDates'])+'）' for r in e['reasons']) for e in examples)
    text=f'''# 逐字段验证与自测报告

本轮结论：`PROJECT_FIELDS_PASS_FORMAL_BLOCKED`。现有 19 个已映射指标在项目规则下通过逐字段验证；正式验收门禁继续 BLOCKED。

## 完成范围与修复

1. 梳理 18 个基础行情指标和 1 个资金指标的原始字段、缩放、项目单位与 NULL 规则，见 [字段规则](../../../docs/project-field-rules.md)。没有把项目假设写成官方确认，也没有扩大注册表能力。
2. 细分均价、涨跌幅、市值和复权收盘价的缺值解释，读取固定白名单原始计算字段，给出 `SOURCE_OPERAND_NULL` 或具体零分母。例如同日分子 NULL、分母 0 会同时列出两种原因。原始字段不能支持结论时明确标注解释不完整。
3. 解释器与 position 的 SQL 数值路径保持一致：伴随字段已经缩放，避免重复缩放振幅；没有伴随字段的复权值也按注册表的小数位数转换。小于声明精度的差异可能成为平坦区间，现在可给出对应解释。主查询公式和证券结果规则没有变更。
4. 增加手工字段参考、94 组矩阵及 CI/统一自测入口。预期值从独立原始行计算，不从生成 SQL 或视图反推。

94 组包含 19 指标 × 3 日期点查询、19 个 position3、6 个派生指标次数，以及 6 个派生指标 × 2 补充日期点查询。官方数据日期为 2006-01-04、2018-08-20、2026-04-10、2026-04-13、2026-04-14；真实查询未补日历行，原始代码保留前导零，资金按三键关联。

## 官方数据上的结果

五个日期共核对 **{total_values:,} 个字段值**，其中 **{null_values:,} 个 NULL**；与手工公式一致。非 NULL 数值使用 `1e-10 * max(1, abs(expected))` 容差。94 次项目入口执行的完整证券列表、顺序、缺值数量、前 20 个样本和资源预算完全一致；同一批 94 次执行的样本原因、观察数和具体日期再次从原始行独立核对，不计作额外 94 次查询。

真实样本：

{example_text}

最新日逐字段有效性如下（5614 只基础行情证券）。NULL 不等同于项目错误，也不以 0 替代：

| 指标 | 非 NULL | NULL |
|---|---:|---:|
{latest_rows}

复权数据的现有乘加参数覆盖有限，真实数据通过不能证明所有复权口径；隔离边界另使用非平凡乘数和加数。五个日期的字段数值核对不代表全部历史逐行验算，缺值样本最多 20 只，也不代表全量原因分布。

## 自测与证据

| 检查 | 结果 | 证据 |
|---|---|---|
| 主模块 / 执行器 Java | 316 + 3 = 319，无失败、错误或跳过，新增 6 项字段解释测试 | [JUnit](selftest-final/junit-results.json) |
| 独立手工公式 | 新增 8 项；原有 13 项参考检查也通过 | [统一自测](selftest-final/automation/latest.json) |
| 便携字段结果、覆盖及原因边界 | 94/94，包含每个原始 NULL、零分母、合法负值、哨兵、稀疏日期、未来行与观察不足 | [字段边界](selftest-final/portable-boundaries/project-field-boundaries.json) |
| 真实 Doris 隔离字段边界 | 94/94，实际生成 SQL、缺值与日期一致，临时库清理完成 | [原生边界](native-fixture.json) |
| 官方数据项目入口 | 94/94，只读账户，完整列表、顺序、覆盖和预算一致 | [矩阵](native-matrix/result.json) |
| 官方字段值及原因独立复验 | 五个日期，{total_values:,} 个值；同一 94 次执行的解释核对全部通过 | [字段与原因](official-field-verification.json) |
| CLI/HTTP、来源变化和历史 NULL 回归 | 40/40 | [项目入口](synthetic-project/result.json) |
| 真实 JDBC / 精度边界 | 18/18 与 42/42 | [集成](selftest-final/integration-result.json)、[精度](selftest-final/numeric-precision-boundaries.json) |
| 原有解释 / 混合窗口 / RSI | 28/28、48/48、16/16 | [解释](selftest-final/portable-boundaries/project-availability-explanations.json)、[窗口](selftest-final/portable-boundaries/project-window-boundaries.json)、[RSI](selftest-final/portable-boundaries/project-rsi-tail-boundaries.json) |
| 严格执行拒绝 | 9/9 | [门禁](strict-gates/controlled-execution-gate.json) |
| 编译性能 | 5000 次，总 P95 {summary['compilerP95Millis']:.4f}ms，低于 50ms | [编译性能](selftest-final/compiler-performance/latest.json) |
| 原始 CSV、来源定义及行数 | 19,826,855 行，CSV 校验和一致，证书和正式登记保持原有边界 | [来源](source-validation/source-validation-report.json) |

本轮没有重复重启、清空宿主机缓存或执行正式并发/冷缓存评测。没有采集峰值内存 Profile，也不宣称性能收益；容器 10GiB、BE 60%，查询仍 2GiB/10 秒/扫描估算一亿行/返回 10000 行。解释仍限 20 个样本、32 字段、10001 条历史加探测行，超过预算明确披露不完整。CI 配置已本地核查，未执行远程 CI。

## 失败记录与正式验收边界

早期 `portable-investigation.json` 缺少视图需要的额外衍生列；`portable-fixture-complete.json` 缺少 DuckDB 的日期函数适配。补齐测试夹具和 `DATE_FORMAT` 适配后最终 94/94 通过。这两次失败没有计入最终通过；没有因此修改官方数据或项目公式。

最后的正式门禁命令曾因审批服务用量限制未获执行。恢复时间后通过原审批流程复跑成功；调用封装一度把预期退出码误写为 1，核对源码确认 BLOCKED 的退出码为 2。报告内容和快照校验均正确，不把这次封装误判归为字段计算失败。

正式门禁复核为 BLOCKED，物理文件与清单一致，但没有 VALIDATED 快照登记。正式查询执行 0 组，准确率为 null。249,480 条未关联衍生行、3,487 条价格范围警告及行业字段缺失继续保留。官方字典、外部盲测、完整快照认可与正式性能验收依旧没有通过依据，见 [正式门禁](formal-gate/result.json)。

最终 JAR SHA256：`{jar}`。来源证书 SHA256：`{cert}`。实现和工件哈希见 [机器汇总](field-summary.json)。所有本轮临时数据库与账户已清理。

## 下一步

把已逐字段验证的均价、复权、换手率、市值与资金加入多指标组合、排名/LIMIT、跨证券查找和次数回归，优先检查精确阈值、NULL 条件组合及两个窗口并用。之后形成一个可复跑的项目验收入口和能力边界清单，并继续自测。正式门禁仍按现有规则执行。

复跑命令见 [项目验证指南](../../../docs/project-scoped-validation.md)。每次使用新输出目录，保留本轮证据。
'''
    markdown.write_text(text,encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['status','javaTests','fieldInventory','valuesChecked','formalStatus']}))


if __name__=='__main__':main()
