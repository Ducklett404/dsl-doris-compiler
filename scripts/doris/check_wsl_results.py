"""Execute unmodified compiler SQL on real isolated Doris, without acceptance registration."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import bind_sql, compile_case
from run_function_smoke import CASES


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/route-implementation/2026-10-04')
    parser.add_argument('--reference-results',type=Path,default=ROOT/'target/data-audit/reference-results-v1.0.1.json')
    parser.add_argument('--manifest',type=Path)
    args=parser.parse_args()
    folder=args.report_dir;folder.mkdir(parents=True,exist_ok=True)
    local=json.loads((folder/'本地真实数据结果对比.json').read_text(encoding='utf-8'))
    references=json.loads(args.reference_results.read_text(encoding='utf-8'))
    manifest_path=args.manifest or Path(local['manifestPath'])
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest['snapshotId']!=local['snapshotId'] or references['snapshotId']!=local['snapshotId']
        or hashlib.sha256(manifest_path.read_bytes()).hexdigest()!=local['manifestSha256']
        or references['manifestSha256']!=local['manifestSha256']
        or references['goldenSha256']!=local['goldenSha256']):
        raise ValueError('Reference, compiler SQL and manifest provenance do not match')
    digest=hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest()
    if digest!=local['jarSha256'] or digest!=references['jarSha256']:
        raise ValueError('Compiler artifact changed since reference calculation')
    command=['wsl.exe','-d',args.distribution,'--exec','docker','exec','-i','dsl-doris-official',
        'mysql','--defaults-extra-file=/run/dsl-client.cnf','--batch','--skip-column-names','--raw']

    def query(sql):
        completed=subprocess.run(command,input=sql.rstrip(';\n')+';\n',text=True,
            encoding='utf-8',errors='replace',capture_output=True,timeout=300)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip())
        return [line.split('\t') for line in completed.stdout.splitlines() if line]

    output={'engine':'Apache Doris','purpose':'DIAGNOSTIC_ONLY',
        'sourceAuditStatus':local['sourceAuditStatus'],'goldenVersion':local['goldenVersion'],
        'manifestSha256':local['manifestSha256'],'goldenSha256':local['goldenSha256'],
        'snapshotId':local['snapshotId'],'jarSha256':digest,'results':[]}
    try:
        output['mysqlCompatibilityVersion']=query('SELECT VERSION()')[0][0]
        output['version']=query("SHOW VARIABLES LIKE 'version_comment'")[0][1]
        output['loadedRows']=query("SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info UNION ALL SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext")
        expected_counts={short:manifest['files'][table]['rows'] for short,table in (
            ('code','hsj_stock_code_info'),('basic','hsj_stock_hq_basic'),('ext','hsj_stock_hq_ext'))}
        if {name:int(count) for name,count in output['loadedRows']}!=expected_counts:
            raise ValueError('Loaded Doris row counts do not match the frozen input')
        output['registeredSnapshots']=int(query('SELECT COUNT(*) FROM newzl.data_snapshot_registry')[0][0])
        if output['registeredSnapshots']!=0:
            raise ValueError('This diagnostic instance must have no registered snapshot')
        output['extensionWithoutBasicByYear']=[]
        for year in range(int(manifest['files']['hsj_stock_hq_ext']['dateMin'][:4]),int(manifest['files']['hsj_stock_hq_ext']['dateMax'][:4])+1):
            start=f'{year}-01-01';end=f'{year+1}-01-01'
            count=int(query(f"SELECT COUNT(*) FROM newzl.hsj_stock_hq_ext e LEFT JOIN newzl.hsj_stock_hq_basic b ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate AND b.bizdate>='{start}' AND b.bizdate<'{end}' WHERE e.bizdate>='{start}' AND e.bizdate<'{end}' AND b.tgtcode IS NULL")[0][0])
            output['extensionWithoutBasicByYear'].append({'year':year,'rows':count})
        output['extensionWithoutBasic']=sum(row['rows'] for row in output['extensionWithoutBasicByYear'])
        print('Doris source relationship failures: '+str(output['extensionWithoutBasic']),flush=True)
        for case in local['results']:
            start=time.monotonic();record={'id':case['id']}
            try:
                actual=[(int(market),code) for market,code in query(bind_sql(case['sql'],case['bindings']))]
                expected=[tuple(row) for row in references['results'][case['id']]]
                # Orderedness comes from the generated top-level SQL, not row sets.
                ordered=case['ordered']
                equal=actual==expected if ordered else set(actual)==set(expected)
                structure=case['structureEqual']
                record.update(status='PASS' if equal and structure else 'FAIL',resultEqual=equal,structureEqual=structure,rows=len(actual),referenceRows=len(expected),
                    onlyGenerated=sorted(set(actual)-set(expected))[:20],onlyReference=sorted(set(expected)-set(actual))[:20])
            except Exception as error:record.update(status='ERROR',error=str(error))
            record['elapsedSeconds']=round(time.monotonic()-start,3);output['results'].append(record)
            print(f"[Doris {record['id']}] {record['status']} ({record['elapsedSeconds']}s)",flush=True)
        output['passed']=sum(r['status']=='PASS' for r in output['results'])
        output['total']=len(output['results'])
        output['functionSmoke']={'results':[]}
        with tempfile.TemporaryDirectory(prefix='wsl-doris-functions-') as directory:
            for name,dsl in CASES.items():
                record={'name':name,'dsl':dsl}
                try:
                    artifact=compile_case('java',ROOT/'target/dsl-doris-compiler.jar',dsl.replace('2026-04-14',local['evaluationDate']),Path(directory)/'case.dsl',local['snapshotId'])
                    rows=query(bind_sql(artifact['sql'],artifact['bindings']))
                    record.update(status='PASS',rows=len(rows))
                except Exception as error:record.update(status='ERROR',error=str(error))
                output['functionSmoke']['results'].append(record)
                print(f"[Doris function {name}] {record['status']}",flush=True)
        output['functionSmoke']['total']=len(CASES)
        output['functionSmoke']['passed']=sum(row['status']=='PASS' for row in output['functionSmoke']['results'])
        output['explain']={}
        for case in local['results']:
            if case['id'] in ('PY-MA60','PY-RSI14','PY-NET_SUM5'):
                try:
                    plan=query('EXPLAIN '+bind_sql(case['sql'],case['bindings']))
                    (folder/f"Doris-EXPLAIN-{case['id']}.txt").write_text('\n'.join('\t'.join(row) for row in plan)+'\n',encoding='utf-8')
                    output['explain'][case['id']]='PASS'
                except Exception as error:output['explain'][case['id']]=str(error)
    except Exception as error:
        output['fatalError']=str(error)
        raise
    finally:
        (folder/'Doris真实数据诊断结果.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if (len(local['results'])>0 and output['passed']==len(local['results']) and output['total']==len(local['results'])
        and output['functionSmoke']['passed']==len(CASES)
        and all(status=='PASS' for status in output['explain'].values())) else 1


if __name__=='__main__':raise SystemExit(main())
