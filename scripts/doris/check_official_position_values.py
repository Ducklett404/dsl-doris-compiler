"""Independent raw-Decimal categories for every direct field on official rows."""
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/doris'))
import check_official_field_acceptance as oracle


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--java',default='D:/Java/jdk-21/bin/java.exe');args=parser.parse_args()
    manifest=ROOT/'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json'
    jar=ROOT/'target/dsl-doris-compiler.jar'
    con=oracle.duckdb.connect(str(args.database),read_only=True)
    con.execute("SET memory_limit='4GB'");con.execute('SET threads=4')
    client=oracle.WslDoris(args.distribution,'dsl-doris-official')
    report={'purpose':'INDEPENDENT_RAW_POSITION_RESULTS_DIAGNOSTIC','acceptanceEligible':False,
            'jarSha256':oracle.digest(jar),'manifestSha256':oracle.digest(manifest),
            'oracleSha256':oracle.digest(Path(__file__)),'results':[],'fieldDomainChecks':[]}
    try:
        lock=con.execute('SELECT snapshot_id,manifest_sha256 FROM audit_source_lock').fetchone()
        if lock!=('stock-20060104-20260414-v1',report['manifestSha256']):raise ValueError('Source lock mismatch')
        registry=json.loads((ROOT/'src/main/resources/stock-slot-registry-v1.json').read_text(encoding='utf-8'))
        # Full-table scalar domain checks include worst possible window spreads.
        for table in ['basic','extension']:
            entries=[i for i in registry['indicators'] if i['source']['table']==table]
            expressions=[]
            for i in entries:
                params=i['lowering']['parameters'];field=params.get('positionField',i['source']['field'])
                physical=registry['tables'][table]['fields'][field]
                expression=physical
                if i['sentinelValues']:expression='NULLIF('+physical+','+str(i['sentinelValues'][0])+')'
                # Ordinary scaled-field expressions need scaling if there is no companion.
                if 'positionField' not in params:
                    multiply=i['scale']['multiply'];divide=i['scale']['divide']
                    expression='('+expression+'*'+str(multiply)+'/'+str(divide)+')'
                value='CAST('+expression+' AS DECIMAL(36,'+params['positionScale']+'))'
                expressions.extend(['MIN('+value+')','MAX('+value+')',
                    'CAST(3 AS DECIMAL(1,0))*(MAX('+value+')-MIN('+value+'))'])
            rows=client.query('SELECT '+','.join(expressions)+' FROM '+registry['tables'][table]['qualifiedName'])
            assert len(rows)==1 and len(rows[0])==3*len(entries)
            for index,item in enumerate(entries):
                report['fieldDomainChecks'].append({'field':item['name'],'status':'PASS','minimum':rows[0][3*index],
                    'maximum':rows[0][3*index+1],'maximumCrossProduct':rows[0][3*index+2]})
        with tempfile.TemporaryDirectory(prefix='official-position-') as directory:
            for date in ['2026-04-10','2026-04-13','2026-04-14']:
                rows=con.execute('WITH tail AS MATERIALIZED (SELECT mktcode,tgtcode,bizdate,'+','.join(oracle.RAW_COLUMNS)+
                    ' FROM newzl.hsj_stock_hq_basic WHERE bizdate<=CAST(? AS DATE) QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=5) '
                    'SELECT t.*,e.ZJLXMainNetTur net FROM tail t LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) ORDER BY mktcode,tgtcode,bizdate',[date]).fetchall()
                histories=defaultdict(list)
                for m,code,day,*values in rows:
                    histories[(int(m),code)].append((str(day),oracle.raw_values(dict(zip((*oracle.RAW_COLUMNS,'net'),values)))))
                for index,(metric,_,_) in enumerate(oracle.FIELDS):
                    expected={label:[] for label in ['低','中','高']}
                    for key,history in histories.items():
                        if history[-1][0]!=date or len(history)<5:continue
                        values=[r[1][index] for r in history[-5:]]
                        if any(v is None for v in values):continue
                        low,high,current=min(values),max(values),values[-1]
                        if low==high:continue
                        label='低' if 3*(current-low)<=high-low else ('高' if 3*(current-low)>=2*(high-low) else '中')
                        expected[label].append(key)
                    for label,keys in expected.items():
                        keys=sorted(keys)
                        dsl=f"position('', '', '{metric}', '5日', '{date}', '', '', '') = '{label}'"
                        record={'date':date,'metric':metric,'category':label,'dsl':dsl,'referenceRows':len(keys)}
                        try:
                            artifact=oracle.compile_case(args.java,jar,dsl,Path(directory)/'case.dsl',lock[0])
                            actual=[(int(m),code) for m,code in client.query(oracle.bind_sql(artifact['sql'],artifact['bindings']))]
                            record.update(status='PASS' if actual==keys else 'FAIL',actualRows=len(actual),
                                onlyActual=sorted(set(actual)-set(keys))[:10],onlyExpected=sorted(set(keys)-set(actual))[:10],
                                sql=artifact['sql'],bindings=artifact['bindings'])
                        except Exception as error:record.update(status='ERROR',error=str(error))
                        report['results'].append(record)
                        if record['status']!='PASS':print(json.dumps(record,ensure_ascii=False),flush=True)
                print(date+': all 19 position fields checked',flush=True)
        assert oracle.digest(jar)==report['jarSha256']
        assert client.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry')==[('0',)]
    except Exception as error:
        report['fatalError']=str(error);raise
    finally:
        con.close();report['total']=len(report['results']);report['passed']=sum(r['status']=='PASS' for r in report['results'])
        report['status']='PASS' if 'fatalError' not in report and len(report['fieldDomainChecks'])==19 and report['total']==171 and report['passed']==171 else 'FAIL'
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','total','passed']}))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
