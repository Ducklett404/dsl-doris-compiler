"""Verify read-only credentials and real CLI/HTTP refusal of an unvalidated snapshot."""
import argparse
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
from run_correctness import WslDoris


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--host',help='Doris address reachable from Windows; defaults to the WSL IPv4 address')
    parser.add_argument('--java',help='Direct Java executable, avoiding Windows launcher forwarding processes')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/route-implementation/2026-10-04')
    args=parser.parse_args()
    if args.java is None:
        runtime=subprocess.run(['java','-XshowSettings:properties','-version'],
            text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=15)
        home=re.search(r'^\s*java.home\s*=\s*(.+)$',runtime.stderr,re.MULTILINE)
        if runtime.returncode or home is None:raise RuntimeError('Cannot locate the active Java runtime')
        args.java=str(Path(home.group(1).strip())/'bin'/('java.exe' if os.name=='nt' else 'java'))
    args.report_dir.mkdir(parents=True,exist_ok=True)
    admin=WslDoris(args.distribution,'dsl-doris-official')
    if args.host is None:
        address=subprocess.run(['wsl.exe','-d',args.distribution,'--exec','hostname','-I'],
            text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=15)
        candidates=[item for item in address.stdout.split() if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}',item)]
        if address.returncode or not candidates:raise RuntimeError('Cannot determine the WSL IPv4 address')
        args.host=candidates[0]
    if admin.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry')!=[('0',)]:
        raise RuntimeError('This negative test requires the diagnostic instance with an empty registry')
    reader='dsl_gate_'+secrets.token_hex(6)
    password=secrets.token_hex(24)
    token=secrets.token_hex(32)
    records=[]
    report={'purpose':'DIAGNOSTIC_NEGATIVE_GATE_TEST','host':args.host,'checks':records}
    server=None
    created=False

    def check(name,condition,**evidence):
        records.append({'name':name,'status':'PASS' if condition else 'FAIL',**evidence})
        if not condition:raise AssertionError(name)

    def request(address,path,body=None,authenticated=False):
        headers={'Content-Type':'application/json'}
        if authenticated:headers['Authorization']='Bearer '+token
        data=None if body is None else json.dumps(body).encode('utf-8')
        try:
            with urllib.request.urlopen(urllib.request.Request(address+path,data=data,headers=headers),timeout=10) as response:
                return response.status,json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())

    try:
        admin.query(f"CREATE USER '{reader}' IDENTIFIED BY '{password}'")
        created=True
        admin.query(f"GRANT SELECT_PRIV ON newzl.* TO '{reader}'")
        reader_command=admin.prefix+['exec','-i','-e','MYSQL_PWD='+password,'dsl-doris-official',
            'mysql','-h','127.0.0.1','-P',str(admin.query_port),'-u',reader,'--batch','--skip-column-names','--raw']
        selected=subprocess.run(reader_command,input='SELECT COUNT(*) FROM newzl.data_snapshot_registry;\n',
            text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=30)
        check('readonly-select',selected.returncode==0 and selected.stdout.strip()=='0')
        denied=subprocess.run(reader_command,input="INSERT INTO newzl.data_snapshot_registry SELECT '__gate_test_never_registered__','test','hash','TEST',NOW(),'negative test' WHERE FALSE;\n",
            text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=30)
        check('readonly-write-denied',denied.returncode!=0 and ('denied' in denied.stderr.lower() or 'LOAD_PRIV' in denied.stderr),
            exitCode=denied.returncode,message='\n'.join(line for line in denied.stderr.splitlines() if 'ERROR' in line).replace(password,'[REDACTED]'))
        with tempfile.TemporaryDirectory(prefix='doris-execution-gate-') as directory:
            temp=Path(directory)
            dsl="indicator('', '', '收盘价', '2026-04-14', '', '', '') > 1"
            source=temp/'query.dsl';source.write_text(dsl,encoding='utf-8')
            environment=os.environ.copy()
            environment['DSL_GATE_PASSWORD']=password
            environment['DSL_GATE_TOKEN']=token
            java=[args.java,'-Dfile.encoding=UTF-8','-Dsun.stdout.encoding=UTF-8','-Dsun.stderr.encoding=UTF-8',
                '-Djdk.net.unixdomain.tmpdir='+str(temp/'nonexistent-socket-directory'),
                '-jar',str(ROOT/'target/dsl-doris-compiler.jar')]
            database=['--host',args.host,'--port',str(admin.query_port),'--user',reader,'--password-env','DSL_GATE_PASSWORD']
            executed=subprocess.run(java+['execute-stock-slot-sql',str(source)]+database,
                env=environment,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=30)
            check('cli-unvalidated-snapshot-rejected',executed.returncode==3 and
                'Required VALIDATED Doris snapshot is not registered' in executed.stderr,
                exitCode=executed.returncode,message=executed.stderr.strip().replace(password,'[REDACTED]'))
            output=temp/'server.log'
            with output.open('wb') as stream:
                server=subprocess.Popen(java+['serve-doris']+database+['--http-port','0','--auth-token-env','DSL_GATE_TOKEN'],
                    env=environment,stdout=stream,stderr=subprocess.STDOUT)
                address=None;deadline=time.monotonic()+30
                while time.monotonic()<deadline and server.poll() is None:
                    match=re.search(r'Listening on (http://127\.0\.0\.1:\d+)',output.read_text(encoding='utf-8',errors='replace'))
                    if match:address=match.group(1);break
                    time.sleep(.1)
                check('readonly-http-service-starts',address is not None,
                    startupReported=address is not None)
                status,body=request(address,'/health')
                check('http-health',status==200,httpStatus=status)
                payload={'dsl':dsl,'snapshotId':'stock-20060104-20260414-v1'}
                status,body=request(address,'/execute',payload)
                check('http-authentication',status==401,httpStatus=status)
                status,body=request(address,'/execute',payload,True)
                check('http-unvalidated-snapshot-rejected',status==503 and body.get('category')=='data_unavailable',
                    httpStatus=status,category=body.get('category'))
                server.terminate();server.wait(timeout=10);server=None
                check('http-process-released',True)
        check('registry-remains-empty',admin.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry')==[('0',)])
    except Exception as error:
        report['error']=str(error).replace(password,'[REDACTED]').replace(token,'[REDACTED]')
        raise
    finally:
        if server is not None and server.poll() is None:
            server.terminate();server.wait(timeout=10)
        if created:admin.query(f"DROP USER '{reader}'")
        report['passed']=sum(item['status']=='PASS' for item in records)
        report['total']=len(records)
        report['status']='PASS' if records and 'error' not in report and report['passed']==report['total'] else 'FAIL'
        (args.report_dir/'controlled-execution-gate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':report['status'],'passed':report['passed'],'total':report['total']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
