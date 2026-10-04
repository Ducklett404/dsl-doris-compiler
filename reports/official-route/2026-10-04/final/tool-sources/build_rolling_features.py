"""Build strict observed-row MA features and prove incremental append equals full history."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid
from build_history_features import registry_metadata

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris,sql_literal
WINDOWS=(20,60,120,250)
PRICE_FIELDS=('closePrice','highPrice','lowPrice')
RANGE_FIELDS={key:{'sourceExpression':'b.'+field,'period':250,'currentField':key+'_current',
    'minField':key+'_min250','maxField':key+'_max250'} for key,field in [('high','highPrice'),('low','lowPrice')]}


def averages_sql(source,date,windows=WINDOWS,ranges=RANGE_FIELDS):
    fields=[]
    for n in windows:
        frame=f'(PARTITION BY b.mktcode,b.tgtcode ORDER BY b.bizdate ROWS BETWEEN {n-1} PRECEDING AND CURRENT ROW)'
        fields.append(f'CASE WHEN COUNT(b.closePrice) OVER {frame}={n} THEN AVG(b.closePrice) OVER {frame} ELSE NULL END AS ma{n}')
    for r in ranges.values():
        frame='(PARTITION BY b.mktcode,b.tgtcode ORDER BY b.bizdate ROWS BETWEEN 249 PRECEDING AND CURRENT ROW)'
        fields.append(r['sourceExpression']+' AS '+r['currentField'])
        for fn,col in [('MIN','minField'),('MAX','maxField')]:
            fields.append(f"CASE WHEN COUNT({r['sourceExpression']}) OVER {frame}=250 THEN {fn}({r['sourceExpression']}) OVER {frame} ELSE NULL END AS {r[col]}")
    return f"SELECT * FROM (SELECT b.mktcode,b.tgtcode,b.bizdate,{','.join(fields)} FROM {source} b WHERE b.bizdate<={sql_literal(date)}) w WHERE bizdate={sql_literal(date)}"


def tail_sql(source,date,keep=249):
    return f"SELECT mktcode,tgtcode,bizdate,{','.join(PRICE_FIELDS)} FROM (SELECT b.mktcode,b.tgtcode,b.bizdate,{','.join('b.'+f for f in PRICE_FIELDS)},ROW_NUMBER() OVER(PARTITION BY b.mktcode,b.tgtcode ORDER BY b.bizdate DESC) AS rn FROM {source} b WHERE b.bizdate<={sql_literal(date)}) t WHERE rn<={keep}"


def delta_source(source,tail,previous,date):
    return f"(SELECT mktcode,tgtcode,bizdate,{','.join(PRICE_FIELDS)} FROM {tail} UNION ALL SELECT b.mktcode,b.tgtcode,b.bizdate,{','.join('b.'+f for f in PRICE_FIELDS)} FROM {source} b WHERE b.bizdate>{sql_literal(previous)} AND b.bizdate<={sql_literal(date)})"


def bounded_source(source,date,keep=250):
    return f"(SELECT mktcode,tgtcode,bizdate,{','.join(PRICE_FIELDS)} FROM (SELECT b.mktcode,b.tgtcode,b.bizdate,{','.join('b.'+f for f in PRICE_FIELDS)},ROW_NUMBER() OVER(PARTITION BY b.mktcode,b.tgtcode ORDER BY b.bizdate DESC) rn FROM {source} b WHERE b.bizdate<={sql_literal(date)}) observed WHERE rn<={keep})"


def feature_ddl(table,dates):
    partitions=','.join(f"PARTITION p{d.replace('-','')} VALUES LESS THAN ('{(datetime.date.fromisoformat(d)+datetime.timedelta(days=1)).isoformat()}')" for d in dates)
    return f"""CREATE TABLE {table}(snapshot_id VARCHAR(128) NOT NULL,manifest_sha256 VARCHAR(64) NOT NULL,
      registry_fingerprint VARCHAR(64) NOT NULL,bizdate DATE NOT NULL,mktcode INT NOT NULL,tgtcode VARCHAR(64) NOT NULL,
      {','.join(f'ma{n} DOUBLE NULL' for n in WINDOWS)},
      {','.join(r[f]+' DOUBLE NULL' for r in RANGE_FIELDS.values() for f in ['currentField','minField','maxField'])})
      UNIQUE KEY(snapshot_id,manifest_sha256,registry_fingerprint,bizdate,mktcode,tgtcode)
      PARTITION BY RANGE(bizdate)({partitions}) DISTRIBUTED BY HASH(mktcode,tgtcode) BUCKETS 4
      PROPERTIES('replication_num'='1','enable_unique_key_merge_on_write'='true')"""


def verification_sql(table,source,date,identity,windows=WINDOWS,ranges=RANGE_FIELDS):
    guards=' AND '.join(f'f.{key}={sql_literal(value)}' for key,value in identity.items())
    differences=[f'((f.ma{n} IS NULL)!=(w.ma{n} IS NULL)) OR ABS(f.ma{n}-w.ma{n})>1e-10*GREATEST(1,ABS(w.ma{n}))' for n in windows]
    for r in ranges.values():
        for col in ('currentField','minField','maxField'):
            differences.append(f"NOT(f.{r[col]} <=> w.{r[col]})")
    wrong=' OR '.join(differences)
    return f"WITH reference AS ({averages_sql(source,date,windows,ranges)}), feature AS(SELECT f.* FROM {table} f WHERE f.bizdate={sql_literal(date)} AND {guards}) SELECT COUNT(*) FROM reference w FULL OUTER JOIN feature f ON w.mktcode=f.mktcode AND w.tgtcode=f.tgtcode WHERE w.mktcode IS NULL OR f.mktcode IS NULL OR {wrong}"


def rows_digest(rows):return hashlib.sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--snapshot-id',default='stock-20060104-20260414-v1')
    parser.add_argument('--dates',nargs='+',default=['2026-04-10','2026-04-13','2026-04-14'])
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    folder=args.output_dir.resolve();folder.mkdir(parents=True,exist_ok=True)
    if any((folder/n).exists() for n in ('catalog.json','build-report.json')):raise ValueError('Use a fresh directory')
    manifest_path=ROOT/'data/doris/snapshots'/args.snapshot_id/'manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    dates=sorted(set(datetime.date.fromisoformat(d).isoformat() for d in args.dates))
    basic=manifest['files']['hsj_stock_hq_basic']
    if not dates or dates[0]<basic['dateMin'] or dates[-1]>basic['dateMax']:raise ValueError('Dates outside immutable snapshot')
    meta=registry_metadata();expr=meta['metrics']['close']['sourceExpression']
    if expr!='b.closePrice':raise ValueError('Builder needs the compiler closePrice expression')
    client=WslDoris(args.distribution,'dsl-doris-official');original=client.query('SELECT * FROM newzl.data_snapshot_registry')
    if original:raise ValueError('Expected the unregistered diagnostic source')
    counts={k:int(v) for k,v in client.query("SELECT 'hsj_stock_code_info',COUNT(*) FROM newzl.hsj_stock_code_info UNION ALL SELECT 'hsj_stock_hq_basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'hsj_stock_hq_ext',COUNT(*) FROM newzl.hsj_stock_hq_ext")}
    if counts!={k:v['rows'] for k,v in manifest['files'].items()}:raise ValueError('Source counts changed')
    database='dsl_rolling_diag_'+uuid.uuid4().hex[:12];table=database+'.rolling_averages_v1'
    catalog={'formatVersion':'rolling-average-v1','snapshotId':args.snapshot_id,
        'manifestSha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),'registryFingerprint':meta['registryFingerprint'],
        'qualifiedTable':table,'sourceExpression':expr,'completeDates':{},'windowFields':{n:f'ma{n}' for n in WINDOWS},'rangeFields':RANGE_FIELDS}
    identity={'snapshot_id':catalog['snapshotId'],'manifest_sha256':catalog['manifestSha256'],'registry_fingerprint':catalog['registryFingerprint']}
    report={'purpose':'DIAGNOSTIC_ONLY','acceptanceEligible':False,'status':'BUILDING','snapshotId':args.snapshot_id,
        'jarSha256':hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest(),
        'manifestSha256':catalog['manifestSha256'],'registryFingerprint':meta['registryFingerprint'],'database':database,
        'sourceCounts':counts,'nullPolicy':'COUNT(non-NULL closePrice)=N over exactly N observed rows; otherwise NULL',
        'incrementalPolicy':'immutable snapshot; retain all securities last 249 observed rows including NULL; append all new rows; never calendar-truncate',
        'floatTolerance':'absolute difference <= 1e-10 * max(1, abs(reference))','dates':[]}
    created=False;ready=False;previous=None;tail=None
    try:
        client.query('CREATE DATABASE '+database);created=True
        ddl=feature_ddl(table,dates);client.query(ddl);(folder/'create-table.sql').write_text(ddl+';\n',encoding='utf-8')
        for index,date in enumerate(dates):
            source=bounded_source(meta['sourceTable'],date) if previous is None else delta_source(meta['sourceTable'],tail,previous,date)
            old_digest=rows_digest(client.query(f"SELECT * FROM {table} ORDER BY bizdate,mktcode,tgtcode"))
            value_fields=[f'ma{n}' for n in WINDOWS]+[r[f] for r in RANGE_FIELDS.values() for f in ['currentField','minField','maxField']]
            sql=f"INSERT INTO {table} SELECT {','.join(sql_literal(v) for v in identity.values())},a.bizdate,a.mktcode,a.tgtcode,{','.join('a.'+f for f in value_fields)} FROM ({averages_sql(source,date)}) a"
            (folder/f'build-{date}.sql').write_text(sql+';\n',encoding='utf-8');start=time.perf_counter();client.query(sql);elapsed=time.perf_counter()-start
            old_after=rows_digest(client.query(f"SELECT * FROM {table} WHERE bizdate<{sql_literal(date)} ORDER BY bizdate,mktcode,tgtcode"))
            if old_digest!=old_after:raise ValueError('Previously built features changed')
            actual=int(client.query(f'SELECT COUNT(*) FROM {table} WHERE bizdate={sql_literal(date)}')[0][0])
            expected=int(client.query(f'SELECT COUNT(*) FROM {meta["sourceTable"]} WHERE bizdate={sql_literal(date)}')[0][0])
            if actual!=expected:raise ValueError('Incomplete feature coverage')
            differences=0;checks=[]
            for name,selected_windows,selected_ranges in [(f'ma{n}',(n,),{}) for n in WINDOWS]+[(key,(),{key:r}) for key,r in RANGE_FIELDS.items()]:
                verify=verification_sql(table,meta['sourceTable'],date,identity,selected_windows,selected_ranges)
                (folder/f'verify-{date}-{name}.sql').write_text(verify+';\n',encoding='utf-8')
                count=int(client.query(verify)[0][0]);differences+=count;checks.append({'fieldGroup':name,'differences':count})
            if differences:raise ValueError('Incremental features differ from full ordered history')
            next_tail=database+f'.tail_{index}'
            client.query(f"CREATE TABLE {next_tail}(mktcode INT NOT NULL,tgtcode VARCHAR(64) NOT NULL,bizdate DATE NOT NULL,{','.join(f+' DOUBLE NULL' for f in PRICE_FIELDS)}) UNIQUE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(mktcode,tgtcode) BUCKETS 4 PROPERTIES('replication_num'='1','enable_unique_key_merge_on_write'='true')")
            tail_build=f'INSERT INTO {next_tail} '+tail_sql(source,date)
            (folder/f'tail-{date}.sql').write_text(tail_build+';\n',encoding='utf-8');client.query(tail_build)
            tail_rows=int(client.query(f'SELECT COUNT(*) FROM {next_tail}')[0][0])
            max_rows=int(client.query(f'SELECT COALESCE(MAX(n),0) FROM (SELECT COUNT(*) n FROM {next_tail} GROUP BY mktcode,tgtcode) s')[0][0])
            if max_rows>249 or int(client.query(f'SELECT COUNT(*) FROM {next_tail} WHERE bizdate>{sql_literal(date)}')[0][0]):raise ValueError('Invalid incremental tail')
            catalog['completeDates'][date]=actual
            report['dates'].append({'date':date,'mode':'FULL' if previous is None else 'INCREMENTAL',
                'rows':actual,'expectedRows':expected,'fullWindowDifferences':differences,'previousFeaturesUnchanged':True,
                'fullHistoryChecks':checks,
                'previousFeaturesDigest':old_digest,'tailRows':tail_rows,'maxTailRowsPerSecurity':max_rows,
                'buildSecondsIncludingWslTransport':elapsed})
            print(f'{date}: {actual} rows, {report["dates"][-1]["mode"]}, 10 fields match full history',flush=True)
            previous=date;tail=next_tail
        client.query('ANALYZE TABLE '+table+' WITH SYNC')
        if client.query('SELECT * FROM newzl.data_snapshot_registry')!=original:raise ValueError('Source registry changed')
        tmp=folder/'catalog.pending.json';tmp.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(folder/'catalog.json')
        ready=True;report.update(status='PASS',lastDate=previous,tailTable=tail,catalogSha256=hashlib.sha256((folder/'catalog.json').read_bytes()).hexdigest())
    except Exception as error:report.update(status='FAIL',error=str(error));raise
    finally:
        if created and not ready:
            if not re.fullmatch(r'dsl_rolling_diag_[0-9a-f]{12}',database):raise ValueError('Unowned database')
            client.query('DROP DATABASE '+database);report['failedBuildCleanup']='DONE'
        report['officialRegistryUnchanged']=client.query('SELECT * FROM newzl.data_snapshot_registry')==original
        report['completedAtUtc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (folder/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
