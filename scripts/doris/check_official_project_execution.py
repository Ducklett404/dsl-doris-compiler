"""Project-only CLI/HTTP checks against independent calculations on immutable official raw rows."""
import argparse
from contextlib import ExitStack
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import duckdb

from validate_project_sources import ROOT, WslDoris, digest


def indicator(metric, date, count=''):
    return f"indicator('', '', '{metric}', '{date}', '', '', '{count}')"


def independent(con, date):
    rows = con.execute("""WITH tail AS (
        SELECT mktcode,tgtcode,bizdate,closePx,openPx,volume FROM newzl.hsj_stock_hq_basic WHERE bizdate<=CAST(? AS DATE)
        QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=20)
        SELECT b.*,e.tgtcode,ZJLXMainNetTur FROM tail b LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate)
        ORDER BY b.mktcode,b.tgtcode,b.bizdate""", [date]).fetchall()
    histories = defaultdict(list)
    for market, code, day, close, opening, volume, ext, net in rows:
        histories[(str(market),code)].append(dict(date=str(day),close=close,open=opening,volume=volume,
            ext=ext is not None,net=None if net == -999999 else net))
    current = {key: history for key,history in histories.items() if history[-1]['date']==date}
    names = ['close','net','mixed','ma5','cons3','exist3','position3','cross','rank','queryData']
    expected = {name:[] for name in names}
    unavailable = {name:defaultdict(int) for name in names}
    target = next((history[-1]['close'] for key,history in current.items() if key[1]=='600000'),None)
    missing = sum(not h[-1]['ext'] for h in current.values())
    values=[]
    for key, history in current.items():
        now=history[-1]; close=now['close']; net=now['net']
        for name in ['close','mixed','cons3','queryData']:
            unavailable[name][('indicator','收盘价')] += close is None
        for name in ['net','mixed']:
            unavailable[name][('indicator','主力净流入')] += net is None
        if close is not None and close>10000: expected['close'].append(list(key))
        if net is not None and net>0: expected['net'].append(list(key))
        if close is not None and close>10000 and net is not None and net>0: expected['mixed'].append(list(key))
        prices=[r['close'] for r in history]
        complete5=len(prices)>=5 and all(p is not None for p in prices[-5:])
        unavailable['ma5'][('indicator','5日均线')] += not complete5
        if complete5 and sum(prices[-5:])>50000: expected['ma5'].append(list(key))
        unavailable['cons3'][('CONS','完整 3 条观察记录的次数条件')] += len(history)<3
        unavailable['cons3'][('CONS（窗口输入）','完整 3 条观察记录的条件输入')] += len(history)<3 or any(p is None for p in prices[-3:])
        if len(history)>=3 and all(p is not None and p>10000 for p in prices[-3:]): expected['cons3'].append(list(key))
        unavailable['exist3'][('indicator','成交量')] += now['volume'] is None
        unavailable['exist3'][('EXIST','完整 20 条观察记录的次数条件')] += len(history)<20
        unavailable['exist3'][('EXIST（窗口输入）','完整 20 条观察记录的条件输入')] += len(history)<20 or any(r['volume'] is None for r in history[-20:])
        if len(history)>=20 and sum(r['volume'] is not None and r['volume']>0 for r in history[-20:])>=3: expected['exist3'].append(list(key))
        complete3=len(prices)>=3 and all(p is not None for p in prices[-3:]) and max(prices[-3:])!=min(prices[-3:])
        unavailable['position3'][('position','收盘价')] += not complete3
        if complete3 and 3*(close-min(prices[-3:]))>=2*(max(prices[-3:])-min(prices[-3:])): expected['position3'].append(list(key))
        complete2=len(history)>=2 and all(r[f] is not None for r in history[-2:] for f in ('close','open'))
        unavailable['cross'][('cross_above','收盘价 / 开盘价')] += not complete2
        if complete2 and close>now['open'] and history[-2]['close']<=history[-2]['open']: expected['cross'].append(list(key))
        unavailable['rank'][('rank','收盘价')] += close is None
        if close is not None: values.append((list(key),close))
        unavailable['queryData'][('querydata','收盘价')] += target is None  # Canonical DSL function names are lowercase.
        if close is not None and target is not None and close>target: expected['queryData'].append(list(key))
    top=sorted({p for _,p in values},reverse=True)[:3]
    expected['rank']=[key for key,p in sorted(values,key=lambda v:(-v[1],v[0])) if p in top]
    for name in names:
        if name!='rank': expected[name].sort()
    return dict(observed=len(current),missingExtension=missing,expected=expected,unavailable=unavailable)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--certificate',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=ROOT/'target/data-audit/acceptance-a0f7260.duckdb')
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--java',default='D:/Java/jdk-21/bin/java.exe')
    parser.add_argument('--only-case', help='Run one case for failure diagnosis; no HTTP/full-suite claim')
    args=parser.parse_args();folder=args.output_dir.resolve()
    if (folder/'result.json').exists(): raise ValueError('Use a fresh output directory')
    folder.mkdir(parents=True,exist_ok=True)
    certificate=json.loads(args.certificate.read_text(encoding='utf-8'))
    snapshot=certificate['snapshotId'];client=WslDoris(args.distribution,'dsl-doris-official')
    before=client.query('SELECT * FROM newzl.data_snapshot_registry')
    address=subprocess.run(['wsl.exe','-d',args.distribution,'--exec','hostname','-I'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
    hosts=re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b',address.stdout)
    if address.returncode or not hosts: raise RuntimeError('Cannot determine WSL IPv4 address')
    host=hosts[0]
    reader='dsl_project_official_'+secrets.token_hex(6);password=secrets.token_hex(24);token=secrets.token_hex(24)
    env=os.environ.copy();env.update(DSL_PROJECT_PASSWORD=password,DSL_PROJECT_TOKEN=token)
    java=[args.java,'-Dfile.encoding=UTF-8','-Dsun.stdout.encoding=UTF-8','-Dsun.stderr.encoding=UTF-8','-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets','-jar',str(ROOT/'target/dsl-doris-compiler.jar')]
    connection=['--host',host,'--database','newzl','--user',reader,'--password-env','DSL_PROJECT_PASSWORD',
        '--max-scan-rows','100000000','--max-exec-memory-bytes','2147483648','--max-return-rows','10000']
    report=dict(purpose='PROJECT_SCOPED_OFFICIAL_DATA_EXECUTION',officialAcceptanceEligible=False,
        jarSha256=digest(ROOT/'target/dsl-doris-compiler.jar'),certificateSha256=digest(args.certificate),snapshotId=snapshot,
        manifestSha256=certificate['manifestSha256'],checks=[],cases=[])
    server=None;created=False;con=None
    def check(name,passed,**detail):
        report['checks'].append(dict(name=name,status='PASS' if passed else 'FAIL',**detail))
        if not passed: raise AssertionError(name)
    def stop_server():
        nonlocal server
        if server is not None:
            if server.poll() is None: server.terminate()
            server.wait(timeout=10);server=None
    def compare(name,data,ref,key,extension):
        quality=data['dataQuality'];actual={(r['function'],r['indicator']):r['unavailableSecurities'] for r in quality['inputs']}
        expect=dict(ref['unavailable'][key]);keys_equal=data['rows']==ref['expected'][key]
        coverage_equal=(quality['observedSecurities']==ref['observed'] and quality['currentMissingExtensionRows']==(ref['missingExtension'] if extension else 0) and actual==expect)
        (folder/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        check(name+'-keys-and-coverage',keys_equal and coverage_equal and not data['truncated'] and quality['officialAcceptanceEligible'] is False,
            rows=len(data['rows']),expectedRows=len(ref['expected'][key]),keysEqual=keys_equal,coverageEqual=coverage_equal,observedSecurities=quality['observedSecurities'],currentMissingExtensionRows=quality['currentMissingExtensionRows'],
            actualInputs=[dict(function=k[0],indicator=k[1],unavailable=v) for k,v in actual.items()],expectedInputs=[dict(function=k[0],indicator=k[1],unavailable=v) for k,v in expect.items()])
    def request(endpoint,payload,auth=True):
        headers={'Content-Type':'application/json'}
        if auth: headers['Authorization']='Bearer '+token
        try:
            with urllib.request.urlopen(urllib.request.Request(endpoint+'/execute',data=json.dumps(payload).encode(),headers=headers),timeout=80) as r:
                body=r.read().decode('utf-8');return r.status,json.loads(body) if 'json' in r.headers.get('Content-Type','') else body
        except urllib.error.HTTPError as e: return e.code,json.loads(e.read())
    try:
        con=duckdb.connect(str(args.database),read_only=True);con.execute("SET memory_limit='4GB'");con.execute('SET threads=4')
        lock=con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone()
        check('independent-source-lock',lock==(snapshot,certificate['manifestSha256'],'FAIL'))
        references={}
        for date in ['2026-04-14','2006-01-04','2018-08-20']:
            references[date]=independent(con,date)
        con.close();con=None
        client.query(f"CREATE USER '{reader}' IDENTIFIED BY '{password}'");created=True
        client.query(f"GRANT SELECT_PRIV ON newzl.* TO '{reader}'")
        date='2026-04-14';close=indicator('收盘价',date)+' > 1';net=indicator('主力净流入',date)+' > 0'
        cases=[('close',close,'close',False,date),('net',net,'net',True,date),('mixed',close+' and '+net,'mixed',True,date),
            ('ma5',indicator('5日均线',date)+' > 1','ma5',False,date),('cons3',indicator('收盘价',date,'CONS>=3日')+' > 1','cons3',False,date),
            ('exist3',indicator('成交量',date,'EXIST>=3日')+' > 0','exist3',False,date),
            ('position3',f"position('', '', '收盘价', '3日', '{date}', '', '', '') = '高'",'position3',False,date),
            ('cross',f"cross_above('', '', '收盘价', '开盘价', '{date}', '', '') = True",'cross',False,date),
            ('rank',f"rank('', '', '收盘价', 'desc:dense_rank', '{date}', '', '', '') <= 3",'rank',False,date),
            ('queryData',indicator('收盘价',date)+f" > queryData('', '600000', '收盘价', '{date}', '')",'queryData',False,date),
            ('first-basic',indicator('收盘价','2006-01-04')+' > 1','close',False,'2006-01-04'),
            ('early-extension',indicator('主力净流入','2018-08-20')+' > 0','net',True,'2018-08-20')]
        if args.only_case and args.only_case not in {case[0] for case in cases}: raise ValueError('Unknown diagnostic case')
        with tempfile.TemporaryDirectory(prefix='official-project-') as temp, ExitStack() as processes:
            source=Path(temp)/'query.dsl'
            for name,dsl,key,extension,day in cases:
                if args.only_case and name!=args.only_case: continue
                source.write_text(dsl,encoding='utf-8');start=time.monotonic()
                executed=subprocess.run(java+['execute-stock-slot-sql',str(source),'--snapshot-id',snapshot,'--max-rows','10000']+connection+['--project-validation',str(args.certificate.resolve())],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
                if executed.returncode:
                    probe=subprocess.run([args.java,'-Dfile.encoding=UTF-8','-cp',str(ROOT/'target/dsl-doris-compiler.jar'),str(ROOT/'scripts/doris/ProjectExecutionProbe.java'),
                        f'jdbc:mysql://{host}:9030/newzl',reader,str(ROOT/'src/main/resources/stock-slot-registry-v1.json'),str(args.certificate.resolve()),str(source)],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=80)
                    report['diagnostic']=probe.stdout.replace(password,'[REDACTED]').replace(token,'[REDACTED]')
                check(name+'-cli',executed.returncode==0,exitCode=executed.returncode,error=executed.stderr[:400].replace(password,'[REDACTED]').replace(token,'[REDACTED]'))
                data=json.loads(executed.stdout);compare(name,data,references[day],key,extension)
                report['cases'].append(dict(name=name,dsl=dsl,evaluationDate=day,rows=len(data['rows']),coverageStatus=data['dataQuality']['coverageStatus'],
                    totalMillis=data['timings']['totalMillis'],dorisExecutionMillis=data['timings']['dorisExecutionMillis'],validationMillis=data['dataQuality']['validationMillis'],wallSeconds=round(time.monotonic()-start,3)))
                print(name+' PASS',flush=True)
            if args.only_case:
                check('official-registry-unmodified',client.query('SELECT * FROM newzl.data_snapshot_registry')==before and not before)
                report['purpose']='PROJECT_SCOPED_SINGLE_CASE_DIAGNOSTIC'
                report['selectedCase']=args.only_case
                return
            log=Path(temp)/'http.log'
            with log.open('wb') as output:
                server=subprocess.Popen(java+['serve-doris']+connection+['--project-validation',str(args.certificate.resolve()),'--http-port','0','--auth-token-env','DSL_PROJECT_TOKEN'],env=env,stdout=output,stderr=subprocess.STDOUT)
            processes.callback(stop_server)
            endpoint=None;deadline=time.monotonic()+30
            while time.monotonic()<deadline and server.poll() is None:
                match=re.search(r'Listening on (http://127.0.0.1:\d+)',log.read_text(encoding='utf-8',errors='replace'))
                if match: endpoint=match[1];break
                time.sleep(.1)
            check('official-http-start',endpoint is not None)
            payload=dict(dsl=net,snapshotId=snapshot,maxRows=10000)
            status,data=request(endpoint,payload,False);check('official-http-auth',status==401)
            status,data=request(endpoint,payload);check('official-http-success',status==200);compare('http-net',data,references[date],'net',True)
            status,data=request(endpoint,dict(payload,format='markdown'));check('official-http-readable-coverage',status==200 and '数据可用性' in data and '不代表官方验收' in data)
            (folder/'official-http-result.md').write_text(data,encoding='utf-8')
            status,data=request(endpoint,dict(payload,dsl="belong_industry('', '', '收盘价', '2026-04-14', 'AVG') > 1"));check('official-http-industry-unavailable',status==503)
        check('official-registry-unmodified',client.query('SELECT * FROM newzl.data_snapshot_registry')==before and not before)
    except Exception as error:
        report['fatalError']=str(error).replace(password,'[REDACTED]').replace(token,'[REDACTED]');raise
    finally:
        if con: con.close()
        stop_server()
        if created: client.query(f"DROP USER '{reader}'")
        report.update(cleanup='DONE',passed=sum(c['status']=='PASS' for c in report['checks']),total=len(report['checks']),completedAtUtc=datetime.now(timezone.utc).isoformat())
        report['status']='PASS' if 'fatalError' not in report and report['passed']==report['total'] else 'FAIL'
        (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'],passed=report['passed'],total=report['total'])))


if __name__=='__main__': main()
