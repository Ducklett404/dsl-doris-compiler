"""Generated SQL versus an independent raw-row oracle, including combined diagnostics."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import random
import subprocess
import tempfile
import duckdb
from validate_project_sources import ROOT, digest
from project_matrix_reference import reference, assess
from check_project_window_performance import cases


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--java',default='D:/Java/jdk-21/bin/java.exe');args=p.parse_args()
    if args.output.exists():raise ValueError('Preserve prior evidence')
    rng=random.Random(20261005);rows=[];ext=[];histories={}
    for index in range(65):
        market=[0,1,103][index%3];code=f'{index+1:06}';length=[1,2,3,4,5,6,20,25,39,40,45][index%11]
        prices=[10000*rng.randint(0,20) for _ in range(length)]
        if index%7==0:prices=[20000]*length
        if index%5==0:prices[length//2]=None
        if index%9==0:prices[-1]=None
        history=[]
        for i,price in enumerate(prices):
            day=str(date(2026,4,14)-timedelta(days=(length-i-1)*41)) # Suspensions, not calendar windows.
            opening=None if i%17==3 else 10000*rng.randint(0,20)
            has_ext=not(index%4==0 and i==length-1);net=-999999 if index%6==0 else None if index%13==0 else index-30
            history.append(dict(date=day,close=price,open=opening,volume=100,ext=has_ext,net=None if not has_ext or net==-999999 else net))
            rows.append((market,code,day,None if price is None else price/10000,None if opening is None else opening/10000,100))
            if has_ext:ext.append((market,code,day,net))
        if index%11!=10:histories[(str(market),code)]=history
        else:
            rows[-1]=(*rows[-1][:2],'2026-04-13',*rows[-1][3:]) # Missing evaluation-date row.
        rows.append((market,code,'2026-04-15',999999,999999,999999)) # Future data cannot affect results.
    suite=[c for c in cases() if c['date']=='2026-04-14']
    # Fully available inputs and zero observations test diagnostic result cardinality.
    suite += [dict(name='all-complete',dsl="indicator('', '', '成交量', '2026-04-14', '', '', '')>0",market='',calls=[dict(kind='field',metric='volume')],expr=('cmp',0,'>',0),date='2026-04-14'),
              dict(name='no-observations',dsl="indicator('', '', 'RSI(5)', '2000-01-01', '', '', '')>0",market='',calls=[dict(kind='rsi',n=5)],expr=('cmp',0,'>',0),date='2000-01-01')]
    # Manually labelled dependency boundary: both operands of counted comparisons need history.
    cross = "indicator('', '', 'RSI(2)', '2026-04-14', '', '', 'CONS=2日') > indicator('', '', '3日均线', '2026-04-14', '', '', '')"
    hand=[dict(name='counted-two-operands',dsl=cross)]
    report=dict(purpose='PROJECT_WINDOW_BOUNDARIES',officialAcceptanceEligible=False,seed=20261005,
        jarSha256=digest(ROOT/'target/dsl-doris-compiler.jar'),oracleSha256=digest(ROOT/'scripts/doris/project_matrix_reference.py'),checks=[],fixtureRows=rows,extensionRows=ext)
    try:
        with tempfile.TemporaryDirectory(prefix='mixed-boundaries-') as temp:
            path=Path(temp)/'queries.json';path.write_text(json.dumps([c['dsl'] for c in suite+hand]),encoding='utf-8')
            result=subprocess.run([args.java,'-Dfile.encoding=UTF-8','-Dsun.stdout.encoding=UTF-8','-Dsun.stderr.encoding=UTF-8','-cp',str(ROOT/'target/dsl-doris-compiler.jar'),str(ROOT/'scripts/doris/ProjectWindowCompile.java'),str(path)],capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=50,check=True)
            artifacts=json.loads(result.stdout)
        con=duckdb.connect();con.execute('CREATE SCHEMA newzl')
        con.execute('CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR,bizdate DATE,closePrice DOUBLE,openPrice DOUBLE,volume BIGINT,closePricePosition DECIMAL(36,4))')
        con.execute('CREATE TABLE newzl.v_hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT)')
        con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?,?,?,?)',[r+(r[3],) for r in rows])
        con.executemany('INSERT INTO newzl.v_hsj_stock_hq_ext VALUES(?,?,?,?)',ext)
        def query(sql,bindings):return [list(r) for r in con.execute(sql.replace('`','"').replace('DATE_FORMAT(', 'STRFTIME('),bindings).fetchall()]
        for case, paths in zip(suite,artifacts):
            expected=reference(case,dict(histories=histories if case['date']=='2026-04-14' else {},names={}))
            results=[]
            for mode,artifact in paths.items():
                keys=[[str(v) for v in r] for r in query(artifact['sql'],artifact['bindings'])]
                plan=artifact['coveragePlan'];counts=query(plan['sql'],plan['bindings'])[0];samples=query(plan['samplesSql'],plan['bindings'])
                combined=query(plan['combinedSql'],plan['bindings']);width=len(counts)
                combined_samples=[r[width:] for r in combined if any(v==1 for v in r[width+2:])]
                flags_equal=combined_samples==samples and all(r[:width]==counts for r in combined) and 1<=len(combined)<=20
                quality=dict(validationLevel='PROJECT_SCOPED',officialAcceptanceEligible=False,observedSecurities=counts[0],currentMissingExtensionRows=counts[1],
                    coverageStatus='NO_OBSERVATIONS' if counts[0]==0 else 'PARTIAL_INPUTS' if any(counts[1:]) else 'COMPLETE_QUERY_INPUTS',
                    inputs=[dict(function=i['function'],indicator=i['indicator'],unavailableSecurities=n) for i,n in zip(plan['inputs'],counts[2:])],
                    unavailableSamples=[[str(v) for v in r] for r in combined_samples])
                checks=assess(dict(rows=keys,truncated=False,dataQuality=quality),expected);checks['combinedEqual']=flags_equal
                report['checks'].append(dict(name=case['name'],mode=mode,status='PASS' if all(checks.values()) else 'FAIL',checks=checks,
                    rows=keys,counts=counts,samples=combined_samples,diagnosticReturnedRows=len(combined)))
                if not all(checks.values()):raise AssertionError(case['name']+' '+mode)
                results.append((keys,counts,samples))
            if results[0]!=results[1]:raise AssertionError('full reference mismatch '+case['name'])
        con.execute('DELETE FROM newzl.v_hsj_stock_hq_basic');con.execute('DELETE FROM newzl.v_hsj_stock_hq_ext')
        # Each of the last two RSI values is positive; the preceding predicate is unknown.
        # Other security has too few prices for the MA operand at the earlier counted row.
        fixture=[(1,'000001',str(date(2026,4,14)-timedelta(days=(4-i)*71)),v,v,100,v) for i,v in enumerate([None,3,1,2,1])]
        fixture += [(1,'000002',str(date(2026,4,14)-timedelta(days=(2-i)*71)),v,v,100,v) for i,v in enumerate([3,1,2])]
        con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?,?,?,?)',fixture)
        outputs=[]
        for mode,artifact in artifacts[-1].items():
            keys=[[str(v) for v in r] for r in query(artifact['sql'],artifact['bindings'])]
            plan=artifact['coveragePlan'];counts=query(plan['sql'],plan['bindings'])[0];samples=query(plan['samplesSql'],plan['bindings'])
            combined=query(plan['combinedSql'],plan['bindings']);width=len(counts)
            ok=keys==[['1','000001']] and counts[:2]==[2,0] and sorted(counts[2:])==[0,0,0,2]
            ok &= all(r[:width]==counts for r in combined) and [r[width:] for r in combined if any(v==1 for v in r[width+2:])]==samples
            report['checks'].append(dict(name='counted-two-operands',mode=mode,status='PASS' if ok else 'FAIL',rows=keys,counts=counts,samples=samples))
            if not ok:raise AssertionError('hand-labelled counted operands '+mode)
            outputs.append((keys,counts,samples))
        if outputs[0]!=outputs[1]:raise AssertionError('hand-labelled reference mismatch')
        con.close()
    except Exception as error:report['fatalError']=str(error);raise
    finally:
        report.update(status='FAIL' if 'fatalError' in report else 'PASS',passed=sum(c['status']=='PASS' for c in report['checks']),total=len(report['checks']))
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','passed','total']}))


if __name__=='__main__':main()
