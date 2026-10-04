"""Compare MA feature, complete windows and identity fallbacks with hand-labelled histories."""
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
sys.path.insert(0,str(ROOT/'scripts/accuracy'));sys.path.insert(0,str(ROOT/'scripts/doris'))
from run_correctness import WslDoris,compile_case,bind_sql,sql_literal
from build_history_features import registry_metadata
from build_rolling_features import feature_ddl,WINDOWS,RANGE_FIELDS


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wsl',action='store_true')
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'reports/official-route/2026-10-04')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    path=ROOT/'accuracy/fixtures/rolling-averages-v1.json';fixture=json.loads(path.read_text(encoding='utf-8'))
    anchor=datetime.date.fromisoformat(fixture['date']);rows=[]
    for key,history in fixture['histories'].items():
        market,code=key.split(':');end=anchor-datetime.timedelta(days=history.get('missingCurrent',False))
        for i in range(history['rows']):
            value=history.get('constant') if 'constant' in history else history['start']+i*history['step']
            if history.get('nullFromEnd')==history['rows']-i:value=None
            date=end-datetime.timedelta(days=(history['rows']-1-i)*history.get('intervalDays',1))
            rows.append((int(market),code,date.isoformat(),value))
    rows.extend(tuple(r) for r in fixture['futureRows']);meta=registry_metadata();identity=('rolling-hand-v1','e'*64,meta['registryFingerprint'])
    date=fixture['date'];feature_rows=[]
    for market,code in sorted({r[:2] for r in rows if r[2]==date}):
        values=[r[3] for r in sorted(rows,key=lambda r:r[2]) if r[:2]==(market,code) and r[2]<=date]
        averages=[sum(values[-n:])/n if len(values)>=n and all(v is not None for v in values[-n:]) else None for n in WINDOWS]
        extrema=[v for v in values[-250:] if v is not None]
        low=min(extrema) if len(values)>=250 and len(extrema)==250 else None
        high=max(extrema) if len(values)>=250 and len(extrema)==250 else None
        feature_rows.append((*identity,date,market,code,*averages,values[-1],low,high,values[-1],low,high))
    catalog={'formatVersion':'rolling-average-v1','snapshotId':identity[0],'manifestSha256':identity[1],
        'registryFingerprint':identity[2],'qualifiedTable':'newzl.rolling_averages_v1','sourceExpression':'b.closePrice',
        'completeDates':{date:len(feature_rows)},'windowFields':{n:f'ma{n}' for n in WINDOWS},'rangeFields':RANGE_FIELDS}
    output={'authority':fixture['authority'],'fixtureSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'jarSha256':hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest(),
        'engine':'Apache Doris' if args.wsl else 'SQLite','results':[]}
    con=None;client=None;database=None;created=False
    try:
        if args.wsl:
            client=WslDoris(args.distribution,'dsl-doris-official');original=client.query('SELECT * FROM newzl.data_snapshot_registry')
            database='dsl_rolling_fixture_'+uuid.uuid4().hex[:12];client.query('CREATE DATABASE '+database);created=True
            client.query(f"CREATE TABLE {database}.v_hsj_stock_hq_basic(mktcode INT NOT NULL,tgtcode VARCHAR(64) NOT NULL,bizdate DATE NOT NULL,closePrice DOUBLE,highPrice DOUBLE,lowPrice DOUBLE) UNIQUE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(tgtcode) BUCKETS 1 PROPERTIES('replication_num'='1')")
            client.query(f'INSERT INTO {database}.v_hsj_stock_hq_basic VALUES '+','.join('('+','.join(sql_literal(v) for v in (*r,r[3],r[3]))+')' for r in rows))
            catalog['qualifiedTable']=database+'.rolling_averages_v1';client.query(feature_ddl(catalog['qualifiedTable'],[date]))
            client.query('INSERT INTO '+catalog['qualifiedTable']+' VALUES '+','.join('('+','.join(sql_literal(v) for v in r)+')' for r in feature_rows))
            output['fixtureDatabase']=database
        else:
            con=sqlite3.connect(':memory:');con.execute("ATTACH DATABASE ':memory:' AS newzl")
            con.execute('CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INT,tgtcode TEXT,bizdate TEXT,closePrice REAL,highPrice REAL,lowPrice REAL)')
            con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?,?,?)',[( *r,r[3],r[3]) for r in rows])
            con.execute('CREATE TABLE newzl.rolling_averages_v1(snapshot_id TEXT,manifest_sha256 TEXT,registry_fingerprint TEXT,bizdate TEXT,mktcode INT,tgtcode TEXT,ma20 REAL,ma60 REAL,ma120 REAL,ma250 REAL,high_current REAL,high_min250 REAL,high_max250 REAL,low_current REAL,low_min250 REAL,low_max250 REAL)')
            con.executemany('INSERT INTO newzl.rolling_averages_v1 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',feature_rows)
        with tempfile.TemporaryDirectory(prefix='rolling-averages-') as directory:
            config=Path(directory)/'catalog.json';config.write_text(json.dumps(catalog),encoding='utf-8')
            for case in fixture['cases']:
                def call(metric):return f"indicator('{case.get('market','')}', '', '{metric}', '{date}', '', '', '{case.get('count','')}')"
                dsl=case['expression'];dsl=re.sub(r'MA(\d+)',lambda m:call(m.group(1)+'日均线'),dsl).replace('CLOSE',call('收盘价'))
                for marker,function,metric,period in [('HIGH120','record_high','最高价',120),('HIGH','record_high','最高价',250),('LOW','record_low','最低价',250)]:
                    dsl=dsl.replace(marker,f"{function}('{case.get('market','')}', '', '{metric}', '{period}日', '{date}', '', '', '')")
                record={'id':case['id'],'dsl':dsl,'paths':{}}
                expected=[(int(k.split(':')[0]),k.split(':')[1]) for k in case['expected']]
                for mode in ('FULL_SCAN_REFERENCE','MATERIALIZED','WRONG_SNAPSHOT','WRONG_MANIFEST','NO_MANIFEST'):
                    try:
                        artifact=compile_case('java',ROOT/'target/dsl-doris-compiler.jar',dsl,Path(directory)/'case.dsl',
                            access_path='FULL_SCAN_REFERENCE' if mode=='FULL_SCAN_REFERENCE' else 'OPTIMIZED',rolling_features=config,
                            snapshot_id='other' if mode=='WRONG_SNAPSHOT' else identity[0],
                            manifest_sha256=None if mode=='NO_MANIFEST' else 'f'*64 if mode=='WRONG_MANIFEST' else identity[1])
                        actual=([(int(m),c) for m,c in client.query(bind_sql(artifact['sql'],artifact['bindings']).replace('newzl.',database+'.'))]
                            if client else con.execute(artifact['sql'],artifact['bindings']).fetchall())
                        feature=any(n['kind']=='RollingFeatureScan' for n in artifact['logicalPlan'])
                        record['paths'][mode]={'status':'PASS' if actual==expected and feature==(mode=='MATERIALIZED' and case.get('feature',True)) else 'FAIL',
                            'actual':actual,'expected':expected,'feature':feature,'sql':artifact['sql'],'bindings':artifact['bindings']}
                    except Exception as error:record['paths'][mode]={'status':'ERROR','error':str(error)}
                record['status']='PASS' if all(p['status']=='PASS' for p in record['paths'].values()) else 'FAIL'
                output['results'].append(record);print(case['id']+': '+record['status'],flush=True)
    finally:
        if con:con.close()
        if created:
            if not re.fullmatch(r'dsl_rolling_fixture_[0-9a-f]{12}',database):raise ValueError('Unowned fixture')
            client.query('DROP DATABASE '+database);output['fixtureCleanup']='DONE'
            output['officialRegistryUnchanged']=client.query('SELECT * FROM newzl.data_snapshot_registry')==original
        output['total']=len(output['results']);output['passed']=sum(r['status']=='PASS' for r in output['results'])
        (args.output_dir/('doris-rolling-boundaries.json' if args.wsl else 'portable-rolling-boundaries.json')).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if output['passed']==output['total']==len(fixture['cases']) else 1


if __name__=='__main__':sys.exit(main())
