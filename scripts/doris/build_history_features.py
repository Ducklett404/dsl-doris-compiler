"""Publish complete extrema in a new owned diagnostic namespace, preserving source gates."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris, sql_literal


def registry_metadata():
    result = subprocess.run(['java', '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8',
        '-cp', str(ROOT/'target/dsl-doris-compiler.jar'), str(ROOT/'scripts/doris/HistoryFeatureRegistry.java')],
        capture_output=True, text=True, encoding='utf-8', timeout=30)
    if result.returncode: raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def feature_ddl(table, dates, metrics):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*', table): raise ValueError('Unsafe table')
    fields = [m[field] for m in metrics.values() for field in ('currentField','minField','maxField')]
    if len(set(fields)) != len(fields) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',f) for f in fields):
        raise ValueError('Invalid feature fields')
    partitions = ','.join(f"PARTITION p{date.replace('-','')} VALUES LESS THAN ('{(datetime.date.fromisoformat(date)+datetime.timedelta(days=1)).isoformat()}')" for date in sorted(dates))
    return f"""CREATE TABLE {table} (
      snapshot_id VARCHAR(128) NOT NULL, manifest_sha256 VARCHAR(64) NOT NULL,
      registry_fingerprint VARCHAR(64) NOT NULL, bizdate DATE NOT NULL,
      mktcode INT NOT NULL, tgtcode VARCHAR(64) NOT NULL,
      {','.join(f'{field} DOUBLE NULL' for field in fields)}
    ) UNIQUE KEY(snapshot_id,manifest_sha256,registry_fingerprint,bizdate,mktcode,tgtcode)
    PARTITION BY RANGE(bizdate) ({partitions})
    DISTRIBUTED BY HASH(mktcode,tgtcode) BUCKETS 4
    PROPERTIES('replication_num'='1','enable_unique_key_merge_on_write'='true')"""


def aggregate_select(source, date, metrics):
    columns = []
    for metric in metrics.values():
        expr = metric['sourceExpression']
        # Expressions come from the validated compiler registry, never user SQL templates.
        if not re.fullmatch(r'b\.[A-Za-z_][A-Za-z0-9_]*', expr): raise ValueError('Unsupported build expression')
        columns.extend([f"MAX(CASE WHEN b.bizdate={sql_literal(date)} THEN {expr} END) AS {metric['currentField']}",
            f"MIN({expr}) AS {metric['minField']}", f"MAX({expr}) AS {metric['maxField']}"])
    return f"SELECT b.mktcode,b.tgtcode,{','.join(columns)} FROM {source} b WHERE b.bizdate<={sql_literal(date)} GROUP BY b.mktcode,b.tgtcode HAVING MAX(CASE WHEN b.bizdate={sql_literal(date)} THEN 1 ELSE 0 END)=1"


def window_verification_sql(table, source, date, catalog):
    columns = []; fields = []
    for metric in catalog['metrics'].values():
        expr = metric['sourceExpression']; current=metric['currentField']; minimum=metric['minField']; maximum=metric['maxField']
        fields.extend([current,minimum,maximum])
        columns.extend([f'{expr} AS {current}',
            f'MIN({expr}) OVER (PARTITION BY b.mktcode,b.tgtcode ORDER BY b.bizdate ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS {minimum}',
            f'MAX({expr}) OVER (PARTITION BY b.mktcode,b.tgtcode ORDER BY b.bizdate ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS {maximum}'])
    guard = ' AND '.join(f'h.{key}={sql_literal(catalog[key])}' for key in ('snapshot_id','manifest_sha256','registry_fingerprint'))
    mismatches = ' OR '.join(f'NOT(f.{field} <=> w.{field})' for field in fields)
    return f"""WITH history AS (
      SELECT b.mktcode,b.tgtcode,b.bizdate,{','.join(columns)} FROM {source} b WHERE b.bizdate<={sql_literal(date)}
    ), current_reference AS (SELECT * FROM history WHERE bizdate={sql_literal(date)}),
    feature AS (SELECT h.* FROM {table} h WHERE h.bizdate={sql_literal(date)} AND {guard})
    SELECT COUNT(*) FROM current_reference w FULL OUTER JOIN feature f ON w.mktcode=f.mktcode AND w.tgtcode=f.tgtcode
    WHERE w.mktcode IS NULL OR f.mktcode IS NULL OR {mismatches}"""


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--snapshot-id',default='stock-20060104-20260414-v1')
    parser.add_argument('--dates',nargs='+',default=['2026-04-13','2026-04-14'])
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(); folder=args.output_dir.resolve(); folder.mkdir(parents=True,exist_ok=True)
    if (folder/'catalog.json').exists() or (folder/'build-report.json').exists(): raise ValueError('Use a fresh report directory')
    manifest_path=ROOT/'data/doris/snapshots'/args.snapshot_id/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    dates=sorted(set(datetime.date.fromisoformat(d).isoformat() for d in args.dates))
    metadata=registry_metadata(); client=WslDoris(args.distribution,'dsl-doris-official')
    original_registry=client.query('SELECT * FROM newzl.data_snapshot_registry')
    if original_registry: raise ValueError('Expected an unregistered diagnostic source')
    counts={name:int(count) for name,count in client.query("SELECT 'hsj_stock_code_info',COUNT(*) FROM newzl.hsj_stock_code_info UNION ALL SELECT 'hsj_stock_hq_basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'hsj_stock_hq_ext',COUNT(*) FROM newzl.hsj_stock_hq_ext")}
    if counts!={k:v['rows'] for k,v in manifest['files'].items()}: raise ValueError('Source row counts changed')
    database='dsl_history_diag_'+uuid.uuid4().hex[:12]; table=database+'.history_extrema_v1'
    report={'purpose':'HISTORICAL_EXTREMA_DIAGNOSTIC','acceptanceEligible':False,'snapshotId':args.snapshot_id,
        'manifestSha256':manifest_hash,'registryFingerprint':metadata['registryFingerprint'],
        'sourceTable':metadata['sourceTable'],'database':database,'sourceCounts':counts,
        'jarSha256':hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest(),
        'status':'BUILDING','dates':[]}
    catalog={'formatVersion':'history-extrema-v1','snapshotId':args.snapshot_id,'manifestSha256':manifest_hash,
        'registryFingerprint':metadata['registryFingerprint'],'qualifiedTable':table,'completeDates':{},'metrics':metadata['metrics']}
    guard={'snapshot_id':args.snapshot_id,'manifest_sha256':manifest_hash,'registry_fingerprint':metadata['registryFingerprint'],'metrics':metadata['metrics']}
    created=False; ready=False
    try:
        client.query('CREATE DATABASE '+database); created=True
        ddl=feature_ddl(table,dates,metadata['metrics']);(folder/'create-table.sql').write_text(ddl+';\n',encoding='utf-8');client.query(ddl)
        for date in dates:
            sql=f"INSERT INTO {table} SELECT {sql_literal(args.snapshot_id)},{sql_literal(manifest_hash)},{sql_literal(metadata['registryFingerprint'])},{sql_literal(date)},a.* FROM ({aggregate_select(metadata['sourceTable'],date,metadata['metrics'])}) a"
            (folder/f'build-{date}.sql').write_text(sql+';\n',encoding='utf-8')
            start=time.perf_counter();client.query(sql);elapsed=time.perf_counter()-start
            actual=int(client.query(f'SELECT COUNT(*) FROM {table} WHERE bizdate={sql_literal(date)}')[0][0])
            expected=int(client.query(f'SELECT COUNT(*) FROM {metadata["sourceTable"]} WHERE bizdate={sql_literal(date)}')[0][0])
            if actual!=expected:raise ValueError('Incomplete feature date '+date)
            verification=window_verification_sql(table,metadata['sourceTable'],date,guard)
            (folder/f'verify-{date}.sql').write_text(verification+';\n',encoding='utf-8')
            differences=int(client.query(verification)[0][0])
            if differences:raise ValueError('Feature values differ from complete ordered windows')
            catalog['completeDates'][date]=actual
            report['dates'].append({'date':date,'rows':actual,'expectedCurrentRows':expected,'windowValueDifferences':differences,'buildSecondsIncludingWslTransport':elapsed})
            print(f'{date}: {actual} rows, 9 fields verified, build {elapsed:.3f}s',flush=True)
        client.query('ANALYZE TABLE '+table+' WITH SYNC')
        if client.query('SELECT * FROM newzl.data_snapshot_registry')!=original_registry:raise ValueError('Source registry changed')
        # Publish last; failed or partial builds cannot be selected through a catalog.
        temporary=folder/'catalog.pending.json';temporary.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.replace(folder/'catalog.json');ready=True;report['status']='PASS'
        report['publishedCatalogSha256']=hashlib.sha256((folder/'catalog.json').read_bytes()).hexdigest()
    except Exception as error:
        report['status']='FAIL';report['error']=str(error)
        raise
    finally:
        if created and not ready:
            if not re.fullmatch(r'dsl_history_diag_[0-9a-f]{12}',database):raise ValueError('Unowned database')
            client.query('DROP DATABASE '+database);report['failedBuildCleanup']='DONE'
        report['officialRegistryUnchanged']=client.query('SELECT * FROM newzl.data_snapshot_registry')==original_registry
        report['completedAtUtc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (folder/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0


if __name__=='__main__':sys.exit(main())
