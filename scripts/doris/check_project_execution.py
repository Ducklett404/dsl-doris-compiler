"""Real CLI/HTTP project execution on labelled synthetic gaps; preserve strict gate."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
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

from validate_project_sources import ROOT, WslDoris, metadata, capture_sources, sql_literal, definition


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='D:/Java/jdk-21/bin/java.exe')
    args = parser.parse_args()
    folder = args.output_dir.resolve()
    if (folder / 'result.json').exists(): raise ValueError('Use a fresh output directory')
    folder.mkdir(parents=True, exist_ok=True)
    client = WslDoris(args.distribution, 'dsl-doris-official')
    original = client.query('SELECT * FROM newzl.data_snapshot_registry')
    database = 'dsl_project_fixture_' + secrets.token_hex(6)
    reader = 'dsl_project_read_' + secrets.token_hex(6)
    password, token = secrets.token_hex(24), secrets.token_hex(24)
    registry = json.loads((ROOT / 'src/main/resources/stock-slot-registry-v1.json').read_text(encoding='utf-8'))
    for table in registry['tables'].values(): table['qualifiedName'] = database + '.' + table['qualifiedName'].split('.')[-1]
    registry_path = folder / 'registry.json'
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8')
    address = subprocess.run(['wsl.exe','-d',args.distribution,'--exec','hostname','-I'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    host = re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', address.stdout)[0]
    environment = os.environ.copy()
    environment.update(DSL_PROJECT_PASSWORD=password, DSL_PROJECT_TOKEN=token)
    command = [args.java, '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8',
        '-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets', '-jar', str(ROOT / 'target/dsl-doris-compiler.jar')]
    connection = ['--host',host,'--port',str(client.query_port),'--database',database,'--user',reader,'--password-env','DSL_PROJECT_PASSWORD','--registry',str(registry_path),'--max-scan-rows','10000','--max-exec-memory-bytes','134217728']
    created = account = False
    server = None
    report = dict(purpose='SYNTHETIC_PROJECT_SCOPED_EXECUTION', officialAcceptanceEligible=False,
        jarSha256=hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest(), checks=[])

    def check(name, passed, **details):
        report['checks'].append(dict(name=name, status='PASS' if passed else 'FAIL', **details))
        if not passed: raise AssertionError(name)

    def stop_server():
        nonlocal server
        if server is not None:
            if server.poll() is None: server.terminate()
            server.wait(timeout=10);server=None

    def insert(table, columns, rows):
        client.query(f'INSERT INTO {database}.{table}({columns}) VALUES ' + ','.join('('+','.join(sql_literal(v) for v in row)+')' for row in rows))

    def request(endpoint, body=None, auth=True):
        headers={'Content-Type':'application/json'}
        if auth: headers['Authorization']='Bearer '+token
        try:
            with urllib.request.urlopen(urllib.request.Request(endpoint, data=None if body is None else json.dumps(body).encode(), headers=headers), timeout=30) as result:
                data=result.read().decode('utf-8')
                return result.status, json.loads(data) if 'json' in result.headers.get('Content-Type','') else data
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())

    try:
        client.query('CREATE DATABASE '+database);created=True
        for path in ['001_rebuild_tables.sql','002_semantic_view.sql']:
            client.query((ROOT/'data/doris/ddl'/path).read_text(encoding='utf-8').replace('USE newzl;', 'USE '+database+';'))
        vectors={'000001':[2,3,4],'000002':[2,2,2],'000003':[5],'000004':[1,None,3],'000005':[None,None,None],'000006':[1,2,3]}
        basic=[];extension=[]
        for code,prices in vectors.items():
            dates=['2026-04-14'] if len(prices)==1 else (['2026-04-11','2026-04-12','2026-04-13'] if code=='000006' else ['2026-04-12','2026-04-13','2026-04-14'])
            if code=='000001': dates=['2026-01-04','2026-02-01','2026-04-14']  # Actual observations span long suspensions.
            for date,price in zip(dates,prices):
                px=None if price is None else price*10000
                basic.append((1,code,date,px,10000,px,px,px,px,100,10000))
                if not (code=='000002' and date=='2026-04-14'):
                    net=-999999 if code=='000003' else 0 if code=='000004' else None if code=='000005' else 10
                    extension.append((1,code,date,net))
        extension.append((1,'999999','2026-04-14',20))
        # A NULL current price must not fall through the unbounded POSITION CASE to '中'.
        basic += [(1,'000005',d,px,10000,px,px,px,px,100,10000) for d,px in [('2026-01-01',10000),('2026-01-02',20000)]]
        insert('hsj_stock_hq_basic','mktcode,tgtcode,bizdate,lastPx,preClosePx,closePx,openPx,highPx,lowPx,volume,turnover',basic)
        insert('hsj_stock_hq_ext','mktcode,tgtcode,bizdate,ZJLXMainNetTur',extension)
        insert('hsj_stock_code_info','mktcode,tgtcode,name',[(1,code,'合成证券'+code) for code in list(vectors)+['999999']])
        meta=metadata(args.java,registry_path)
        sources,details=capture_sources(client,meta,dict(basic=len(basic),extension=len(extension),code=7))
        check('independent-source-capabilities',all(s['status']=='PROJECT_READY' for s in sources.values()), details=details)
        certificate=dict(formatVersion='project-data-validation-v1',status='PROJECT_READY_WITH_LIMITATIONS',snapshotId='synthetic-project-v1',contractVersion='fixture-v1',
            manifestSha256='a'*64,registryFingerprint=meta['registryFingerprint'],definitionAuthority='PROJECT_INTERNAL',sources=sources,
            extensionWithoutBasic=1,closeOutsideRange=0,limitations=['手工标注合成数据；不代表官方数据或官方验收。'])
        certificate_path=folder/'project-validation.json'
        certificate_path.write_text(json.dumps(certificate,ensure_ascii=False,indent=2),encoding='utf-8')
        client.query(f"CREATE USER '{reader}' IDENTIFIED BY '{password}'");account=True
        client.query(f"GRANT SELECT_PRIV ON {database}.* TO '{reader}'")
        client.query('ANALYZE TABLE '+database+'.hsj_stock_hq_basic WITH SYNC')
        with tempfile.TemporaryDirectory(prefix='project-execution-') as temporary, ExitStack() as processes:
            source=Path(temporary)/'query.dsl'

            def execute(name,dsl,cert=certificate_path,extra=(),expected=0):
                source.write_text(dsl,encoding='utf-8')
                option=[] if cert is None else ['--project-validation',str(cert)]
                selected=list(connection)
                for flag in extra[::2]:
                    if flag in selected:
                        offset=selected.index(flag);del selected[offset:offset+2]
                result=subprocess.run(command+['execute-stock-slot-sql',str(source),'--snapshot-id','synthetic-project-v1']+selected+option+list(extra),
                    env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40)
                if result.returncode and expected==0:
                    probe=subprocess.run([args.java,'-Dfile.encoding=UTF-8','-cp',str(ROOT/'target/dsl-doris-compiler.jar'),str(ROOT/'scripts/doris/ProjectExecutionProbe.java'),
                        f'jdbc:mysql://{host}:{client.query_port}/{database}',reader,str(registry_path),str(cert),str(source)],env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40)
                    report['diagnostic']=probe.stdout.replace(password,'[REDACTED]').replace(token,'[REDACTED]')
                check(name,result.returncode==expected,exitCode=result.returncode,
                    error=result.stderr[:600].replace(password,'[REDACTED]').replace(token,'[REDACTED]') if result.returncode else '')
                if expected: return {}
                data=json.loads(result.stdout)
                (folder/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                return data

            close="indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1"
            net="indicator('', '', '主力净流入', '2026-04-14', '', '', '') > 0"
            data=execute('basic-positive',close)
            check('basic-results-and-null-coverage',data['rows']==[['1',c] for c in ['000001','000002','000003','000004']]
                and data['dataQuality']['observedSecurities']==5 and data['dataQuality']['inputs'][0]['unavailableSecurities']==1
                and data['dataQuality']['currentMissingExtensionRows']==0)
            data=execute('extension-positive',net)
            check('missing-sentinel-and-null-coverage',data['rows']==[['1','000001']] and data['dataQuality']['currentMissingExtensionRows']==1
                and data['dataQuality']['inputs'][0]['unavailableSecurities']==3 and data['dataQuality']['snapshotExtensionWithoutBasic']==1)
            data=execute('mixed-positive',close+' and '+net)
            check('mixed-retains-three-valued-inputs',data['rows']==[['1','000001']] and len(data['dataQuality']['inputs'])==2)
            data=execute('window-positive',"indicator('', '', '3日均线', '2026-04-14', '', '', '') > 1")
            check('window-insufficiency-and-historical-null',data['rows']==[['1','000001'],['1','000002']] and data['dataQuality']['inputs'][0]['unavailableSecurities']==3)
            data=execute('position-positive',"position('', '', '收盘价', '3日', '2026-04-14', '', '', '') = '高'")
            check('position-flat-and-window-gaps',data['rows']==[['1','000001']] and data['dataQuality']['inputs'][0]['unavailableSecurities']==4)
            check('position-retains-sparse-observed-rows',any(p['kind']=='ObservedTail' for p in data['compilation']['logicalPlan']))
            data=execute('historical-position-current-null',"position('', '', '收盘价', '历史', '2026-04-14', '', '', '') = '中'")
            check('historical-position-null-and-explanation',data['rows']==[] and data['dataQuality']['inputs'][0]['unavailableSecurities']==3
                and any(s['securityCode']=='000005' and any(r['code']=='SOURCE_NULL' and r['relatedDates']==['2026-04-14']
                    for i in s['inputs'] for r in i['reasons']) for s in data['dataQuality']['sampleDetails']))
            data=execute('consecutive-positive',"indicator('', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') > 1")
            check('consecutive-complete-horizon',data['rows']==[['1','000001'],['1','000002']] and any(i['unavailableSecurities']==3 for i in data['dataQuality']['inputs']))
            data=execute('named-security-positive',"indicator('', '', '收盘价', '2026-04-14', '', '', '') > queryData('', '合成证券000002', '收盘价', '2026-04-14', '')")
            check('code-source-dependency',data['rows']==[['1',c] for c in ['000001','000003','000004']] and 'code' in data['dataQuality']['requiredSources'])
            data=execute('ranking-positive',close+" then rank('', '', '收盘价', 'desc:row_number', '2026-04-14', '', '', '') <= 2 limit 0,1")
            check('availability-before-then-rank-and-limit',data['rows']==[['1','000003']] and data['dataQuality']['observedSecurities']==5)
            data=execute('no-observations',close.replace('2026-04-14','2026-04-15'))
            check('empty-date-is-labelled',data['rows']==[] and data['dataQuality']['coverageStatus']=='NO_OBSERVATIONS')
            execute('strict-still-rejects',close,cert=None,expected=3)
            execute('industry-rejected',"indicator('', '', '收盘价', '2026-04-14', '', '', '') > belong_industry('', '', '收盘价', '2026-04-14', 'AVG')",expected=3)
            execute('scan-limit-rejected',close,extra=['--max-scan-rows','1'],expected=3)
            for key,field,value in [('stale-count','rows',999),('stale-definition','definitionSha256','0'*64)]:
                changed=json.loads(json.dumps(certificate));changed['sources']['basic'][field]=value
                path=Path(temporary)/(key+'.json');path.write_text(json.dumps(changed),encoding='utf-8')
                execute(key,close,cert=path,expected=3)
            changed=json.loads(json.dumps(certificate));changed['sources']['extension']['status']='BLOCKED'
            path=Path(temporary)/'blocked-extension.json';path.write_text(json.dumps(changed),encoding='utf-8')
            execute('basic-with-blocked-extension',close,cert=path)
            execute('extension-capability-blocked',net,cert=path,expected=3)
            changed=json.loads(json.dumps(certificate));changed['sources']['code']['status']='BLOCKED'
            path=Path(temporary)/'blocked-code.json';path.write_text(json.dumps(changed),encoding='utf-8')
            execute('basic-with-blocked-code',close,cert=path)
            execute('code-capability-blocked',"queryData('', '合成证券000002', '收盘价', '2026-04-14', '') > 1",cert=path,expected=3)
            log=Path(temporary)/'server.log'
            with log.open('wb') as output:
                server=subprocess.Popen(command+['serve-doris']+connection+['--project-validation',str(certificate_path),'--http-port','0','--auth-token-env','DSL_PROJECT_TOKEN'],env=environment,stdout=output,stderr=subprocess.STDOUT)
            processes.callback(stop_server)
            endpoint=None;deadline=time.monotonic()+30
            while time.monotonic()<deadline and server.poll() is None:
                match=re.search(r'Listening on (http://127.0.0.1:\d+)',log.read_text(encoding='utf-8',errors='replace'))
                if match: endpoint=match[1];break
                time.sleep(.1)
            check('project-http-starts',endpoint is not None)
            payload=dict(dsl=net,snapshotId='synthetic-project-v1')
            status,data=request(endpoint+'/execute',payload,False);check('project-http-authentication',status==401)
            status,data=request(endpoint+'/execute',payload);check('project-http-positive-coverage',status==200 and data['dataQuality']['officialAcceptanceEligible'] is False and data['dataQuality']['currentMissingExtensionRows']==1)
            status,data=request(endpoint+'/execute',dict(payload,snapshotId="' OR 1=1 --"));check('project-http-snapshot-identity',status==503)
            status,data=request(endpoint+'/execute',dict(payload,format='markdown'));check('project-http-markdown',status==200 and '数据可用性' in data and '不代表官方验收' in data)
            status,data=request(endpoint+'/execute',payload);check('project-http-recovers',status==200)
            original_view=definition(client,database+'.v_hsj_stock_hq_basic','VIEW')
            client.query('USE '+database+';\n'+original_view.replace('CREATE VIEW','ALTER VIEW',1).rstrip(';')+' WHERE 1=1')
            execute('live-view-change-rejected',close,expected=3)
            status,data=request(endpoint+'/execute',payload);check('project-http-live-view-change-rejected',status==503)
        check('official-registry-unchanged',original==client.query('SELECT * FROM newzl.data_snapshot_registry'))
    except Exception as error:
        report['fatalError']=str(error).replace(password,'[REDACTED]').replace(token,'[REDACTED]');raise
    finally:
        stop_server()
        if account: client.query(f"DROP USER '{reader}'")
        if created: client.query('DROP DATABASE '+database)
        report.update(cleanup='DONE',passed=sum(c['status']=='PASS' for c in report['checks']),total=len(report['checks']),completedAtUtc=datetime.now(timezone.utc).isoformat())
        report['status']='PASS' if 'fatalError' not in report and report['passed']==report['total'] else 'FAIL'
        (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','passed','total']}))


if __name__=='__main__': main()
