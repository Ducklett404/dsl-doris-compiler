"""Report nearest-rank timings without treating absent real measurements as PASS."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import subprocess

from run_project_acceptance import ROOT, digest, read, verify_report


def stats(values):
    if not values or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in values):
        raise ValueError('Timing samples must be nonempty, finite and nonnegative')
    values=sorted(values)
    return dict(samples=len(values),p50=values[math.ceil(len(values)*.5)-1],
                p95=values[math.ceil(len(values)*.95)-1],max=values[-1])


def summarize(folder,minimum_rounds=30):
    folder=Path(folder);run=read(folder/'result.json');verify_report(run)
    matrix=read(folder/'matrix.json');names=[c['name'] for c in matrix]
    if not names or len(names)!=len(set(names)) or run.get('matrixScope')!='FULL_MATRIX' or set(run.get('originalCaseNames',[]))!=set(names):
        raise ValueError('A complete matrix measurement is required; a subset is diagnostic only')
    expected=read(folder/'expected.json')
    if set(expected)!=set(names):raise ValueError('Expected results do not cover the entire matrix')
    if not isinstance(run.get('rounds'),int) or run['rounds']<minimum_rounds:raise ValueError('Insufficient full-matrix rounds')
    grouped=defaultdict(list)
    for execution in run['executions']:
        if execution.get('phase','timed')!='timed':continue
        grouped[execution['case']].append(execution)
    if set(grouped)!=set(names):raise ValueError('Measured cases do not cover the entire matrix')
    result=[]
    for name,executions in grouped.items():
        rounds=[e['round'] for e in executions]
        if sorted(rounds)!=list(range(1,run['rounds']+1)):
            raise ValueError('Each matrix case requires at least '+str(minimum_rounds)+' independent rounds: '+name)
        for execution in executions:
            path=(folder/execution['artifact']).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file():raise ValueError('Unsafe/missing execution artifact')
            data=read(path)
            if data.get('truncated') is not False or data.get('rows')!=expected[name]['rows']:
                raise ValueError('Recorded full results changed: '+name)
            if data.get('timings')!=execution['timings'] or data.get('dataQuality',{}).get('diagnosticTimings')!=execution.get('diagnosticTimings'):
                raise ValueError('Timing evidence does not match actual execution: '+name)
            if data.get('dataQuality',{}).get('certificateSha256')!=run['certificateSha256']:
                raise ValueError('Recorded source certificate changed')
            limits=data.get('limits',{})
            if (limits.get('queryTimeoutSeconds'),limits.get('maxExecutionMemoryBytes'),limits.get('maxEstimatedScanRows'),limits.get('maxReturnRows'))!=(10,2147483648,100000000,10000):
                raise ValueError('Query resource limits changed')
        row=dict(case=name,mainSql=stats([e['timings']['dorisExecutionMillis'] for e in executions]),
                 endToEnd=stats([e['timings']['totalMillis'] for e in executions]),wall=stats([e['wallMillis'] for e in executions]))
        for stage in ('sourceValidationMillis','mainExplainMillis','availabilityExplainMillis','missingStatisticsMillis','sampleDetailsMillis'):
            row[stage]=stats([e['diagnosticTimings'][stage] for e in executions])
        row['profilesAvailable']=sum(bool(e.get('queryProfile',{}).get('available')) for e in executions)
        # A configured budget is not actual peak query memory.
        row['queryPeakMemoryStatus']='NOT_AVAILABLE_IN_SUMMARY'
        result.append(row)
    return dict(status='PASS',purpose='PROJECT_HOT_PROCESS_DIAGNOSTIC',officialAcceptanceEligible=False,
                cacheState='Doris SQL cache disabled; no OS page-cache clearing. Includes first-request effects.',
                minimumRounds=minimum_rounds,cases=result,jarSha256=run['jarSha256'],
                certificateSha256=run['certificateSha256'],executionSha256=digest(folder/'result.json'))


def verify_compiler(data):
    pipeline=data['uncachedPipeline']
    for name,value,minimum in [('iterations',pipeline['iterations'],5000),('warmup',data['warmupIterations'],1000)]:
        if not isinstance(value,int) or isinstance(value,bool) or value<minimum:raise ValueError('Insufficient compiler '+name)
    if set(pipeline['stages'])!={'parse','semantic','rewrite','planning','sqlGeneration','total'}:
        raise ValueError('Missing compiler pipeline stage')
    for stage in pipeline['stages'].values():
        if set(stage)!={'p50','p95','p99','max'}:raise ValueError('Missing compiler percentile')
        values=[stage[k] for k in ('p50','p95','p99','max')]
        stats(values)
        if values!=sorted(values):raise ValueError('Invalid compiler percentile ordering')
    p95=pipeline['stages']['total']['p95']
    if p95>=50:raise ValueError('Compiler performance failed: P95 must be <50ms')
    return p95


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--compiler',action='store_true');p.add_argument('--java',default='java')
    p.add_argument('--execution-dir',type=Path);args=p.parse_args()
    if args.compiler == bool(args.execution_dir):p.error('Choose exactly one of --compiler or --execution-dir')
    folder=args.output_dir.resolve()
    if (folder/'result.json').exists():raise ValueError('Preserve previous measurement')
    folder.mkdir(parents=True,exist_ok=True)
    if args.compiler:
        proof=folder/'compiler-performance.json'
        command=[args.java,'-jar',str(ROOT/'target/dsl-doris-compiler.jar'),'benchmark-stock-slot-compiler',
                 '--corpus',str(ROOT/'benchmarks/compiler/stock-slot-complex-v1.json'),'--warmup','1000',
                 '--iterations','5000','--p95-threshold-ms','50','--json-output',str(proof),
                 '--markdown-output',str(folder/'compiler-performance.md')]
        subprocess.run(command,cwd=ROOT,check=True,timeout=120)
        data=read(proof);pipeline=data['uncachedPipeline']
        p95=verify_compiler(data)
        result=dict(status='PASS',purpose='LOCAL_COMPLEX_COMPILER_PERFORMANCE',officialAcceptanceEligible=False,
                    compilerJarSha256=digest(ROOT/'target/dsl-doris-compiler.jar'),performanceSha256=digest(proof),
                    iterations=pipeline['iterations'],p95Millis=p95,memoryAllocation=data.get('allocatedBytes',pipeline.get('allocatedBytes')))
    elif args.execution_dir:result=summarize(args.execution_dir)
    else:p.error('Choose --compiler or --execution-dir')
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
