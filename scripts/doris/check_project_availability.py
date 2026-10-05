"""Independent reason/date oracle; portable lookup SQL or saved native execution artifacts."""
import argparse
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import tempfile
import duckdb
from validate_project_sources import ROOT, digest
from check_project_window_performance import cases
from project_matrix_reference import METRICS, load, value, render


def explanation_cases():
    suite=cases()
    for name,call,operator,threshold in [
        ('position-volume',dict(kind='position',metric='volume',n=3),'=','高'),
        ('position-net',dict(kind='position',metric='net',n=3),'=','低'),
        ('count-net',dict(kind='count',metric='net',n=3,mode='EXIST',countOp='>=',op='>',threshold=0),'=',True),
        ('close-together',dict(kind='close_together'),'=',True)]:
        expr=('cmp',0,operator,threshold)
        suite.append(dict(name=name,calls=[call],expr=expr,date='2026-04-14',market='',dsl=render(expr,[call],'2026-04-14','')))
    return suite


def requirements(call):
    kind=call['kind'];n=call.get('n',1)
    return n+1 if kind=='rsi' else n if kind in ('ma','position','record_high','record_low') else 2 if kind in ('cross_above','cross_down') else 1


def inputs(case):
    output=[]
    for call in case['calls']:
        base=call.get('base',dict(kind='field',metric=call.get('metric','close'))) if call['kind']=='count' else call
        kind=base['kind'];n=base.get('n',1);metric=METRICS[base.get('metric','close')]
        fn='indicator' if kind in ('field','ma','rsi') else kind
        label=f'{n}日均线' if kind=='ma' else f'RSI({n})' if kind=='rsi' else '收盘价 / 开盘价' if kind.startswith('cross_') or kind=='close_together' else metric
        output.append(dict(function=fn,indicator=label,role='VALUE',requiredObservations=requirements(base),base=base))
        if call['kind']=='count':
            horizon=call['n']+(call['countOp']=='=') if call['mode']=='CONS' else max(20,call['n'])
            for role in ['COUNT_RESULT','COUNT_INPUT']:
                output.append(dict(function=call['mode']+('（窗口输入）' if role=='COUNT_INPUT' else ''),
                    indicator=f'完整 {horizon} 条观察记录的'+('条件输入' if role=='COUNT_INPUT' else '次数条件'),role=role,
                    requiredObservations=horizon if role=='COUNT_RESULT' else horizon+requirements(base)-1,base=base,horizon=horizon))
    # Identical SQL value calls may be shared; identity comparisons below preserve distinct windows.
    return output


def expected_reasons(spec,history):
    evidence={}
    def add(code,metric,required,observed,dates):
        key=(code,metric,required)
        item=evidence.setdefault(key,dict(code=code,indicator=metric,requiredObservations=required,minimumObserved=observed,maximumObserved=observed,dates=set()))
        item['minimumObserved']=min(item['minimumObserved'],observed);item['maximumObserved']=max(item['maximumObserved'],observed);item['dates'].update(dates)
    def evaluate(base,end):
        h=history[:end+1];kind=base['kind'];metric=base.get('metric','close');label=METRICS[metric];required=requirements(base)
        if kind.startswith('cross_') or kind=='close_together':
            if len(h)<required:add('INSUFFICIENT_OBSERVATIONS','收盘价 / 开盘价',required,len(h),[h[-1]['date']])
            for row in h[-required:]:
                for m in ['close','open']:
                    if row[m] is None:add('SOURCE_NULL',METRICS[m],1,1,[row['date']])
            if kind=='close_together' and h[-1]['close']==0 and h[-1]['open']==0:
                add('ZERO_DENOMINATOR','收盘价 / 开盘价',1,1,[h[-1]['date']])
            return value(base,h)
        if len(h)<required:add('INSUFFICIENT_OBSERVATIONS',label,required,len(h),[h[-1]['date']])
        for row in h[-required:]:
            if metric=='net' and not row['ext']:add('EXTENSION_ROW_MISSING',label,1,0,[row['date']])
            elif metric=='net' and row.get('rawNet')==-999999:add('SENTINEL_VALUE',label,1,1,[row['date']])
            elif 'normalized' in row and row['normalized'][metric] is None:
                from project_field_reference import null_causes
                for code,operand in null_causes(row,metric):add(code,operand,1,1,[row['date']])
            elif 'normalized' not in row and row[metric] is None:add('SOURCE_NULL',label,1,1,[row['date']])
        window=h[-required:]
        if len(h)>=required and all((r['normalized'][metric] if 'normalized' in r else r[metric]) is not None for r in window):
            prices=[r['positions'][metric] if kind=='position' and 'positions' in r else Decimal(r['normalized'][metric] if 'normalized' in r else r[metric]) for r in window]
            if kind=='position' and min(prices)==max(prices):add('FLAT_WINDOW',label,required,required,[r['date'] for r in window])
            if kind=='rsi' and all(a<=b for a,b in zip(prices,prices[1:])):
                add('ZERO_LOSS_DENOMINATOR',f"RSI({base['n']})",required,required,[r['date'] for r in window])
        return value(base,h)
    if spec['role'].startswith('COUNT'):
        horizon=spec['horizon']
        if len(history)<horizon:add('INSUFFICIENT_OBSERVATIONS',spec['function'],horizon,len(history),[history[-1]['date']])
        if spec['role']=='COUNT_INPUT':
            for end in range(max(0,len(history)-horizon),len(history)):
                if evaluate(spec['base'],end) is None:add('UNKNOWN_PREDICATE',spec['indicator'],0,0,[history[end]['date']])
    else:evaluate(spec['base'],len(history)-1)
    result=[]
    for item in evidence.values():
        dates=sorted(item.pop('dates'));item.update(relatedDates=dates[:20],totalRelatedDates=len(dates),datesTruncated=len(dates)>20);result.append(item)
    return sorted(result,key=lambda r:(r['code'],r['indicator'],r['requiredObservations']))


def verify(quality,case,histories):
    specs=inputs(case);actual_inputs=quality['inputs'];checks={}
    matched=[]
    for actual in actual_inputs:
        candidates=[s for s in specs if all(s[k]==actual[k] for k in ['function','indicator','role','requiredObservations'])]
        if len(candidates)!=1:raise AssertionError('ambiguous/mismatched input metadata '+str(actual))
        matched.append(candidates[0])
    details=quality['sampleDetails'];samples=quality['unavailableSamples']
    checks['sampleOrder']= [(d['marketCode'],d['securityCode']) for d in details]==[tuple(s[:2]) for s in samples]
    checks['stableIds']=all(len(i['inputId'])==64 for i in actual_inputs) and len({i['inputId'] for i in actual_inputs})==len(actual_inputs)
    for sample,detail in zip(samples,details):
        key=tuple(sample[:2]);history=histories[key]
        checks[str(key)+'-extension']=detail['currentExtensionMissing']==(sample[2]=='1')
        checks[str(key)+'-flags']= [i['inputId'] for i in detail['inputs']]==[i['inputId'] for i,flag in zip(actual_inputs,sample[3:]) if flag=='1']
        issue_map={i['inputId']:i for i in detail['inputs']}
        for input_spec,actual,flag in zip(matched,actual_inputs,sample[3:]):
            if flag!='1':continue
            issue=issue_map[actual['inputId']]
            expected=expected_reasons(input_spec,history)
            observed=sorted(issue['reasons'],key=lambda r:(r['code'],r['indicator'],r['requiredObservations']))
            checks[str(key)+'-'+actual['inputId']]=issue['status']=='EXPLAINED' and observed==expected
            if observed!=expected:raise AssertionError(json.dumps(dict(case=case['name'],security=key,input=actual,expected=expected,observed=observed),ensure_ascii=False))
    if not all(checks.values()):raise AssertionError(str(checks))
    return checks


def probe(requests,java):
    with tempfile.TemporaryDirectory(prefix='availability-probe-') as temp:
        path=Path(temp)/'requests.json';path.write_text(json.dumps(requests,ensure_ascii=False),encoding='utf-8')
        r=subprocess.run([java,'-Dfile.encoding=UTF-8','-Dsun.stdout.encoding=UTF-8','-Dsun.stderr.encoding=UTF-8','-cp',str(ROOT/'target/dsl-doris-compiler.jar'),str(ROOT/'scripts/doris/ProjectAvailabilityProbe.java'),str(path)],capture_output=True,text=True,encoding='utf-8',errors='strict',check=True,timeout=70)
        return json.loads(r.stdout)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--execution-dir',type=Path);p.add_argument('--java',default='D:/Java/jdk-21/bin/java.exe');args=p.parse_args()
    if args.output.exists():raise ValueError('Preserve prior evidence')
    report=dict(purpose='PROJECT_AVAILABILITY_EXPLANATIONS',officialAcceptanceEligible=False,jarSha256=digest(ROOT/'target/dsl-doris-compiler.jar'),runnerSha256=digest(Path(__file__)),checks=[])
    try:
        suite=explanation_cases()
        if args.execution_dir:
            results=json.loads((args.execution_dir/'result.json').read_text(encoding='utf-8'));assert results['status']=='PASS';assert results['jarSha256']==report['jarSha256']
            suite=json.loads((args.execution_dir/'matrix.json').read_text(encoding='utf-8'));lookup={c['name']:c for c in suite}
            with duckdb.connect(str(ROOT/'target/data-audit/acceptance-a0f7260.duckdb'),read_only=True) as con:
                con.execute("SET memory_limit='4GB'");con.execute('SET threads=4')
                for day in sorted({c['date'] for c in suite}):
                    histories=load(con,day,64)['histories']
                    for execution in results['executions']:
                        case=lookup[execution['case']]
                        if case['date']!=day:continue
                        data=json.loads((args.execution_dir/execution['artifact']).read_text(encoding='utf-8'));quality=data['dataQuality']
                        # Check unconverted sentinels directly against raw extension rows.
                        keys=[tuple(s[:2]) for s in quality['unavailableSamples']]
                        if keys:
                            conditions=' OR '.join('(mktcode=? AND tgtcode=?)' for _ in keys)
                            raw=con.execute('SELECT mktcode,tgtcode,bizdate,ZJLXMainNetTur FROM newzl.hsj_stock_hq_ext WHERE bizdate<=? AND ('+conditions+')',[day,*[v for k in keys for v in k]]).fetchall()
                            rawnet={(str(m),code,str(d)):net for m,code,d,net in raw}
                            for k in keys:
                                for row in histories[k]:row['rawNet']=rawnet.get((*k,row['date']))
                        checks=verify(quality,case,histories)
                        report['checks'].append(dict(name=case['name'],round=execution['round'],status='PASS',checks=checks,samples=len(keys)))
                        print(case['name']+' explanations PASS',flush=True)
        else:
            histories={};rows=[];extension=[]
            for index in range(36):
                m=[0,1,103][index%3];code=f'{index+1:06}';size=[1,2,3,4,5,6,20,25,40][index%9];history=[]
                for i in range(size):
                    day=str(date(2026,4,14)-timedelta(days=(size-i-1)*41));price=2 if index%5==0 else (i*7+index*3)%11
                    if index==9:price=0  # Hand fixture: both current pair inputs zero.
                    price=None if index%7==0 and i==size//2 else price
                    opening=0 if index%9==0 else None if index%8==0 and i==size-1 else (i+index)%7
                    has_ext=not(index%4==0 and i==size-1);net=-999999 if index%6==0 else None if index%11==0 else index-20
                    history.append(dict(date=day,close=None if price is None else price*10000,open=None if opening is None else opening*10000,volume=100,ext=has_ext,rawNet=net if has_ext else None,net=None if not has_ext or net==-999999 else net))
                    rows.append((m,code,day,price,opening,100,price))
                    if has_ext:extension.append((m,code,day,net))
                histories[(str(m),code)]=history
                rows.append((m,code,'2026-04-15',999,999,999,999))
            report.update(fixtureRows=rows,extensionRows=extension)
            with duckdb.connect() as con:
                con.execute('CREATE SCHEMA newzl');con.execute('CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR,bizdate DATE,closePrice DOUBLE,openPrice DOUBLE,volume BIGINT,closePricePosition DECIMAL(36,4))');con.execute('CREATE TABLE newzl.v_hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT)')
                con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?,?,?,?)',rows);con.executemany('INSERT INTO newzl.v_hsj_stock_hq_ext VALUES(?,?,?,?)',extension)
                def query(sql,bindings):return [[str(v) if v is not None else 'NULL' for v in row] for row in con.execute(sql.replace('`','"'),bindings).fetchall()]
                plans=probe([dict(dsl=c['dsl'],samples=[]) for c in suite],args.java);requests=[]
                for case,plan in zip(suite,plans):
                    coverage=plan['coverage'];combined=query(coverage['combinedSql'],coverage['bindings']);width=len(coverage['inputs'])+2
                    samples=[row[width:] for row in combined if '1' in row[width+2:]]
                    requests.append(dict(dsl=case['dsl'],samples=samples))
                fetches=probe(requests,args.java)
                for request,fetch in zip(requests,fetches):
                    if request['samples']:request['rawRows']=query(fetch['fetch']['sql'],fetch['fetch']['bindings'])
                explained=probe(requests,args.java)
                for case,request,result in zip(suite,requests,explained):
                    quality=dict(inputs=result['coverage']['inputs'],sampleDetails=result['details'],unavailableSamples=request['samples'])
                    checks=verify(quality,case,histories if case['date']=='2026-04-14' else {})
                    report['checks'].append(dict(name=case['name'],status='PASS',checks=checks,samples=len(request['samples']),details=result['details']))
    except Exception as error:report['fatalError']=str(error);raise
    finally:
        report.update(status='FAIL' if 'fatalError' in report else 'PASS',passed=sum(c['status']=='PASS' for c in report['checks']),total=len(report['checks']))
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','passed','total']}))


if __name__=='__main__':main()
