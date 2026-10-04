"""Independent Decimal expectations from immutable raw CSV-backed DuckDB observations."""
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import duckdb

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris,sql_literal
from build_rolling_features import RANGE_FIELDS


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=ROOT/'target/data-audit/official.duckdb')
    parser.add_argument('--distribution',default='dsl-doris-official-01a104f9');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();catalog=json.loads(args.catalog.read_text(encoding='utf-8'));windows=sorted(int(n) for n in catalog['windowFields'])
    manifest_path=ROOT/'data/doris/snapshots'/catalog['snapshotId']/'manifest.json'
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest()!=catalog['manifestSha256']:raise ValueError('Manifest mismatch')
    client=WslDoris(args.distribution,'dsl-doris-official');con=duckdb.connect(str(args.database),read_only=True)
    output={'purpose':'INDEPENDENT_DECIMAL_DATA_DIAGNOSTIC','acceptanceEligible':False,
        'catalogSha256':hashlib.sha256(args.catalog.read_bytes()).hexdigest(),
        'jarSha256':hashlib.sha256((ROOT/'target/dsl-doris-compiler.jar').read_bytes()).hexdigest(),'dates':[],'queryExpectations':{}}
    try:
        lock=con.execute('SELECT snapshot_id,manifest_sha256 FROM audit_source_lock').fetchone()
        if lock!=(catalog['snapshotId'],catalog['manifestSha256']):raise ValueError('Local raw source mismatch')
        for date,count in sorted(catalog['completeDates'].items()):
            rows=con.execute(f"""SELECT mktcode,tgtcode,bizdate,closePx,highPx,lowPx FROM newzl.hsj_stock_hq_basic
                WHERE bizdate<=CAST(? AS DATE)
                QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<={max(windows)}
                ORDER BY mktcode,tgtcode,bizdate""",[date]).fetchall()
            histories=defaultdict(list)
            for market,code,day,*prices in rows:histories[(int(market),code)].append((str(day),*[None if p is None else Decimal(p)/Decimal(10000) for p in prices]))
            expected={}
            for key,values in histories.items():
                if values[-1][0]!=date:continue
                prices=[v[1] for v in values]
                expected[key]={n:sum(prices[-n:])/Decimal(n) if len(prices)>=n and all(p is not None for p in prices[-n:]) else None for n in windows}
                for index,r in enumerate(RANGE_FIELDS.values(),2):
                    observations=[v[index] for v in values]
                    complete=len(observations)>=250 and all(v is not None for v in observations[-250:])
                    expected[key].update({r['currentField']:observations[-1],r['minField']:min(observations[-250:]) if complete else None,
                        r['maxField']:max(observations[-250:]) if complete else None})
            keys=windows+[r[f] for r in RANGE_FIELDS.values() for f in ('currentField','minField','maxField')]
            fields=','.join([catalog['windowFields'][str(n)] for n in windows]+keys[len(windows):])
            actual={(int(m),code):{n:None if value=='NULL' else Decimal(value) for n,value in zip(keys,values)}
                for m,code,*values in client.query(f"SELECT mktcode,tgtcode,{fields} FROM {catalog['qualifiedTable']} WHERE bizdate={sql_literal(date)} ORDER BY mktcode,tgtcode")}
            if len(expected)!=count or set(actual)!=set(expected):raise ValueError('Independent coverage differs')
            checked=0;nulls=0;max_error=Decimal(0)
            for key,values in expected.items():
                for n,e in values.items():
                    a=actual[key][n];checked+=1
                    if e is None:
                        nulls+=1
                        if a is not None:raise ValueError('NULL/insufficient window differs')
                    elif a is None or abs(a-e)>Decimal('1e-10')*max(Decimal(1),abs(e)):raise ValueError('Independent decimal average differs')
                    else:max_error=max(max_error,abs(a-e))
            for n in windows:
                for market in ('all','沪'):
                    output['queryExpectations'][f'ma{n}-{date}-{market}']=[list(key) for key in sorted(expected)
                        if (market=='all' or key[0]==1) and expected[key][n] is not None and expected[key][n]>10]
            for name,r in RANGE_FIELDS.items():
                function='high' if name=='high' else 'low';bound=r['maxField'] if name=='high' else r['minField']
                output['queryExpectations'][f'record-{function}-{date}-all']=[list(key) for key in sorted(expected)
                    if expected[key][r['currentField']] is not None and expected[key][bound] is not None and expected[key][r['currentField']]==expected[key][bound]]
            output['dates'].append({'date':date,'status':'PASS','rows':count,'numericValuesChecked':checked,
                'nullValuesChecked':nulls,'maxAbsoluteError':str(max_error)})
            print(f'{date}: independent Decimal checked {checked} values ({nulls} NULL)',flush=True)
        output['status']='PASS';output['totalNumericValuesChecked']=sum(r['numericValuesChecked'] for r in output['dates'])
    finally:
        con.close();args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
