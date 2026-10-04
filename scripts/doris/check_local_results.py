"""Diagnostic result differential on real CSVs; never a Doris acceptance result."""
from __future__ import annotations
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import duckdb

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts/accuracy"))
from run_correctness import compile_case, reference_sql, functions


def portable_identifiers(sql):
    """Change identifier quoting only, preserving SQL string literals."""
    result=[]; quoted=False; i=0
    while i<len(sql):
        char=sql[i]
        if char=="'":
            result.append(char)
            if quoted and i+1<len(sql) and sql[i+1]=="'":
                result.append("'");i+=2;continue
            quoted=not quoted
        else: result.append('"' if char=='`' and not quoted else char)
        i+=1
    return ''.join(result)


def indicator(metric,date,count='',agg=''):
    return f"indicator('', '', '{metric}', '{date}', '', '{agg}', '{count}')"


def python_expectations(con,evaluation_date):
    # Keep actual observed rows, including NULLs; select 61 rows per security.
    rows=con.execute("""WITH tail AS (
        SELECT mktcode,tgtcode,bizdate,closePx,openPx,highPx,lowPx,volume FROM newzl.hsj_stock_hq_basic
        WHERE bizdate<=CAST(? AS DATE)
        QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=61)
        SELECT t.*,NULLIF(e.ZJLXMainNetTur,-999999) net FROM tail t LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate)
        ORDER BY mktcode,tgtcode,bizdate""",[evaluation_date]).fetchall()
    histories=defaultdict(list)
    for market,code,date,close,opening,high,low,volume,net in rows:
        histories[(market,code)].append({'date':str(date),'close':None if close is None else Decimal(close)/10000,
            'open':None if opening is None else Decimal(opening)/10000,'high':None if high is None else Decimal(high)/10000,
            'low':None if low is None else Decimal(low)/10000,'volume':volume,'net':net})
    names=['MA60','MA5','RSI14','BETWEEN_MA5','CONS3_CLOSE','EXIST3_VOLUME','BOOLEAN_CONS3','CROSS_ABOVE','NET_SUM5','RANK_CLOSE']
    results={name:[] for name in names};current=[]
    for key,history in histories.items():
        if history[-1]['date']!=evaluation_date:continue
        close=[r['close'] for r in history]
        for n,name in [(60,'MA60'),(5,'MA5')]:
            if len(close)>=n and all(v is not None for v in close[-n:]):
                ma=sum(close[-n:])/n
                if ma>1:results[name].append(key)
                if n==5 and 2<=ma+1<=4:results['BETWEEN_MA5'].append(key)
        if len(close)>=15 and all(v is not None for v in close[-15:]):
            delta=[b-a for a,b in zip(close[-15:],close[-14:])]
            gain=sum(max(x,0) for x in delta);loss=sum(max(-x,0) for x in delta)
            if loss>0 and 100-100/(1+gain/loss)>50:results['RSI14'].append(key)
        if len(close)>=3 and all(v is not None and v>1 for v in close[-3:]):results['CONS3_CLOSE'].append(key)
        if len(history)>=20 and sum(r['volume'] is not None and r['volume']>0 for r in history[-20:])>=3:results['EXIST3_VOLUME'].append(key)
        if len(close)>=5:
            last=close[-5:]
            if all(v is not None for v in last) and all(last[i]==max(last[i-2:i+1]) for i in range(2,5)):
                results['BOOLEAN_CONS3'].append(key)
        if len(history)>=2:
            prev,now=history[-2:]
            if all(r[f] is not None for r in (prev,now) for f in ('open','close')) and now['close']>now['open'] and prev['close']<=prev['open']:
                results['CROSS_ABOVE'].append(key)
        if len(history)>=5 and all(r['net'] is not None for r in history[-5:]) and sum(r['net'] for r in history[-5:])>0:results['NET_SUM5'].append(key)
        if close[-1] is not None:current.append((key,close[-1]))
    top=sorted({value for _,value in current},reverse=True)[:3]
    ordered_rank=[key for key,value in sorted(current,key=lambda item:(-item[1],item[0])) if value in top]
    results={name:sorted(value) for name,value in results.items()}
    results['RANK_CLOSE']=ordered_rank
    return results


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path,default=ROOT/'target/data-audit/official.duckdb')
    parser.add_argument('--java',default='java')
    parser.add_argument('--manifest',type=Path,default=ROOT/'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json')
    parser.add_argument('--audit-report',type=Path,default=ROOT/'reports/data-inspection/2026-10-04/全量数据检查.json')
    parser.add_argument('--golden',type=Path,default=ROOT/'accuracy/golden/stock-slot-executable-v1.0.1.json')
    parser.add_argument('--evaluation-date')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/route-implementation/2026-10-04')
    parser.add_argument('--reference-output',type=Path,default=ROOT/'target/data-audit/reference-results-v1.0.1.json')
    args=parser.parse_args()
    folder=args.report_dir;folder.mkdir(parents=True,exist_ok=True);jar=ROOT/'target/dsl-doris-compiler.jar'
    audit=json.loads(args.audit_report.read_text(encoding='utf-8'))
    manifest_json=json.loads(args.manifest.read_text(encoding='utf-8'))
    golden=json.loads(args.golden.read_text(encoding='utf-8'))
    if golden['snapshotId']!=manifest_json['snapshotId'] or audit['snapshotId']!=manifest_json['snapshotId']:
        raise ValueError('Golden set, manifest and audit snapshot IDs must match')
    evaluation_date=args.evaluation_date or manifest_json['files']['hsj_stock_hq_basic']['dateMax']
    if not manifest_json['files']['hsj_stock_hq_basic']['dateMin']<=evaluation_date<=manifest_json['files']['hsj_stock_hq_basic']['dateMax']:
        raise ValueError('Evaluation date is outside the snapshot range')
    con=duckdb.connect(str(args.database));con.execute("SET memory_limit='4GB'");con.execute('SET threads=4')
    con.execute("SET schema='newzl'")
    output={'engine':'DuckDB '+duckdb.__version__,'purpose':'DIAGNOSTIC_ONLY_NOT_DORIS_ACCEPTANCE',
        'sourceAuditStatus':audit['status'],'snapshotId':audit['snapshotId'],
        'jarSha256':hashlib.sha256(jar.read_bytes()).hexdigest(),
        'goldenPath':str(args.golden.resolve()),'goldenVersion':golden['goldenVersion'],
        'goldenSha256':hashlib.sha256(args.golden.read_bytes()).hexdigest(),
        'manifestPath':str(args.manifest.resolve()),'manifestSha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'evaluationDate':evaluation_date,'results':[]}
    references={}
    try:
        lock=con.execute('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock').fetchone()
        manifest=args.manifest
        if lock != (audit['snapshotId'],hashlib.sha256(manifest.read_bytes()).hexdigest(),audit['status']):
            raise ValueError('Local audit database does not match the source audit report and manifest')
        views=(ROOT/'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8').replace('USE newzl;','')
        con.execute(views)
        con.execute('CREATE TABLE IF NOT EXISTS newzl.stock_daily_features_v2(mktcode INT,tgtcode VARCHAR,bizdate DATE,ma60 DOUBLE)')
        con.execute('DELETE FROM newzl.stock_daily_features_v2')
        ddl=(ROOT/'data/doris/ddl/005_performance_features.sql').read_text(encoding='utf-8')
        con.execute(ddl[ddl.index('INSERT INTO stock_daily_features_v2'):ddl.index('ANALYZE TABLE')])
        print('[reference] independent Python expectations from actual observed rows',flush=True)
        independent=python_expectations(con,evaluation_date)
        extra={
            'MA60':indicator('60日均线',evaluation_date)+' > 1', 'MA5':indicator('5日均线',evaluation_date)+' > 1',
            'RSI14':indicator('RSI(14)',evaluation_date)+' > 50','BETWEEN_MA5':'('+indicator('5日均线',evaluation_date)+"+1) between '[2,4]'",
            'CONS3_CLOSE':indicator('收盘价',evaluation_date,count='CONS>=3日')+' > 1',
            'EXIST3_VOLUME':indicator('成交量',evaluation_date,count='EXIST>=3日')+' > 0',
            'BOOLEAN_CONS3':f"record_high('', '', '收盘价', '3日', '{evaluation_date}', '', '', 'CONS>=3日')",
            'CROSS_ABOVE':f"cross_above('', '', '收盘价', '开盘价', '{evaluation_date}', '', '') = True",
            'NET_SUM5':indicator('主力净流入',date=evaluation_date+'近5日',agg='SUM')+' > 0',
            'RANK_CLOSE':f"rank('', '', '收盘价', 'desc:dense_rank', '{evaluation_date}', '', '', '') <= 3",
        }
        cases=[c for c in golden['cases'] if c.get('executable')]+[{'id':'PY-'+k,'dsl':v,'pythonReference':k} for k,v in extra.items()]
        with tempfile.TemporaryDirectory(prefix='official-data-sql-') as temp:
            for case in cases:
                started=time.monotonic();record={'id':case['id'],'dsl':case['dsl']}
                try:
                    artifact=compile_case(args.java,jar,case['dsl'],Path(temp)/'case.dsl',output['snapshotId'])
                    generated=con.execute(portable_identifiers(artifact['sql']),artifact['bindings']).fetchall()
                    expected=independent[case['pythonReference']] if 'pythonReference' in case else con.execute(portable_identifiers(reference_sql(case['reference']))).fetchall()
                    references[case['id']]=expected
                    correct=generated==expected if artifact['ordered'] else set(generated)==set(expected)
                    structure=True
                    if 'expect' in case:
                        e=case['expect'];expression=artifact['semanticModel']['document']['expression']
                        structure=(expression.get('operator')==e['rootOperator'] and functions(expression)==e['functions']
                            and [n['kind'] for n in artifact['logicalPlan']]==e['planKinds']
                            and len(artifact['bindings'])==e['bindingCount'] and artifact['ordered']==e['ordered']
                            and all(s in artifact['sql'] for s in e['requiredSql']) and not any(s in artifact['sql'] for s in e['forbiddenSql']))
                    record.update(status='PASS' if correct and structure else 'FAIL',resultEqual=correct,structureEqual=structure,
                        generatedRows=len(generated),referenceRows=len(expected),
                        onlyGenerated=sorted(set(generated)-set(expected))[:20],onlyReference=sorted(set(expected)-set(generated))[:20],
                        sample=generated[:10],sql=artifact['sql'],bindings=artifact['bindings'],ordered=artifact['ordered'])
                    if 'expect' in case:
                        record['missingRequiredSql']=[s for s in case['expect']['requiredSql'] if s not in artifact['sql']]
                except Exception as error:record.update(status='ERROR',error=str(error))
                record['elapsedSeconds']=round(time.monotonic()-started,3);output['results'].append(record)
                print(f"[{record['id']}] {record['status']} ({record['elapsedSeconds']}s)",flush=True)
    finally:
        con.close()
        output['total']=len(output['results']);output['passed']=sum(r['status']=='PASS' for r in output['results'])
        output['resultEqualCount']=sum(r.get('resultEqual') is True for r in output['results'])
        output['structureEqualCount']=sum(r.get('structureEqual') is True for r in output['results'])
        (folder/'本地真实数据结果对比.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
        args.reference_output.parent.mkdir(parents=True,exist_ok=True)
        args.reference_output.write_text(json.dumps({
            'snapshotId':output['snapshotId'],'jarSha256':output['jarSha256'],
            'goldenSha256':output['goldenSha256'],'manifestSha256':output['manifestSha256'],
            'referenceEngine':output['engine'],'results':references},ensure_ascii=False)+'\n',encoding='utf-8')
    print(f"LOCAL_DIAGNOSTIC_RESULTS: {output['passed']}/{output['total']}",flush=True)
    return 0 if output['total']==len(cases) and output['passed']==output['total'] else 1


if __name__=='__main__':raise SystemExit(main())
