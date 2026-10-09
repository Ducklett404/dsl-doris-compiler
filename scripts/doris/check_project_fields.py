"""19-field independent values, controlled execution explanations and portable SQL fixtures."""
import argparse
from datetime import date,timedelta
from decimal import Decimal
import json
import secrets
from pathlib import Path
import duckdb
from validate_project_sources import ROOT,WslDoris,digest
from project_field_reference import KEYS,OPERANDS,observation,load,cases,configure_reference_connection
from check_official_field_acceptance import FIELDS,RAW_COLUMNS,raw_values,compare_values
from project_matrix_reference import reference,assess
from check_project_availability import probe,verify
from project_portable_decimal import install_semantic_views,adapt_compiler_sql


def portable(suite,java,native=None,adapter_evidence=None):
    source_rows=[];extension_rows=[];histories={}
    # Hand fixtures: sparse dates, legal negatives, sentinel, missing ext, zero divisors,
    # every raw NULL operand, nontrivial adjustment and all 19 scales.
    for index in range(42):
        market=[0,1,103][index%3];code=f'{index+1:06}'
        size=[1,2,3,4,20,25][index%6];history=[]
        days=['2006-01-04','2018-08-20']+[str(date(2026,4,14)-timedelta(days=41*(size-i-1))) for i in range(size)]
        for i,day in enumerate(days):
            price=20000 if index%7==0 else (index*3+i*7)%13*10000
            raw={k:10000 for k in RAW_COLUMNS}
            raw.update(lastPx=price,preClosePx=10000,openPx=price,highPx=price+20000,
                lowPx=price-10000,closePx=price,volume=100,turnover=price*100,
                totalShare=123456,listedShare=65432,qfqMulti=2,qfqAdd=3,hfqMulti=3,hfqAdd=-2)
            if index%5==0:raw['volume']=0
            if index%6==0:raw['preClosePx']=0
            if index<len(RAW_COLUMNS) and i==len(days)-1:raw[RAW_COLUMNS[index]]=None
            if index==20:raw.update(turnover=None,volume=0,lastPx=None,preClosePx=0)
            ext=not(index%8==0 and i==len(days)-1)
            raw['net']=-999999 if index%9==0 else None if index%11==0 else index-25
            if not ext:raw['net']=None
            history.append(observation(day,raw,ext))
            source_rows.append((market,code,day,*(raw[k] for k in RAW_COLUMNS)))
            if ext:extension_rows.append((market,code,day,raw['net']))
        histories[(str(market),code)]=history
        source_rows.append((market,code,'2026-04-15',*([999999]*len(RAW_COLUMNS))))
    with duckdb.connect() as con:
        con.execute('CREATE SCHEMA newzl')
        types=','.join(k+' '+('DOUBLE' if k in ['qfqMulti','qfqAdd','hfqMulti','hfqAdd'] else 'BIGINT') for k in RAW_COLUMNS)
        con.execute('CREATE TABLE newzl.hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR,bizdate DATE,'+types+')')
        con.execute('CREATE TABLE newzl.hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT,'+
            ','.join(k+' BIGINT' for k in ['ZJLXMainNetTurInDays','ZJLXMainNetTurOutDays','ZJLXMainNetTurInSeries','ZJLXMainNetTurOutSeries','pxMkTopDays','mainTurMkTopDays'])+')')
        con.executemany('INSERT INTO newzl.hsj_stock_hq_basic VALUES('+','.join('?' for _ in range(3+len(RAW_COLUMNS)))+')',source_rows)
        con.executemany('INSERT INTO newzl.hsj_stock_hq_ext(mktcode,tgtcode,bizdate,ZJLXMainNetTur) VALUES(?,?,?,?)',extension_rows)
        ddl=(ROOT/'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8').replace('USE newzl;','')
        con.execute("SET schema='newzl'")
        if native is None:
            metadata=install_semantic_views(con,ddl)
            if adapter_evidence is not None:adapter_evidence.update(metadata)
        else:
            con.execute(ddl)
        if native is None:
            def query(sql,bindings):return [[str(v) if v is not None else 'NULL' for v in row] for row in con.execute(adapt_compiler_sql(con,sql,adapter_evidence).replace('`','"').replace('DATE_FORMAT(','STRFTIME('),bindings).fetchall()]
        else:
            client,database=native
            from run_correctness import sql_literal,bind_sql
            client.query((ROOT/'data/doris/ddl/001_rebuild_tables.sql').read_text(encoding='utf-8').replace('newzl',database).replace('BUCKETS 16','BUCKETS 1'))
            client.query((ROOT/'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8').replace('USE newzl;','USE '+database+';'))
            def insert(table,columns,rows):
                for start in range(0,len(rows),100):
                    client.query('INSERT INTO '+database+'.'+table+' ('+','.join(columns)+') VALUES '+','.join('('+','.join(sql_literal(v) for v in row)+')' for row in rows[start:start+100]))
            insert('hsj_stock_hq_basic',['mktcode','tgtcode','bizdate',*RAW_COLUMNS],source_rows)
            insert('hsj_stock_hq_ext',['mktcode','tgtcode','bizdate','ZJLXMainNetTur'],extension_rows)
            def query(sql,bindings):return [list(r) for r in client.query(bind_sql(sql,bindings).replace('newzl.',database+'.'))]
        plans=probe([dict(dsl=c['dsl'],samples=[]) for c in suite],java);requests=[];expected=[];rows=[]
        for case,plan in zip(suite,plans):
            day=case['date'];source=dict(histories={k:[r for r in h if r['date']<=day] for k,h in histories.items() if any(r['date']==day for r in h)},names={})
            e=reference(case,source);expected.append(source)
            rows.append(query(plan['sql'],plan['bindings']))
            coverage=plan['coverage'];combined=query(coverage['combinedSql'],coverage['bindings']);width=len(coverage['inputs'])+2
            samples=[r[width:] for r in combined if '1' in r[width+2:]]
            quality=dict(inputs=[dict(i,unavailableSecurities=int(combined[0][j+2])) for j,i in enumerate(coverage['inputs'])],
                observedSecurities=int(combined[0][0]),currentMissingExtensionRows=int(combined[0][1]),
                unavailableSamples=samples,coverageStatus=e['coverageStatus'],validationLevel='PROJECT_SCOPED',officialAcceptanceEligible=False)
            checks=assess(dict(rows=rows[-1],truncated=False,dataQuality=quality),e)
            if not all(checks.values()):raise AssertionError('Portable results/coverage: '+case['name']+' '+str(checks))
            requests.append(dict(dsl=case['dsl'],samples=samples))
        fetches=probe(requests,java)
        for request,fetch in zip(requests,fetches):
            if request['samples']:request['rawRows']=query(fetch['fetch']['sql'],fetch['fetch']['bindings'])
        explained=probe(requests,java);result=[]
        for case,request,output,source,keys in zip(suite,requests,explained,expected,rows):
            quality=dict(inputs=output['coverage']['inputs'],sampleDetails=output['details'],unavailableSamples=request['samples'])
            checks=verify(quality,case,source['histories'])
            result.append(dict(name=case['name'],status='PASS',checks=checks,rows=keys,samples=len(request['samples']),details=output['details']))
        return result


def values_native(client,con):
    result=[]
    for day in ['2006-01-04','2018-08-20','2026-04-10','2026-04-13','2026-04-14']:
        raw=con.execute('SELECT b.mktcode,b.tgtcode,'+','.join('b.'+k for k in RAW_COLUMNS)+',e.ZJLXMainNetTur FROM newzl.hsj_stock_hq_basic b LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) WHERE bizdate=CAST(? AS DATE)',[day]).fetchall()
        expected={(int(m),code):raw_values(dict(zip([*RAW_COLUMNS,'net'],v))) for m,code,*v in raw}
        if len(expected)!=len(raw):raise AssertionError('Duplicate raw source keys')
        actual=client.query('SELECT b.mktcode,b.tgtcode,'+','.join(f[1] for f in FIELDS)+" FROM newzl.v_hsj_stock_hq_basic b LEFT JOIN newzl.v_hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) WHERE bizdate='"+day+"'")
        compared=compare_values(expected,actual)
        compared.update(date=day,perField=[dict(name=name,nulls=sum(v[i] is None for v in expected.values()),nonNull=sum(v[i] is not None for v in expected.values())) for i,(name,_,_) in enumerate(FIELDS)])
        result.append(compared)
        print('19-field raw values '+day+' '+compared['status'],flush=True)
        if compared['status']!='PASS':raise AssertionError(str(compared))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--matrix-output',type=Path)
    p.add_argument('--execution-dir',type=Path);p.add_argument('--values-native',action='store_true');p.add_argument('--native-fixture',action='store_true');p.add_argument('--java',default='java')
    p.add_argument('--reference-database',type=Path,default=ROOT/'target/data-audit/acceptance-a0f7260.duckdb')
    p.add_argument('--certificate',type=Path);p.add_argument('--distribution',default='dsl-doris-official-01a104f9');args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh immutable output file')
    suite=cases();report=dict(purpose='PROJECT_19_FIELD_VALIDATION',officialAcceptanceEligible=False,
        definitionAuthority='PROJECT_INTERNAL_OFFICIAL_DICTIONARY_UNAVAILABLE',jarSha256=digest(ROOT/'target/dsl-doris-compiler.jar'),
        oracleSha256=digest(ROOT/'scripts/doris/project_field_reference.py'),valueOracleSha256=digest(ROOT/'scripts/doris/check_official_field_acceptance.py'),runnerSha256=digest(Path(__file__)),checks=[],
        portableDecimalAdapter=dict(used=not(args.native_fixture or args.execution_dir or args.values_native),
            implementationSha256=digest(ROOT/'scripts/doris/project_portable_decimal.py'),
            evidenceType='PORTABLE_DORIS_DECIMAL_EMULATION',notNativeDorisProof=True))
    try:
        registry=json.loads((ROOT/'src/main/resources/stock-slot-registry-v1.json').read_text(encoding='utf-8'))
        if {i['name'] for i in registry['indicators']}!={v[0] for v in FIELDS}:raise AssertionError('Manual field inventory mismatch')
        if args.matrix_output:
            if args.matrix_output.exists():raise ValueError('Preserve matrix evidence')
            args.matrix_output.parent.mkdir(parents=True,exist_ok=True);args.matrix_output.write_text(json.dumps(suite,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if args.native_fixture:
            if args.execution_dir or args.values_native:raise ValueError('Separate native fixture and official data reports')
            client=WslDoris(args.distribution,'dsl-doris-official');database='dsl_fields_'+secrets.token_hex(6)
            before=client.query('SELECT * FROM newzl.data_snapshot_registry');created=False
            try:
                client.query('CREATE DATABASE '+database);created=True
                report.update(purpose='SYNTHETIC_NATIVE_19_FIELD_BOUNDARIES',fixtureDatabase=database)
                report['checks']=portable(suite,args.java,(client,database))
                if client.query('SELECT * FROM newzl.data_snapshot_registry')!=before:raise AssertionError('Official registry changed')
            finally:
                if created:client.query('DROP DATABASE '+database)
                report['fixtureCleanup']='DONE'
        elif args.execution_dir or args.values_native:
            if args.certificate is None:raise ValueError('Certificate required for raw source identity')
            cert=json.loads(args.certificate.read_text(encoding='utf-8'));report['certificateSha256']=digest(args.certificate)
            with duckdb.connect(str(args.reference_database),read_only=True) as con:
                report['referenceResources']=configure_reference_connection(con,args.reference_database)
                if con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone()!=(cert['snapshotId'],cert['manifestSha256'],'FAIL'):raise AssertionError('Raw audit identity')
                if args.values_native:
                    client=WslDoris(args.distribution,'dsl-doris-official')
                    before=client.query("SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info")
                    if client.query('SELECT * FROM newzl.data_snapshot_registry'):raise AssertionError('Formal registry unexpectedly populated')
                    report['values']=values_native(client,con)
                    if client.query("SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info")!=before or client.query('SELECT * FROM newzl.data_snapshot_registry'):raise AssertionError('Sources or formal registry changed')
                    report['sourcesUnchanged']=True
                if args.execution_dir:
                    run=json.loads((args.execution_dir/'result.json').read_text(encoding='utf-8'));matrix=json.loads((args.execution_dir/'matrix.json').read_text(encoding='utf-8'))
                    canonical_suite=json.loads(json.dumps(suite,ensure_ascii=False))
                    if run['status']!='PASS' or run['jarSha256']!=report['jarSha256'] or run['certificateSha256']!=report['certificateSha256'] or matrix!=canonical_suite or len(run['executions'])!=len(suite)*run['rounds'] or any(e['status']!='PASS' for e in run['executions']):raise AssertionError('Execution suite/identity mismatch')
                    lookup={c['name']:c for c in suite}
                    for day in sorted({c['date'] for c in suite}):
                        histories=load(con,day,64)['histories']
                        for execution in run['executions']:
                            case=lookup[execution['case']]
                            if case['date']!=day:continue
                            data=json.loads((args.execution_dir/execution['artifact']).read_text(encoding='utf-8'))
                            checks=verify(data['dataQuality'],case,histories)
                            report['checks'].append(dict(name=case['name'],round=execution['round'],status='PASS',checks=checks,samples=len(data['dataQuality']['unavailableSamples'])))
                        del histories
                    report['executionSha256']=digest(args.execution_dir/'result.json')
        else:report['checks']=portable(suite,args.java,adapter_evidence=report['portableDecimalAdapter'])
        if digest(ROOT/'target/dsl-doris-compiler.jar')!=report['jarSha256']:raise AssertionError('Compiler changed during validation')
    except Exception as error:report['fatalError']=str(error);raise
    finally:
        report.update(status='FAIL' if 'fatalError' in report else 'PASS',passed=sum(c['status']=='PASS' for c in report['checks']),total=len(report['checks']))
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','passed','total']}))


if __name__=='__main__':main()
