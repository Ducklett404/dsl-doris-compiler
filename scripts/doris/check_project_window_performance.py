"""Controlled mixed-window correctness and hot-process timings on immutable official rows."""
import argparse
import hashlib
from datetime import datetime, timezone
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
import importlib
from validate_project_sources import ROOT, WslDoris, digest
from project_matrix_reference import load, render, reference, assess


def owned_runtime_environment(client):
    """Selective, read-only runtime identity; never capture Docker Env or secrets."""
    from configure_project_be_runtime import RUNTIME_TARGET
    from project_fe_runtime import capture_fe_runtime
    template = '{{.Id}} {{.State.Running}} {{index .Config.Labels "com.acme.dorisdsl.purpose"}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'
    metadata = subprocess.run(client.prefix + ['inspect', '-f', template, 'dsl-doris-official'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, timeout=20)
    parts = metadata.stdout.strip().split()
    if (len(parts) != 5 or re.fullmatch(r'[0-9a-f]{64}', parts[0]) is None or
            parts[1:3] != ['true', 'official-data-diagnostic'] or
            any(re.fullmatch(r'[0-9]+', p) is None for p in parts[3:]) or int(parts[3]) <= 0):
        raise ValueError('Expected the running owned container with valid resource identity')
    backend = subprocess.run(client.prefix + ['exec', 'dsl-doris-official', 'curl', '-fsS', '--max-time', '10',
        f'http://127.0.0.1:{client.be_http_port}/api/show_config'], capture_output=True, text=True,
        encoding='utf-8', errors='replace', check=True, timeout=20)
    rows = json.loads(backend.stdout)
    if not isinstance(rows, list) or any(not isinstance(r, list) or len(r) < 3 for r in rows):
        raise ValueError('Malformed BE configuration response')
    selected = [r for r in rows if r[0] in RUNTIME_TARGET]
    if (len(selected) != len(RUNTIME_TARGET) or {r[0] for r in selected} != set(RUNTIME_TARGET) or
            any(not isinstance(r[2], str) or re.fullmatch(r'-?[0-9]+', r[2]) is None for r in selected)):
        raise ValueError('Incomplete or duplicate BE runtime settings')
    shares = [r[2] for r in rows if r[0] == 'mem_limit']
    if (len(shares) != 1 or not isinstance(shares[0], str) or
            re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?:%|[KMGTP]?B)?', shares[0], flags=re.I) is None):
        raise ValueError('Incomplete or duplicate BE memory limit')
    configuration = subprocess.run(client.prefix + ['exec', 'dsl-doris-official', 'cat',
        '/opt/apache-doris/be/conf/be.conf'], capture_output=True, check=True, timeout=20)
    if not isinstance(configuration.stdout, bytes) or not configuration.stdout:
        raise ValueError('Empty or non-binary BE configuration')
    return dict(containerId=parts[0], containerMemoryBytes=int(parts[3]), containerNanoCpus=int(parts[4]),
        beMemoryShare=shares[0], beRuntimeSettings={r[0]:r[2] for r in selected},
        beConfigurationSha256=hashlib.sha256(configuration.stdout).hexdigest(),
        feRuntime=capture_fe_runtime(client))


def capture_preservation(report, source_state, environment):
    """Always capture postconditions, including an early SQL/HTTP failure.

    Do not mask the original exception or expose connection error text. Cleanup
    is a separate claim from source/environment preservation.
    """
    errors = []
    for name, before_key, after_key, probe in (
            ('sources-unchanged', 'sourceStateBefore', 'sourceStateAfter', source_state),
            ('environment-unchanged', 'environment', 'environmentAfter', environment)):
        if before_key not in report:
            report['checks'].append(dict(name=name, status='NOT_RUN', reason='Initial state unavailable'))
            errors.append(name + ': initial state unavailable')
            continue
        try:
            observed = probe()
            report[after_key] = observed
            ok = observed == report[before_key]
            report['checks'].append(dict(name=name, status='PASS' if ok else 'FAIL'))
            if not ok:
                errors.append(name + ': state changed')
        except Exception as error:
            report['checks'].append(dict(name=name, status='FAIL', reason='Postcheck unavailable: ' + type(error).__name__))
            errors.append(name + ': postcheck unavailable: ' + type(error).__name__)
    report['preservationErrors'] = errors


def cases():
    result = []
    def add(name, calls, expr, date='2026-04-14', market=''):
        result.append(dict(name=name, calls=calls, expr=expr, date=date, market=market,
                           dsl=render(expr, calls, date, market)))
    rsi = dict(kind='rsi', n=5)
    add('position3', [dict(kind='position', n=3)], ('cmp', 0, '=', '高'))
    add('rsi5', [rsi], ('cmp', 0, '>', 50))
    for kind, n, op, threshold in [('ma',20,'>',1), ('position',20,'=','高'), ('record_high',5,'=',True), ('cross_above',2,'=',True)]:
        add('rsi-'+kind, [rsi, dict(kind=kind,n=n)], ('and', ('cmp',0,'>',50), ('cmp',1,op,threshold)))
    for base in [rsi, dict(kind='ma',n=20), dict(kind='position',n=5)]:
        for mode, op in [('CONS','>='),('CONS','='),('EXIST','>='),('EXIST','=')]:
            threshold = '高' if base['kind']=='position' else 50 if base['kind']=='rsi' else 1
            call = dict(kind='count', base=base, n=3, mode=mode, countOp=op,
                        op='=' if base['kind']=='position' else '>', threshold=threshold)
            add(base['kind']+'-'+mode+op, [call], ('cmp',0,'=',True))
    for date in ['2006-01-04','2018-08-20','2026-04-12']:
        add('date-'+date,[rsi,dict(kind='ma',n=20)],('or',('cmp',0,'>',50),('cmp',1,'>',1)),date)
    add('funds-mixed',[rsi,dict(kind='field',metric='net')],('and',('cmp',0,'>',50),('cmp',1,'>',0)))
    add('two-count-windows',[dict(kind='count',base=rsi,n=3,mode='CONS',countOp='=',op='>',threshold=50),dict(kind='count',base=dict(kind='ma',n=20),n=3,mode='EXIST',countOp='>=',op='>',threshold=1)],('or',('cmp',0,'=',True),('cmp',1,'=',True)))
    add('rsi-then-rank',[rsi,dict(kind='rank',direction='desc:row_number')],('cmp',1,'<=',10))
    result[-1].update(pre=('cmp',0,'>',50),limit=5)
    result[-1]['dsl']=render(result[-1]['pre'],result[-1]['calls'],'2026-04-14','')+' then '+result[-1]['dsl']+' limit 0,5'
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--certificate',type=Path,required=True)
    p.add_argument('--jar',type=Path,default=ROOT/'target/dsl-doris-compiler.jar');p.add_argument('--rounds',type=int,default=3)
    p.add_argument('--baseline',action='store_true',help='Preserve failed baseline queries and continue; overall status stays FAIL')
    p.add_argument('--only-case',help='Single-case investigation, not full matrix coverage')
    p.add_argument('--timing-subset',action='store_true',help='Repeat position3 and rsi5 only; not full matrix coverage')
    p.add_argument('--explain',action='store_true',help='Save native plans without executing extra SELECTs')
    p.add_argument('--matrix',type=Path,help='Explicit project query matrix; default performance suite remains unchanged')
    p.add_argument('--field-oracle',action='store_true',help='Use the independent 19-field raw operand reference')
    p.add_argument('--oracle-module',choices=['project_combination_reference','project_rank_reference'],help='Frozen independent combination oracle')
    p.add_argument('--reference-database',type=Path,default=ROOT/'target/data-audit/acceptance-a0f7260.duckdb')
    p.add_argument('--distribution',default='dsl-doris-official-01a104f9');p.add_argument('--java',default='java')
    args=p.parse_args();folder=args.output_dir.resolve()
    if folder.exists() or args.rounds<1:raise ValueError('Fresh output directory and positive rounds required')
    folder.mkdir(parents=True);suite=cases() if args.matrix is None else json.loads(args.matrix.read_text(encoding='utf-8'));cert=json.loads(args.certificate.read_text(encoding='utf-8'))
    if not suite or len({c['name'] for c in suite})!=len(suite):raise ValueError('Nonempty matrix with unique case names required')
    original_case_names=[c['name'] for c in suite]
    if args.only_case:
        suite=[c for c in suite if c['name']==args.only_case]
        if len(suite)!=1:raise ValueError('Unknown case')
    if args.timing_subset:
        if args.only_case:raise ValueError('Choose one subset mode')
        suite=[c for c in suite if c['name'] in ['position3','rsi5']]
    if not suite:raise ValueError('The selected matrix subset is empty; nothing was executed')
    report=dict(purpose='PROJECT_MIXED_WINDOW_BASELINE' if args.baseline else 'PROJECT_MIXED_WINDOW_VALIDATION',officialAcceptanceEligible=False,
        cacheState='HOT_PROCESS_SQL_CACHE_DISABLED_OS_PAGE_CACHE_NOT_CLEARED_INCLUDES_FIRST_REQUEST',
        matrixScope='SINGLE_CASE_DIAGNOSTIC' if args.only_case else 'TIMING_SUBSET' if args.timing_subset else 'FULL_MATRIX',
        originalCaseNames=original_case_names,
        startedAtUtc=datetime.now(timezone.utc).isoformat(),jarSha256=digest(args.jar),certificateSha256=digest(args.certificate),
        oracleSha256=digest(ROOT/'scripts/doris/project_matrix_reference.py'),runnerSha256=digest(Path(__file__)),
        policySha256=digest(ROOT/'config/acceptance/project-data-policy-v1.json'),rounds=args.rounds,executions=[],checks=[])
    raw_loader=load
    evaluate=reference
    if args.field_oracle:
        from project_field_reference import load as load_fields
        raw_loader=load_fields;report['fieldOracleSha256']=digest(ROOT/'scripts/doris/project_field_reference.py')
    if args.oracle_module:
        oracle=importlib.import_module(args.oracle_module);evaluate=oracle.reference
        report['combinationOracleSha256']=digest(ROOT/'scripts/doris'/(args.oracle_module+'.py'))
    (folder/'matrix.json').write_text(json.dumps(suite,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    reader='dsl_window_read_'+secrets.token_hex(6);password=secrets.token_hex(24);token=secrets.token_hex(24)
    env=os.environ.copy();env.update(DSL_PROJECT_PASSWORD=password,DSL_PROJECT_TOKEN=token)
    client=None;server=None;account=False
    def redact(s):return str(s).replace(password,'[REDACTED]').replace(token,'[REDACTED]')
    def persist(): (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def check(name,ok):
        report['checks'].append(dict(name=name,status='PASS' if ok else 'FAIL'));persist()
        if not ok:raise AssertionError(name)
    def source_state():return [sorted(client.query(q)) for q in ["SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info",'SELECT * FROM newzl.data_snapshot_registry']]
    def environment():
        return owned_runtime_environment(client)
    try:
        client=WslDoris(args.distribution,'dsl-doris-official');before=source_state();report['sourceStateBefore']=before
        report['environment']=environment()
        check('strict-registry-empty',before[1]==[])
        expected={}
        with duckdb.connect(str(args.reference_database),read_only=True) as con:
            from project_field_reference import configure_reference_connection
            report['referenceResources']=configure_reference_connection(con,args.reference_database)
            check('raw-reference-lock',con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone()==(cert['snapshotId'],cert['manifestSha256'],'FAIL'))
            for date in sorted({c['date'] for c in suite}):
                source=raw_loader(con,date,64)  # > max(20 MA + 20 EXIST - 1, 5 RSI + 1 predecessor + 20 - 1).
                for case in suite:
                    if case['date']==date:expected[case['name']]=evaluate(case,source)
                print('raw reference '+date+' ready',flush=True)
                del source
        (folder/'expected.json').write_text(json.dumps({name:dict(rows=e['rows'],observed=e['observed'],samples=e['sampleKeys'],inputs=[dict(function=i['function'],indicator=i['indicator'],missing=len(i['missing'])) for i in e['inputs']]) for name,e in expected.items()},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        host=subprocess.run(['wsl.exe','-d',args.distribution,'--exec','hostname','-I'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True).stdout.split()[0]
        client.query(f"CREATE USER '{reader}' IDENTIFIED BY '{password}'");account=True
        client.query(f"GRANT SELECT_PRIV ON newzl.* TO '{reader}'")
        command=[args.java,'-Dfile.encoding=UTF-8','-Dsun.stdout.encoding=UTF-8','-Dsun.stderr.encoding=UTF-8','-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets','-jar',str(args.jar.resolve()),'serve-doris','--host',host,'--port',str(client.query_port),'--database','newzl','--user',reader,'--password-env','DSL_PROJECT_PASSWORD','--project-validation',str(args.certificate.resolve()),'--http-port','0','--auth-token-env','DSL_PROJECT_TOKEN','--max-scan-rows','100000000','--max-exec-memory-bytes','2147483648','--max-return-rows','10000']
        log=folder/'server.log'
        with log.open('wb') as output:server=subprocess.Popen(command,env=env,stdout=output,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+30;endpoint=None
        while time.monotonic()<deadline and server.poll() is None:
            match=re.search(r'Listening on (http://127.0.0.1:\d+)',log.read_text(encoding='utf-8',errors='replace'))
            if match:endpoint=match[1];break
            time.sleep(.1)
        check('http-started',endpoint is not None)
        for round_number in range(args.rounds):
            for case in suite:
                request=urllib.request.Request(endpoint+'/execute',data=json.dumps(dict(dsl=case['dsl'],snapshotId=cert['snapshotId'],maxRows=10000)).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
                start=time.monotonic()
                try:
                    with urllib.request.urlopen(request,timeout=80) as response:status=response.status;data=json.loads(response.read())
                except urllib.error.HTTPError as error:status=error.code;data=json.loads(error.read())
                filename=re.sub(r'[<>:"/\\|?*]','_',case['name'])+f'-{round_number+1}.json'
                (folder/filename).write_text(redact(json.dumps(data,ensure_ascii=False,indent=2))+'\n',encoding='utf-8')
                checks={} if status!=200 else assess(data,expected[case['name']])
                if status==200:
                    limits=data['limits'];checks.update(certificateEqual=data['dataQuality']['certificateSha256']==report['certificateSha256'],
                        resourcePolicyEqual=limits['queryTimeoutSeconds']==10 and limits['maxExecutionMemoryBytes']==2147483648 and limits['maxReturnRows']==10000 and limits['maxEstimatedScanRows']==100000000)
                ok=status==200 and all(checks.values())
                report['executions'].append(dict(case=case['name'],round=round_number+1,httpStatus=status,status='PASS' if ok else 'FAIL',checks=checks,
                    phase='timed',wallMillis=(time.monotonic()-start)*1000,timings=data.get('timings'),validationMillis=data.get('dataQuality',{}).get('validationMillis'),
                    diagnosticTimings=data.get('dataQuality',{}).get('diagnosticTimings'),queryProfile=data.get('queryProfile'),limits=data.get('limits'),artifact=filename))
                persist();print(f"{case['name']} round {round_number+1} {'PASS' if ok else 'FAIL'} {status}",flush=True)
                if args.explain and round_number==0:
                    with tempfile.TemporaryDirectory(prefix='window-plans-') as temp:
                        path=Path(temp)/'query.dsl';path.write_text(case['dsl'],encoding='utf-8')
                        completed=subprocess.run([args.java,'-Dfile.encoding=UTF-8','-Dsun.stdout.encoding=UTF-8','-Dsun.stderr.encoding=UTF-8','-cp',str(args.jar.resolve()),str(ROOT/'scripts/doris/ProjectPlanExplain.java'),f'jdbc:mysql://{host}:{client.query_port}/newzl',reader,str(path)],env=env,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=50)
                        if completed.returncode:raise RuntimeError('Read-only plan capture failed: '+redact(completed.stderr))
                        (folder/(filename[:-5]+'-plans.json')).write_text(completed.stdout,encoding='utf-8')
                if not ok and not args.baseline:raise AssertionError(case['name'])
        check('artifacts-unchanged',digest(args.jar)==report['jarSha256'] and digest(args.certificate)==report['certificateSha256']
              and digest(ROOT/'scripts/doris/project_matrix_reference.py')==report['oracleSha256'] and digest(Path(__file__))==report['runnerSha256'])
        if args.field_oracle:check('field-oracle-unchanged',digest(ROOT/'scripts/doris/project_field_reference.py')==report['fieldOracleSha256'])
        if args.oracle_module:check('combination-oracle-unchanged',digest(ROOT/'scripts/doris'/(args.oracle_module+'.py'))==report['combinationOracleSha256'])
    except Exception as error:report['fatalError']=redact(error);raise
    finally:
        cleanup=[]
        if server is not None:
            try:
                if server.poll() is None:server.terminate()
                server.wait(timeout=10)
            except Exception as error:cleanup.append(redact(error))
        if account:
            try:client.query(f"DROP USER '{reader}'")
            except Exception as error:cleanup.append(redact(error))
        capture_preservation(report, source_state, environment)
        report.update(cleanup='FAILED' if cleanup else 'DONE',cleanupErrors=cleanup,completedAtUtc=datetime.now(timezone.utc).isoformat())
        report['status']='PASS' if not cleanup and not report['preservationErrors'] and 'fatalError' not in report and len(report['executions'])==len(suite)*args.rounds and all(e['status']=='PASS' and e['checks'] for e in report['executions']) else 'FAIL'
        report['passed']=sum(e['status']=='PASS' for e in report['executions']);report['total']=len(report['executions']);persist()
    print(json.dumps({k:report[k] for k in ['status','passed','total']}))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
