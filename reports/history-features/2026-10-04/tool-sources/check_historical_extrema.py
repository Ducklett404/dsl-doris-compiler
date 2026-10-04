"""Compare both generated paths with hand-labelled extrema, including SQL NULL cases."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import compile_case, bind_sql, sql_literal, WslDoris
sys.path.insert(0,str(ROOT/'scripts/doris'))
from build_history_features import registry_metadata, feature_ddl


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--wsl',action='store_true')
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'reports/history-features/2026-10-04')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    path=ROOT/'accuracy/fixtures/historical-extrema-v1.json'
    fixture=json.loads(path.read_text(encoding='utf-8'));rows=[];codes=[]
    anchor=datetime.date.fromisoformat(fixture['date'])
    for key,values in fixture['histories'].items():
        market,code=key.split(':');end=anchor-datetime.timedelta(days=key in fixture['missingCurrent'])
        industry=fixture.get('industries',{}).get(key,'行业A' if int(code)%2 else '行业B')
        codes.append((int(market),code,'合成证券'+code,industry))
        for index,value in enumerate(values):
            date=end-datetime.timedelta(days=len(values)-1-index)
            rows.append((int(market),code,date.isoformat(),value))
    rows.extend(tuple(row) for row in fixture['futureRows'])
    metadata=registry_metadata(); snapshot='hand-labelled-history-v1';manifest='a'*64
    dates=[(anchor-datetime.timedelta(days=1)).isoformat(),anchor.isoformat()]
    feature_rows=[]
    for date in dates:
        for market,code in sorted({(r[0],r[1]) for r in rows if r[2]==date}):
            current=next(r[3] for r in rows if r[:3]==(market,code,date))
            observed=[r[3] for r in rows if r[:2]==(market,code) and r[2]<=date and r[3] is not None]
            feature_rows.append((snapshot,manifest,metadata['registryFingerprint'],date,market,code,current,
                min(observed) if observed else None,max(observed) if observed else None))
    catalog={'formatVersion':'history-extrema-v1','snapshotId':snapshot,'manifestSha256':manifest,
        'registryFingerprint':metadata['registryFingerprint'],'qualifiedTable':'newzl.history_extrema_v1',
        'completeDates':{d:sum(r[3]==d for r in feature_rows) for d in dates},'metrics':{'close':metadata['metrics']['close']}}
    output={'authority':fixture['authority'],'fixtureSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'jarSha256':hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest(),
        'engine':'Apache Doris' if args.wsl else 'SQLite','results':[]}
    con=None;client=None;created=False;database=None
    try:
        if args.wsl:
            client=WslDoris(args.distribution,'dsl-doris-official')
            original_registry=client.query('SELECT * FROM newzl.data_snapshot_registry')
            database='dsl_extrema_fixture_'+uuid.uuid4().hex[:12]
            client.query('CREATE DATABASE '+database);created=True
            client.query(f"CREATE TABLE {database}.v_hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR(64),bizdate DATE,closePrice DOUBLE) UNIQUE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1')")
            client.query(f"CREATE TABLE {database}.hsj_stock_code_info(mktcode INT,tgtcode VARCHAR(64),name VARCHAR(128),hyBlkRefName VARCHAR(64)) UNIQUE KEY(mktcode,tgtcode) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1')")
            values=','.join('('+','.join(sql_literal(v) for v in row)+')' for row in rows)
            client.query(f'INSERT INTO {database}.v_hsj_stock_hq_basic VALUES '+values)
            values=','.join('('+','.join(sql_literal(v) for v in row)+')' for row in codes)
            client.query(f'INSERT INTO {database}.hsj_stock_code_info VALUES '+values)
            catalog['qualifiedTable']=database+'.history_extrema_v1'
            client.query(feature_ddl(catalog['qualifiedTable'],dates,catalog['metrics']))
            values=','.join('('+','.join(sql_literal(v) for v in row)+')' for row in feature_rows)
            client.query(f"INSERT INTO {catalog['qualifiedTable']} VALUES "+values)
            output['fixtureDatabase']=database
        else:
            con=sqlite3.connect(':memory:');con.execute("ATTACH DATABASE ':memory:' AS newzl")
            con.execute('CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INT,tgtcode TEXT,bizdate TEXT,closePrice REAL)')
            con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?)',rows)
            con.execute('CREATE TABLE newzl.hsj_stock_code_info(mktcode INT,tgtcode TEXT,name TEXT,hyBlkRefName TEXT)')
            con.executemany('INSERT INTO newzl.hsj_stock_code_info VALUES(?,?,?,?)',codes)
            con.execute('CREATE TABLE newzl.history_extrema_v1(snapshot_id TEXT,manifest_sha256 TEXT,registry_fingerprint TEXT,bizdate TEXT,mktcode INT,tgtcode TEXT,close_current REAL,close_min REAL,close_max REAL)')
            con.executemany('INSERT INTO newzl.history_extrema_v1 VALUES(?,?,?,?,?,?,?,?,?)',feature_rows)
        with tempfile.TemporaryDirectory(prefix='history-extrema-') as directory:
            catalog_path=Path(directory)/'catalog.json';catalog_path.write_text(json.dumps(catalog),encoding='utf-8')
            for case in fixture['cases']:
                date=case.get('date',fixture['date']);market=case.get('market','');count=case.get('count','');scope=case.get('scope','')
                def call(function):return f"{function}('{market}', '{scope}', '收盘价', '历史', '{date}', '', '', '{count}')"
                dsl=case['expression'].replace('HIGH',call('record_high')).replace('LOW',call('record_low'))
                record={'id':case['id'],'dsl':dsl,'paths':{}}
                try:
                    for mode in ('FULL_SCAN_REFERENCE','OPTIMIZED','MATERIALIZED','WRONG_SNAPSHOT','WRONG_MANIFEST','NO_MANIFEST'):
                        artifact=compile_case('java',ROOT/'target/dsl-doris-compiler.jar',dsl,Path(directory)/'case.dsl',
                            access_path='FULL_SCAN_REFERENCE' if mode=='FULL_SCAN_REFERENCE' else 'OPTIMIZED',
                            historical_features=catalog_path if mode not in ('FULL_SCAN_REFERENCE','OPTIMIZED') else None,
                            snapshot_id='other-snapshot' if mode=='WRONG_SNAPSHOT' else snapshot,
                            manifest_sha256=None if mode=='NO_MANIFEST' else 'b'*64 if mode=='WRONG_MANIFEST' else manifest)
                        actual=([(int(m),code) for m,code in client.query(bind_sql(artifact['sql'],artifact['bindings']).replace('newzl.',database+'.'))]
                            if client else con.execute(artifact['sql'],artifact['bindings']).fetchall())
                        expected=[tuple(row) for row in case['expected']]
                        aggregate='historical_extrema AS' in artifact['sql']
                        materialized=any(n['kind']=='HistoricalFeatureScan' for n in artifact['logicalPlan'])
                        expect_materialized=mode=='MATERIALIZED' and case.get('expectAggregate',True)
                        expect_aggregate=mode!='FULL_SCAN_REFERENCE' and not expect_materialized and case.get('expectAggregate',True)
                        correct=actual==expected and aggregate==expect_aggregate and materialized==expect_materialized
                        record['paths'][mode]={'status':'PASS' if correct else 'FAIL','actual':actual,'expected':expected,
                            'aggregate':aggregate,'materialized':materialized,'sql':artifact['sql'],'bindings':artifact['bindings']}
                    record['status']='PASS' if all(r['status']=='PASS' for r in record['paths'].values()) else 'FAIL'
                except Exception as error:record.update(status='ERROR',error=str(error))
                output['results'].append(record)
                print(case['id']+': '+record['status'],flush=True)
    finally:
        if con:con.close()
        if created:
            if not re.fullmatch(r'dsl_extrema_fixture_[0-9a-f]{12}',database):raise ValueError('Unowned fixture database')
            client.query('DROP DATABASE '+database)
            output['fixtureCleanup']='DONE'
            output['officialRegistryUnchanged']=client.query('SELECT * FROM newzl.data_snapshot_registry')==original_registry
        output['total']=len(output['results']);output['passed']=sum(r['status']=='PASS' for r in output['results'])
        filename='doris-historical-boundaries.json' if args.wsl else 'portable-historical-boundaries.json'
        (args.output_dir/filename).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if output['passed']==output['total']==len(fixture['cases']) else 1


if __name__=='__main__':sys.exit(main())
