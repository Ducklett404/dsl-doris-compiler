"""One-command, auditable official-data diagnostic route; never registers failed sources."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris


def digest(path):
    sha=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):sha.update(chunk)
    return sha.hexdigest()


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--resume',action='store_true',help='Resume completed phases only after validating their final JAR and artifact hashes')
    args=parser.parse_args();folder=args.report_dir.resolve();folder.mkdir(parents=True,exist_ok=True)
    if not args.resume and any((folder/n).exists() for n in ('route-status.json','final-selftest','rolling-build','hot-30')):
        raise ValueError('Use a fresh report directory to preserve all evidence')
    phases=[];attempts=[]
    if args.resume:
        old=read(folder/'route-status.json');attempt=folder/f'route-attempt-{len(list(folder.glob("route-attempt-*.json")))+1:03}.json'
        shutil.copyfile(folder/'route-status.json',attempt);attempts=old.get('priorAttemptReports',[])+[attempt.name]
        completed={p['phase']:p for p in old['phases'] if p['status'] in ('PASS','EXPECTED_BLOCKED')}
        jar=digest(ROOT/'target/dsl-doris-compiler.jar')
        for name,p in completed.items():
            if name=='full-selftest':
                proof=read(folder/'final-selftest/integration-result.json')
                if proof['status']!='PASS' or proof['compilerJarSha256']!=jar:raise ValueError('Cannot resume with changed JAR or incomplete self-test')
            elif name in ('rolling-build','history-build'):
                proof=read(folder/name/'build-report.json');catalog=folder/name/'catalog.json'
                if proof['status']!='PASS' or proof['jarSha256']!=jar or digest(catalog)!=proof.get('catalogSha256',proof.get('publishedCatalogSha256')):
                    raise ValueError('Cannot reuse changed or incomplete feature build')
            elif name=='hot-performance':
                proof=read(folder/'hot-30/diagnostic-summary.json')
                if proof['hashes']['compilerJar']!=jar or proof['exitCode']!=0:raise ValueError('Cannot reuse incomplete performance evidence')
        phases.extend(completed.values())
    report={'purpose':'OFFICIAL_DATA_PROJECT_ROUTE','acceptanceEligible':False,'status':'RUNNING','phases':phases,'priorAttemptReports':attempts}
    def stage(name,arguments,allowed=(0,),timeout=7200):
        if any(p['phase']==name and p['status'] in ('PASS','EXPECTED_BLOCKED') for p in phases):
            print('Reusing verified completed phase '+name,flush=True);return
        print('Starting '+name,flush=True);path=folder/(name+'.log')
        if path.exists():shutil.copyfile(path,folder/f'{name}.attempt-{len(attempts):03}.log')
        with path.open('wb') as log:
            result=subprocess.run([sys.executable,*map(str,arguments)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        phases.append({'phase':name,'exitCode':result.returncode,'status':'PASS' if result.returncode==0 else 'EXPECTED_BLOCKED' if result.returncode in allowed else 'FAIL','log':path.name})
        (folder/'route-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if result.returncode not in allowed:raise RuntimeError(name+' failed; see '+str(path))
        print('Completed '+name,flush=True)
    try:
        manifest_path=ROOT/'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json';manifest=read(manifest_path)
        integrity=[]
        for name,item in manifest['files'].items():
            source=ROOT.parent/item['relativePath'];actual=digest(source)
            if actual!=item['sha256'] or source.stat().st_size!=item['bytes']:raise ValueError('Immutable official CSV changed: '+name)
            integrity.append({'table':name,'sha256':actual,'bytes':source.stat().st_size,'status':'PASS'})
        client=WslDoris(args.distribution,'dsl-doris-official');before=client.query('SELECT * FROM newzl.data_snapshot_registry')
        if before:raise ValueError('Expected the isolated unregistered diagnostic source')
        (folder/'source-integrity.json').write_text(json.dumps(integrity,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        report.update(snapshotId=manifest['snapshotId'],manifestSha256=digest(manifest_path))
        tests=folder/'final-selftest'
        stage('full-selftest',['scripts/doris/run_wsl_integration.py','--distribution',args.distribution,'--report-dir',tests])
        for source,name in [('reports/automation/latest.json','automation.json'),('reports/compiler-performance/latest.json','compiler-performance.json'),
            ('reports/history-features/2026-10-04/portable-historical-boundaries.json','portable-historical-boundaries.json'),
            ('reports/official-route/2026-10-04/portable-rolling-boundaries.json','portable-rolling-boundaries.json')]:shutil.copyfile(ROOT/source,tests/name)
        for source,name in [('target/surefire-reports','junit-main'),('executor-doris/target/surefire-reports','junit-executor')]:
            if not (tests/name).exists():shutil.copytree(ROOT/source,tests/name)
        stage('rolling-build',['scripts/doris/build_rolling_features.py','--distribution',args.distribution,'--output-dir',folder/'rolling-build'])
        stage('history-build',['scripts/doris/build_history_features.py','--distribution',args.distribution,'--output-dir',folder/'history-build'])
        stage('rolling-independent',['scripts/doris/check_real_rolling_features.py','--distribution',args.distribution,
            '--catalog',folder/'rolling-build/catalog.json','--output',folder/'independent-rolling.json'])
        stage('rolling-native-boundaries',['scripts/accuracy/check_rolling_averages.py','--wsl','--distribution',args.distribution,'--output-dir',tests])
        stage('history-native-boundaries',['scripts/accuracy/check_historical_extrema.py','--wsl','--distribution',args.distribution,'--output-dir',tests])
        stage('local-real-results',['scripts/doris/check_local_results.py','--report-dir',tests,'--reference-output',tests/'reference-results.json'])
        stage('native-real-results',['scripts/doris/check_wsl_results.py','--distribution',args.distribution,'--report-dir',tests,'--reference-results',tests/'reference-results.json'])
        stage('official-execution-gate',['scripts/doris/check_wsl_execution_gate.py','--distribution',args.distribution,'--report-dir',tests])
        stage('formal-correctness-gate',['scripts/accuracy/run_correctness.py','--wsl-distribution',args.distribution,'--container','dsl-doris-official','--output-dir',tests/'formal-gate'],allowed=(0,3))
        matrix=read(ROOT/'benchmarks/doris-matrix-v1.json');matrix['matrixVersion']='official-route-multi-date-v1'
        independent=read(folder/'independent-rolling.json')
        for date in read(folder/'rolling-build/catalog.json')['completeDates']:
            for n in (20,60,120,250):
                matrix['cases'].append({'id':f'ma{n}-{date}-all','category':'MULTI_DATE_WINDOW',
                    'dsl':f"indicator('', '', '{n}日均线', '{date}', '', '', '') > 10"})
        for function,metric in [('high','最高价'),('low','最低价')]:
            matrix['cases'].append({'id':f'record-{function}-2026-04-14-all','category':'STRICT_RANGE',
                'dsl':f"record_{function}('', '', '{metric}', '250日', '2026-04-14', '', '', '') = True"})
        matrix['cases'].append({'id':'mixed-moving-averages','category':'MULTI_WINDOW',
            'dsl':"indicator('', '', '20日均线', '2026-04-14', '', '', '') > indicator('', '', '250日均线', '2026-04-14', '', '', '')"})
        matrix['cases'].append({'id':'mixed-ma60-close-fallback','category':'REFERENCE_FALLBACK',
            'dsl':"indicator('', '', '60日均线', '2026-04-14', '', '', '') > indicator('', '', '收盘价', '2026-04-14', '', '', '')"})
        matrix_path=folder/'matrix.json';matrix_path.write_text(json.dumps(matrix,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        stage('hot-performance',['scripts/doris/diagnose_performance.py','--distribution',args.distribution,'--matrix',matrix_path,
            '--historical-features',folder/'history-build/catalog.json','--rolling-features',folder/'rolling-build/catalog.json',
            '--iterations','30','--report-dir',folder/'hot-30'])
        stage('performance-evidence',['scripts/doris/summarize_performance.py',folder/'hot-30'])
        stage('evidence-selftest',['scripts/doris/test_performance_evidence.py',folder/'hot-30'])
        stage('restart-persistence',['scripts/doris/check_route_restart.py','--distribution',args.distribution,
            '--catalogs',folder/'rolling-build/catalog.json',folder/'history-build/catalog.json','--output',folder/'restart-persistence.json'])
        jar=digest(ROOT/'target/dsl-doris-compiler.jar');measure=read(folder/'hot-30/diagnostic-summary.json')
        if measure['hashes']['compilerJar']!=jar:raise ValueError('Final JAR changed')
        for case in measure['measurements']['results']:
            if case['id'] in independent['queryExpectations']:
                actual=read(folder/'hot-30'/case['id']/'result-rows.json')
                expected=[[str(m),code] for m,code in independent['queryExpectations'][case['id']]]
                if actual!=expected:raise ValueError('Query differs from independent decimal expectation: '+case['id'])
        if client.query('SELECT * FROM newzl.data_snapshot_registry')!=before:raise ValueError('Original source gate changed')
        report.update(status='DIAGNOSTIC_PASS_FORMAL_BLOCKED',jarSha256=jar,formalAcceptanceStatus='BLOCKED',
            diagnosticCases=measure['measurements']['total'],timedQueries=sum(len(c['samples'])*2 for c in measure['measurements']['results']),
            independentValuesChecked=independent['totalNumericValuesChecked'],officialRegistryUnchanged=True)
        report['junit']={name:{key:sum(int(ET.parse(p).getroot().get(key,'0')) for p in (tests/name).glob('TEST-*.xml'))
            for key in ('tests','failures','errors','skipped')} for name in ('junit-main','junit-executor')}
        if any(v['tests']==0 or any(v[k] for k in ('failures','errors','skipped')) for v in report['junit'].values()):raise ValueError('Incomplete Java checks')
    except Exception as error:report.update(status='FAIL',error=str(error));raise
    finally:
        report['completedAtUtc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (folder/'route-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    subprocess.run([sys.executable,str(ROOT/'scripts/doris/summarize_official_route.py'),str(folder)],cwd=ROOT,check=True)
    print('Project diagnostic route complete; official source acceptance remains BLOCKED.',flush=True)


if __name__=='__main__':main()
