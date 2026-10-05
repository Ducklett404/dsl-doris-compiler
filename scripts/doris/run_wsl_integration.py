"""Run real Doris execution tests on a disposable, independently validated synthetic dataset."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris,sql_literal


def verify_test_environment():
    # Fail before creating a fixture or running Java when the chosen environment is incomplete.
    if sys.version_info < (3,11):raise RuntimeError('Python 3.11+ required; use the configured Python 3.12 test environment')
    dependencies=subprocess.run([sys.executable,'-c','import duckdb,openpyxl'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if dependencies.returncode:raise RuntimeError('Chosen Python environment needs scripts/doris/requirements-selftest.txt dependencies: '+dependencies.stderr.strip())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/continuation/2026-10-04')
    parser.add_argument('--maven',default=str(ROOT/'.tools/apache-maven-3.9.16/bin/mvn.cmd'))
    parser.add_argument('--maven-repository',default='.mvn-cache')
    args=parser.parse_args()
    verify_test_environment()
    args.report_dir.mkdir(parents=True,exist_ok=True)
    client=WslDoris(args.distribution,'dsl-doris-official')
    original_registry=client.query('SELECT * FROM newzl.data_snapshot_registry')
    if original_registry:raise RuntimeError('Expected the existing diagnostic instance with no official validated snapshot')
    address=subprocess.run(['wsl.exe','-d',args.distribution,'--exec','hostname','-I'],
        encoding='utf-8',errors='replace',text=True,capture_output=True,timeout=15)
    candidates=[item for item in address.stdout.split() if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}',item)]
    if address.returncode or not candidates:raise RuntimeError('Cannot resolve the WSL IPv4 address')
    host=candidates[0]
    runtime=subprocess.run(['java','-XshowSettings:properties','-version'],
        encoding='utf-8',errors='replace',text=True,capture_output=True,timeout=15)
    java_home=re.search(r'^\s*java.home\s*=\s*(.+)$',runtime.stderr,re.MULTILINE)
    if runtime.returncode or java_home is None:raise RuntimeError('Cannot locate the Java runtime')
    java=str(Path(java_home.group(1).strip())/'bin/java.exe')
    suffix=secrets.token_hex(6);database='dsl_executor_fixture_'+suffix
    reader='dsl_fixture_read_'+suffix;writer='dsl_fixture_write_'+suffix
    reader_password=secrets.token_hex(24);writer_password=secrets.token_hex(24);token=secrets.token_hex(32)
    snapshot='synthetic-execution-'+suffix
    checks=[];created_database=False;users=[];server=None
    report={'purpose':'SYNTHETIC_REAL_DORIS_INTEGRATION_NOT_OFFICIAL_ACCEPTANCE',
        'fixtureDatabase':database,'snapshotId':snapshot,'originalOfficialRegistryRows':len(original_registry),
        'checks':checks,'testTransportNotes':[
            'Queue contention pauses a test-only JDBC transport; successful SELECTs execute actual generated SQL.',
            'Timeout transport runs SELECT SLEEP(4) once under the actual JDBC timeout; it is not a DSL capability.']}

    def record(name,passed,**evidence):
        checks.append({'name':name,'status':'PASS' if passed else 'FAIL',**evidence})
        if not passed:raise AssertionError(name)

    def insert(table,values):
        if values:client.query(f'INSERT INTO {database}.{table} VALUES '+','.join(
            '('+','.join(sql_literal(value) for value in row)+')' for row in values))

    def request(url,path,payload=None,authenticated=True):
        headers={'Content-Type':'application/json'}
        if authenticated:headers['Authorization']='Bearer '+token
        body=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
        try:
            with urllib.request.urlopen(urllib.request.Request(url+path,data=body,headers=headers),timeout=15) as response:
                data=response.read().decode('utf-8');content=response.headers.get('Content-Type','')
                return response.status,json.loads(data) if 'json' in content else data
        except urllib.error.HTTPError as error:
            data=error.read().decode('utf-8')
            return error.code,json.loads(data)

    def stop_server():
        nonlocal server
        if server is not None:
            server.terminate();server.wait(timeout=10);server=None

    try:
        client.query('CREATE DATABASE '+database);created_database=True
        client.query(f"CREATE TABLE {database}.v_hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR(64),bizdate DATE,closePrice DOUBLE,openPrice DOUBLE,highPrice DOUBLE,lowPrice DOUBLE,volume BIGINT) UNIQUE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1')")
        client.query(f"CREATE TABLE {database}.v_hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR(64),bizdate DATE,ZJLXMainNetTur BIGINT) UNIQUE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1')")
        client.query(f"CREATE TABLE {database}.hsj_stock_code_info(mktcode INT,tgtcode VARCHAR(64),name VARCHAR(128),hyBlkRefName VARCHAR(64)) UNIQUE KEY(mktcode,tgtcode) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1')")
        client.query(f"CREATE TABLE {database}.data_snapshot_registry(snapshot_id VARCHAR(96),contract_version VARCHAR(16),manifest_sha256 CHAR(64),status VARCHAR(16),loaded_at DATETIME,note VARCHAR(1024)) UNIQUE KEY(snapshot_id) DISTRIBUTED BY HASH(snapshot_id) BUCKETS 1 PROPERTIES('replication_num'='1')")
        basic=[];extension=[];codes=[]
        prices=[2,3,4,5,None,.5]
        end=datetime.date(2026,4,14)
        for index,price in enumerate(prices,1):
            code=f'{index:06}';codes.append((1,code,'合成证券'+code,'合成行业'))
            for age in range(2,-1,-1):
                date=(end-datetime.timedelta(days=age)).isoformat()
                basic.append((1,code,date,price,price,None if price is None else price+1,
                    None if price is None else price-.2,100))
                extension.append((1,code,date,index*10))
        insert('v_hsj_stock_hq_basic',basic);insert('v_hsj_stock_hq_ext',extension);insert('hsj_stock_code_info',codes)
        checks_sql=f"""SELECT
            (SELECT COUNT(*) FROM {database}.v_hsj_stock_hq_basic),
            (SELECT COUNT(*) FROM {database}.v_hsj_stock_hq_ext),
            (SELECT COUNT(*) FROM {database}.hsj_stock_code_info),
            (SELECT COUNT(*) FROM {database}.v_hsj_stock_hq_ext e LEFT ANTI JOIN {database}.v_hsj_stock_hq_basic b USING(mktcode,tgtcode,bizdate)),
            (SELECT COUNT(*) FROM {database}.v_hsj_stock_hq_basic WHERE closePrice<0 OR highPrice<lowPrice),
            (SELECT COUNT(*) FROM (SELECT mktcode,tgtcode,bizdate FROM {database}.v_hsj_stock_hq_basic GROUP BY mktcode,tgtcode,bizdate) keys_)"""
        verified=client.query(checks_sql)
        record('synthetic-source-validation',verified==[('18','18','6','0','0','18')],actual=verified)
        fixture={'kind':'SYNTHETIC_TEST_DATA','snapshotId':snapshot,'contractVersion':'fixture-v1',
            'basic':basic,'extension':extension,'codes':codes,'expectedSelection':['000001','000002','000003','000004']}
        data_text=json.dumps(fixture,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
        (args.report_dir/'fixture-data.json').write_text(data_text,encoding='utf-8')
        manifest_hash=hashlib.sha256(data_text.encode('utf-8')).hexdigest()
        client.query(f"INSERT INTO {database}.data_snapshot_registry VALUES ({sql_literal(snapshot)},'fixture-v1','{manifest_hash}','VALIDATED',NOW(),'synthetic fixture; checked counts, keys, price range and relationship'),('fixture-pending','fixture-v1','{manifest_hash}','PENDING',NOW(),'negative test')")
        client.query(f'ANALYZE TABLE {database}.v_hsj_stock_hq_basic WITH SYNC')
        # Compatibility mode needs its own quote and observed-calendar tables.
        client.query(f"CREATE TABLE {database}.dwd_quote_daily(symbol VARCHAR(32),trade_date DATE,close DOUBLE,close_qfq DOUBLE) UNIQUE KEY(symbol,trade_date) DISTRIBUTED BY HASH(symbol) BUCKETS 1 PROPERTIES('replication_num'='1')")
        client.query(f"CREATE TABLE {database}.dim_trade_calendar(market VARCHAR(8),cal_date DATE,is_open INT) UNIQUE KEY(market,cal_date) DISTRIBUTED BY HASH(market) BUCKETS 1 PROPERTIES('replication_num'='1')")
        legacy_end=datetime.date(2026,8,7)
        insert('dwd_quote_daily',[('SYNTHETIC',(legacy_end-datetime.timedelta(days=age)).isoformat(),30-age,30-age) for age in range(15,-1,-1)])
        insert('dim_trade_calendar',[('CN',(legacy_end-datetime.timedelta(days=age)).isoformat(),1) for age in range(15,-1,-1)])
        registry=json.loads((ROOT/'src/main/resources/stock-slot-registry-v1.json').read_text(encoding='utf-8'))
        for table in registry['tables'].values():table['qualifiedName']=database+'.'+table['qualifiedName'].split('.')[-1]
        registry_path=args.report_dir/'fixture-stock-registry.json'
        registry_path.write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        screen_registry=json.loads((ROOT/'src/main/resources/registry.json').read_text(encoding='utf-8'))
        for key,value in screen_registry['datasets'].items():
            if isinstance(value,str) and '.' in value:screen_registry['datasets'][key]=database+'.'+value.split('.')[-1]
        screen_path=args.report_dir/'fixture-screen-registry.json'
        screen_path.write_text(json.dumps(screen_registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        catalog=json.loads((ROOT/'src/main/resources/catalog-snapshot.json').read_text(encoding='utf-8'))
        for key,value in catalog['tables'].items():catalog['tables'][key]=database+'.'+value.split('.')[-1]
        catalog_path=args.report_dir/'fixture-screen-catalog.json'
        catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        for name,password,privileges in ((reader,reader_password,'SELECT_PRIV'),(writer,writer_password,'SELECT_PRIV,LOAD_PRIV')):
            client.query(f"CREATE USER '{name}' IDENTIFIED BY '{password}'");users.append(name)
            client.query(f"GRANT {privileges} ON {database}.* TO '{name}'")
        environment=os.environ.copy()
        environment.update(DORIS_JDBC_URL=f'jdbc:mysql://{host}:9030/{database}?useSSL=false&allowPublicKeyRetrieval=true&connectTimeout=5000&socketTimeout=15000',
            DORIS_JDBC_USER=reader,DORIS_JDBC_PASSWORD=reader_password,DORIS_FIXTURE_REGISTRY=str(registry_path),
            DORIS_FIXTURE_SNAPSHOT_ID=snapshot,DORIS_WRITER_USER=writer,DORIS_WRITER_PASSWORD=writer_password,
            DORIS_SCREEN_TEST_REGISTRY=str(screen_path),DORIS_SCREEN_TEST_CATALOG=str(catalog_path),
            DSL_FIXTURE_PASSWORD=reader_password,DSL_FIXTURE_TOKEN=token)
        print('Running complete self-test with real JDBC and isolated synthetic data',flush=True)
        with (args.report_dir/'unified-integration.log').open('wb') as output:
            tested=subprocess.run(['pwsh','-NoProfile','-File',str(ROOT/'scripts/test-all.ps1'),
                '-MavenExecutable',args.maven,'-MavenRepository',args.maven_repository,'-Offline',
                '-PythonExecutable',sys.executable,
                '-TestJvmArgs','-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets'],
                cwd=ROOT,env=environment,stdout=output,stderr=subprocess.STDOUT,timeout=600)
        record('unified-real-jdbc-tests',tested.returncode==0,exitCode=tested.returncode)
        report['compilerJarSha256']=hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest()
        precision_output=args.report_dir/'numeric-precision-boundaries.json'
        with (args.report_dir/'numeric-precision-boundaries.log').open('wb') as output:
            precision=subprocess.run([sys.executable,str(ROOT/'scripts/doris/check_precision_regressions.py'),
                '--distribution',args.distribution,'--java',java,'--output',str(precision_output)],
                cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=300)
        precision_report=json.loads(precision_output.read_text(encoding='utf-8')) if precision_output.exists() else {}
        record('numeric-precision-boundaries',precision.returncode==0 and precision_report.get('status')=='PASS'
            and precision_report.get('fixtureCleanup')=='DONE',exitCode=precision.returncode,
            precisionPassed=precision_report.get('passed'),precisionTotal=precision_report.get('total'))
        with tempfile.TemporaryDirectory(prefix='doris-positive-integration-') as directory:
            temporary=Path(directory);source=temporary/'query.dsl'
            dsl="indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1"
            source.write_text(dsl,encoding='utf-8')
            java_command=[java,'-Dfile.encoding=UTF-8','-Dsun.stdout.encoding=UTF-8','-Dsun.stderr.encoding=UTF-8',
                '-Djdk.net.unixdomain.tmpdir='+str(temporary/'nonexistent-sockets'),'-jar',str(ROOT/'target/dsl-doris-compiler.jar')]
            connection=['--host',host,'--database',database,'--user',reader,'--password-env','DSL_FIXTURE_PASSWORD',
                '--registry',str(registry_path),'--max-return-rows','2']
            executed=subprocess.run(java_command+['execute-stock-slot-sql',str(source),'--snapshot-id',snapshot]+connection,
                env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            result=json.loads(executed.stdout) if executed.returncode==0 else {}
            record('cli-positive-with-return-cap',executed.returncode==0 and len(result.get('rows',[]))==2 and result.get('truncated') is True,
                exitCode=executed.returncode,rows=len(result.get('rows',[])),truncated=result.get('truncated'))
            (args.report_dir/'synthetic-cli-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            for scan_limit in ('10000','1'):
                with (temporary/'server.log').open('wb') as output:
                    server=subprocess.Popen(java_command+['serve-doris']+connection+['--http-port','0',
                        '--auth-token-env','DSL_FIXTURE_TOKEN','--max-scan-rows',scan_limit],
                        env=environment,stdout=output,stderr=subprocess.STDOUT)
                    endpoint=None;deadline=time.monotonic()+30
                    while time.monotonic()<deadline and server.poll() is None:
                        match=re.search(r'Listening on (http://127\.0\.0\.1:\d+)',(temporary/'server.log').read_text(encoding='utf-8',errors='replace'))
                        if match:endpoint=match.group(1);break
                        time.sleep(.1)
                    record('http-starts-scan-limit-'+scan_limit,endpoint is not None)
                    payload={'dsl':dsl,'snapshotId':snapshot,'maxRows':100}
                    if scan_limit=='1':
                        status,body=request(endpoint,'/execute',payload)
                        record('http-scan-limit-rejected',status==429 and body.get('category')=='security_limit',httpStatus=status)
                    else:
                        status,body=request(endpoint,'/execute',payload,False)
                        record('http-auth-required',status==401,httpStatus=status)
                        status,body=request(endpoint,'/execute',payload)
                        record('http-positive-with-return-cap',status==200 and len(body.get('rows',[]))==2 and body.get('truncated') is True,
                            httpStatus=status,rows=len(body.get('rows',[])))
                        status,body=request(endpoint,'/execute',{**payload,'format':'markdown'})
                        record('http-markdown-output',status==200 and isinstance(body,str) and '| ' in body,httpStatus=status)
                        (args.report_dir/'synthetic-http-result.md').write_text(body,encoding='utf-8')
                        for name,alteration,expected in (('pending-snapshot',{'snapshotId':'fixture-pending'},503),
                            ('syntax-error',{'dsl':'indicator('},400),('semantic-error',{'dsl':dsl.replace('收盘价','不存在的指标')},422),
                            ('invalid-return-limit',{'maxRows':0},400)):
                            status,body=request(endpoint,'/execute',{**payload,**alteration})
                            record('http-'+name,status==expected,httpStatus=status)
                        status,body=request(endpoint,'/execute',payload)
                        record('http-recovers-after-errors',status==200,httpStatus=status)
                    status,body=request(endpoint,'/health')
                    record('http-remains-healthy-'+scan_limit,status==200,httpStatus=status)
                    stop_server()
        record('official-snapshot-registry-preserved',client.query('SELECT * FROM newzl.data_snapshot_registry')==original_registry)
    except Exception as error:
        report['error']=str(error).replace(reader_password,'[REDACTED]').replace(writer_password,'[REDACTED]').replace(token,'[REDACTED]')
        raise
    finally:
        stop_server()
        for name in users:client.query(f"DROP USER '{name}'")
        if created_database:
            if not re.fullmatch(r'dsl_executor_fixture_[0-9a-f]{12}',database):raise RuntimeError('Invalid owned fixture database name')
            client.query('DROP DATABASE '+database)
        report['fixtureCleanup']='DONE'
        report['passed']=sum(item['status']=='PASS' for item in checks);report['total']=len(checks)
        report['status']='PASS' if checks and 'error' not in report and report['passed']==report['total'] else 'FAIL'
        (args.report_dir/'integration-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':report['status'],'passed':report['passed'],'total':report['total']}),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
