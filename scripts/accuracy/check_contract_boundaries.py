"""Execute generated SQL on independent, hand-labelled boundary fixtures."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import compile_case, bind_sql


def rows(fixture):
    end=datetime.date.fromisoformat(fixture['date']);basic=[];extension=[]
    for code,values in fixture['histories'].items():
        for index,value in enumerate(values):
            date=(end-datetime.timedelta(days=len(values)-1-index)).isoformat()
            basic.append((fixture['market'],code,date,2.0))
            if value!='NO_EXTENSION_ROW':extension.append((fixture['market'],code,date,value))
    return basic,extension


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--wsl',action='store_true')
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'reports/route-implementation/2026-10-04')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    path=ROOT/'accuracy/fixtures/main-net-turnover-v1.json'
    fixture=json.loads(path.read_text(encoding='utf-8'));basic,ext=rows(fixture)
    output={'fixture':fixture['fixtureVersion'],'fixtureSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'authority':fixture['authority'],'engine':'Apache Doris' if args.wsl else 'SQLite','results':[]}
    con=None
    if args.wsl:
        prefix=['wsl.exe','-d',args.distribution,'--exec']
        inspected=subprocess.run(prefix+['docker','inspect','-f','{{index .Config.Labels "com.acme.dorisdsl.purpose"}}','dsl-doris-official'],
            capture_output=True,text=True,encoding='utf-8',errors='replace')
        if inspected.returncode or inspected.stdout.strip()!='official-data-diagnostic':
            raise ValueError('Refusing a container without the project diagnostic ownership label')
        database='dsl_contract_regression_'+uuid.uuid4().hex[:12]
        output['fixtureDatabase']=database
        command=prefix+['docker','exec','-i','dsl-doris-official','mysql',
            '--defaults-extra-file=/run/dsl-client.cnf','--batch','--skip-column-names','--raw']
        def query(sql):
            completed=subprocess.run(command,input=sql+';\n',capture_output=True,text=True,
                encoding='utf-8',errors='replace',timeout=60)
            if completed.returncode:raise RuntimeError(completed.stderr.strip())
            return [line.split('\t') for line in completed.stdout.splitlines() if line]
        query(f"CREATE DATABASE {database}; CREATE TABLE {database}.v_hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR(64),bizdate DATE,closePrice DOUBLE) UNIQUE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1'); CREATE TABLE {database}.v_hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR(64),bizdate DATE,ZJLXMainNetTur BIGINT) UNIQUE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1')")
        def sql_values(data):
            return ','.join('('+','.join('NULL' if v is None else str(v) if isinstance(v,(int,float)) else "'"+v.replace("'","''")+"'" for v in row)+')' for row in data)
        query(f'INSERT INTO {database}.v_hsj_stock_hq_basic VALUES '+sql_values(basic))
        query(f'INSERT INTO {database}.v_hsj_stock_hq_ext VALUES '+sql_values(ext))
    else:
        con=sqlite3.connect(':memory:');con.execute("ATTACH DATABASE ':memory:' AS newzl")
        con.execute('CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INT,tgtcode TEXT,bizdate TEXT,closePrice REAL)')
        con.execute('CREATE TABLE newzl.v_hsj_stock_hq_ext(mktcode INT,tgtcode TEXT,bizdate TEXT,ZJLXMainNetTur INTEGER)')
        con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?)',basic)
        con.executemany('INSERT INTO newzl.v_hsj_stock_hq_ext VALUES(?,?,?,?)',ext)
    try:
        with tempfile.TemporaryDirectory(prefix='contract-boundaries-') as temp:
            for case in fixture['cases']:
                record={'id':case['id']}
                try:
                    artifact=compile_case('java',ROOT/'target/dsl-doris-compiler.jar',case['dsl'],Path(temp)/'case.dsl')
                    actual=([(int(m),c) for m,c in query(bind_sql(artifact['sql'],artifact['bindings']).replace('newzl.',database+'.'))]
                        if args.wsl else con.execute(artifact['sql'],artifact['bindings']).fetchall())
                    expected={(fixture['market'],code) for code in case['expectedCodes']}
                    record.update(status='PASS' if set(actual)==expected else 'FAIL',actual=sorted(actual),expected=sorted(expected),sql=artifact['sql'],bindings=artifact['bindings'])
                except Exception as error:record.update(status='ERROR',error=str(error))
                output['results'].append(record)
    finally:
        if con:con.close()
        output['total']=len(output['results']);output['passed']=sum(row['status']=='PASS' for row in output['results'])
        name='doris-boundaries.json' if args.wsl else 'portable-boundaries.json'
        (args.output_dir/name).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"CONTRACT_BOUNDARIES: {output['passed']}/{output['total']} ({output['engine']})")
    return 0 if output['total']==len(fixture['cases']) and output['passed']==output['total'] else 1


if __name__=='__main__':raise SystemExit(main())
