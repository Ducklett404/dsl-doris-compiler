"""Run real Doris execution tests on a disposable, independently validated synthetic dataset."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris,sql_literal

REQUIRED_CASES={
    'com.acme.dorisdsl.DorisExplainIntegrationTest':{'dorisExplainsLayeredRsiSql'},
    'com.acme.dorisdsl.stockslot.DorisControlledExecutionIntegrationTest':{
        'executesRealPreparedSelectOnTheValidatedSyntheticDataset',
        'returnCapIsEnforcedAndResultResourcesRemainUsable',
        'unvalidatedAndInjectedSnapshotIdsAreRejectedThenAnotherThreadCanExecute',
        'scanLimitRejectsBeforeExecutionAndReleasesTheQueueSlot',
        'accountsWithWritePrivilegeCannotInitializeTheExecutor',
        'queuedRequestTimesOutWhileFirstRequestHoldsTheSlotAndBothRecover',
        'realDatabaseTimeoutMapsToTimeoutAndTheNextRequestRecovers'}}
REQUIRED_SUITES={name:len(cases) for name,cases in REQUIRED_CASES.items()}


def summarize_required_junit(folder):
    report=dict(status='FAIL',tests=0,passed=0,failures=0,errors=0,skipped=0,suites=[])
    try:
        for name,expected_count in REQUIRED_SUITES.items():
            path=Path(folder)/('TEST-'+name+'.xml')
            suite=ET.parse(path).getroot()
            if suite.tag!='testsuite' or suite.attrib.get('name')!=name:
                raise ValueError('Unexpected required JUnit suite')
            nodes=suite.findall('testcase')
            names=[node.attrib.get('name') for node in nodes]
            if len(nodes)!=expected_count or set(names)!=REQUIRED_CASES[name] or len(names)!=len(set(names)):
                raise ValueError('Required test methods missing, duplicated or replaced')
            counts={key:int(suite.attrib[key]) for key in ('tests','failures','errors','skipped')}
            actual=dict(tests=len(nodes),failures=sum(node.find('failure') is not None for node in nodes),
                        errors=sum(node.find('error') is not None for node in nodes),
                        skipped=sum(node.find('skipped') is not None for node in nodes))
            if counts!=actual or any(node.attrib.get('classname')!=name for node in nodes):
                raise ValueError('JUnit counters / testcase class identity disagree')
            cases=[dict(name=node.attrib['name'],status='SKIP' if node.find('skipped') is not None else
                   'FAIL' if node.find('failure') is not None else 'ERROR' if node.find('error') is not None else 'PASS') for node in nodes]
            report['suites'].append(dict(name=name,**counts,testcases=cases))
            for key in actual:report[key]+=actual[key]
        report['passed']=sum(c['status']=='PASS' for suite in report['suites'] for c in suite['testcases'])
        if report['tests']==8 and report['passed']==8 and report['failures']==report['errors']==report['skipped']==0:
            report['status']='PASS'
    except (OSError,ValueError,KeyError,ET.ParseError) as error:
        report['error']=str(error)
    return report


def verify_test_environment():
    # Fail before creating a fixture or running Java when the chosen environment is incomplete.
    if sys.version_info < (3,11):raise RuntimeError('Python 3.11+ required; use the configured Python 3.12 test environment')
    dependencies=subprocess.run([sys.executable,'-c','import duckdb,openpyxl'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if dependencies.returncode:raise RuntimeError('Chosen Python environment needs scripts/doris/requirements-selftest.txt dependencies: '+dependencies.stderr.strip())


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/continuation/2026-10-04')
    parser.add_argument('--maven',default=str(ROOT/'.tools/apache-maven-3.9.16/bin/mvn.cmd'))
    parser.add_argument('--maven-repository',default='.mvn-cache')
    parser.add_argument('--junit-only',action='store_true',help='Prepare the same isolated fixture but run only the eight formerly skipped JUnit integration tests')
    args=parser.parse_args(argv)
    verify_test_environment()
    if args.report_dir.exists():raise FileExistsError('Use a new report directory; preserve earlier evidence')
    if not Path(args.maven).is_file():raise FileNotFoundError('Provide the installed Maven executable with --maven')
    args.report_dir.mkdir(parents=True,exist_ok=False)
    client=WslDoris(args.distribution,'dsl-doris-official')
    original_registry=client.query('SELECT * FROM newzl.data_snapshot_registry')
    if original_registry:raise RuntimeError('Expected the existing diagnostic instance with no official validated snapshot')
    source_identity_sql="""SELECT 'basic',COUNT(*),MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_basic
        UNION ALL SELECT 'extension',COUNT(*),MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_ext
        UNION ALL SELECT 'code',COUNT(*),NULL,NULL FROM newzl.hsj_stock_code_info ORDER BY 1"""
    view_identity_sql="SELECT TABLE_NAME,SHA2(VIEW_DEFINITION,256) FROM information_schema.views WHERE TABLE_SCHEMA='newzl' ORDER BY TABLE_NAME"
    original_sources=client.query(source_identity_sql)
    original_views=client.query(view_identity_sql)
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
        'testScope':'REQUIRED_EIGHT_JUNIT_ONLY' if args.junit_only else 'UNIFIED_PLUS_PRECISION_CLI_HTTP',
        'distribution':args.distribution,'ports':{'query':client.query_port,'feHttp':client.fe_http_port,'beHttp':client.be_http_port},
        'originalSourcesBefore':original_sources,'originalViewsBefore':original_views,
        'startedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'checks':checks,'testTransportNotes':[
            'Queue contention pauses a test-only JDBC transport; successful SELECTs execute actual generated SQL.',
            'Timeout transport runs SELECT SLEEP(4) once under the actual JDBC timeout; it is not a DSL capability.']}
    def evidence_source_hash():
        paths=sorted([*ROOT.glob('pom.xml'),*(ROOT/'src/main').rglob('*.java'),
            *(ROOT/'src/main/antlr4').rglob('*.g4'),*(ROOT/'src/main/resources').rglob('*'),
            *(ROOT/'src/test').rglob('*Doris*IntegrationTest.java')])
        return hashlib.sha256(''.join(str(p.relative_to(ROOT))+'\0'+hashlib.sha256(p.read_bytes()).hexdigest()+'\n'
            for p in paths if p.is_file()).encode()).hexdigest()
    def class_hash(folder):
        return hashlib.sha256(''.join(str(p.relative_to(ROOT))+'\0'+hashlib.sha256(p.read_bytes()).hexdigest()+'\n'
            for p in sorted((ROOT/folder).rglob('*.class'))).encode()).hexdigest()
    report['sourceSha256']=evidence_source_hash()
    report['runnerSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['compilerJarBeforeSha256']=hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest()
    previous=args.report_dir/'previous-required-junit';previous.mkdir()
    for name in REQUIRED_SUITES:
        old=ROOT/'target/surefire-reports'/('TEST-'+name+'.xml')
        if old.is_file():shutil.copy2(old,previous/old.name)
    report['previousRequiredJunit']=summarize_required_junit(previous)

    def record(name,condition,**evidence):
        checks.append({'name':name,'status':'PASS' if condition else 'FAIL',**evidence})
        if not condition:raise AssertionError(name)

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
        environment.update(DORIS_JDBC_URL=f'jdbc:mysql://{host}:{client.query_port}/{database}?useSSL=false&allowPublicKeyRetrieval=true&connectTimeout=5000&socketTimeout=15000',
            DORIS_JDBC_USER=reader,DORIS_JDBC_PASSWORD=reader_password,DORIS_FIXTURE_REGISTRY=str(registry_path),
            DORIS_FIXTURE_SNAPSHOT_ID=snapshot,DORIS_WRITER_USER=writer,DORIS_WRITER_PASSWORD=writer_password,
            DORIS_SCREEN_TEST_REGISTRY=str(screen_path),DORIS_SCREEN_TEST_CATALOG=str(catalog_path),
            DSL_FIXTURE_PASSWORD=reader_password,DSL_FIXTURE_TOKEN=token)
        print('Running real JDBC tests with isolated synthetic data',flush=True)
        launched_ns=time.time_ns()
        with (args.report_dir/'unified-integration.log').open('wb') as output:
            if args.junit_only:
                command=[args.maven,'-B','--no-transfer-progress','-o',
                    '-Dmaven.repo.local='+str((ROOT/args.maven_repository).resolve()),
                    '-Dtest=DorisExplainIntegrationTest,DorisControlledExecutionIntegrationTest',
                    '-Dtest.jvm.args=-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets','test']
            else:
                command=['pwsh','-NoProfile','-File',str(ROOT/'scripts/test-all.ps1'),
                '-MavenExecutable',args.maven,'-MavenRepository',args.maven_repository,'-Offline',
                '-PythonExecutable',sys.executable,
                '-TestJvmArgs','-Djdk.net.unixdomain.tmpdir=target/disabled-unix-sockets']
            tested=subprocess.run(command,cwd=ROOT,env=environment,stdout=output,stderr=subprocess.STDOUT,timeout=600)
        junit_dir=args.report_dir/'required-junit';junit_dir.mkdir()
        for name in REQUIRED_SUITES:
            path=ROOT/'target/surefire-reports'/('TEST-'+name+'.xml')
            if not path.is_file() or path.stat().st_mtime_ns<launched_ns:
                raise RuntimeError('No fresh JUnit XML for '+name)
            text=path.read_text(encoding='utf-8')
            for secret in (reader_password,writer_password,token):text=text.replace(secret,'[REDACTED]')
            (junit_dir/path.name).write_text(text,encoding='utf-8')
        required=summarize_required_junit(junit_dir)
        report['requiredJunit']=required
        (args.report_dir/'required-eight-result.json').write_text(json.dumps(required,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        record('required-eight-real-jdbc-tests',tested.returncode==0 and required['status']=='PASS',
            exitCode=tested.returncode,tests=required['tests'],passed=required['passed'],skipped=required['skipped'],
            failures=required['failures'],errors=required['errors'])
        if not args.junit_only:record('unified-real-jdbc-tests',tested.returncode==0,exitCode=tested.returncode)
        if args.junit_only:
            report['compilerJarAfterSha256']=hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest()
            report['compiledClassesSha256']=class_hash('target/classes')
            report['compiledTestClassesSha256']=class_hash('target/test-classes')
            report['compilerJarUsedForTests']=False
            record('existing-compiler-jar-preserved',report['compilerJarAfterSha256']==report['compilerJarBeforeSha256'])
            record('official-snapshot-registry-preserved',client.query('SELECT * FROM newzl.data_snapshot_registry')==original_registry)
            return 0
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
            connection=['--host',host,'--port',str(client.query_port),'--database',database,'--user',reader,'--password-env','DSL_FIXTURE_PASSWORD',
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
        raise RuntimeError(report['error']) from None
    finally:
        cleanup_errors=[]
        try:stop_server()
        except Exception as error:cleanup_errors.append('HTTP server: '+str(error))
        for name in users:
            try:
                if not re.fullmatch(r'dsl_fixture_(read|write)_[0-9a-f]{12}',name):raise RuntimeError('Invalid owned fixture user')
                client.query(f"DROP USER '{name}'")
                remaining=client.query('SHOW ALL GRANTS')
                if any(name in row[0] for row in remaining):raise RuntimeError('Created fixture user still exists')
            except Exception as error:cleanup_errors.append(name+': '+str(error))
        if created_database:
            try:
                if not re.fullmatch(r'dsl_executor_fixture_[0-9a-f]{12}',database):raise RuntimeError('Invalid owned fixture database name')
                client.query('DROP DATABASE '+database)
                if client.query('SHOW DATABASES LIKE '+sql_literal(database)):raise RuntimeError('Created fixture database still exists')
            except Exception as error:cleanup_errors.append(database+': '+str(error))
        try:
            report['originalSourcesAfter']=client.query(source_identity_sql)
            report['originalViewsAfter']=client.query(view_identity_sql)
            if report['originalSourcesAfter']!=original_sources or report['originalViewsAfter']!=original_views:
                cleanup_errors.append('Original source count / date / semantic view identity changed')
            if client.query('SELECT * FROM newzl.data_snapshot_registry')!=original_registry:
                cleanup_errors.append('Original snapshot registry changed')
        except Exception as error:cleanup_errors.append('Source preservation verification: '+str(error))
        try:
            report['sourceAfterSha256']=evidence_source_hash()
            report['runnerAfterSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            if report['sourceAfterSha256']!=report['sourceSha256'] or report['runnerAfterSha256']!=report['runnerSha256']:
                cleanup_errors.append('Compiler/test sources or integration runner changed during the run')
            log=args.report_dir/'unified-integration.log'
            if log.exists():
                log_text=log.read_text(encoding='utf-8',errors='replace')
                for secret in (reader_password,writer_password,token):log_text=log_text.replace(secret,'[REDACTED]')
                log.write_text(log_text,encoding='utf-8')
        except Exception as error:cleanup_errors.append('Evidence identity / sanitization: '+str(error))
        report['fixtureCleanup']='FAILED' if cleanup_errors else 'DONE'
        report['cleanupErrors']=[str(e).replace(reader_password,'[REDACTED]').replace(writer_password,'[REDACTED]').replace(token,'[REDACTED]') for e in cleanup_errors]
        report['passed']=sum(item['status']=='PASS' for item in checks);report['total']=len(checks)
        report['status']='PASS' if checks and 'error' not in report and not cleanup_errors and report['passed']==report['total'] else 'FAIL'
        report['completedAtUtc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (args.report_dir/'integration-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':report['status'],'passed':report['passed'],'total':report['total']}),flush=True)
        if cleanup_errors:raise RuntimeError('Fixture cleanup / source preservation failed; see new report')
    return 0


if __name__=='__main__':raise SystemExit(main())
