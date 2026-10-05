"""Actual generated SQL on disposable numerical boundary fixtures.

No official table or snapshot registration is changed. Expected categories are
hand-labelled independently of the generated CASE expression.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris, bind_sql, compile_case, sql_literal

D = Decimal
DATE = '2026-04-14'
DAYS = ['2026-04-02','2026-04-06','2026-04-08','2026-04-13',DATE]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='D:/Java/jdk-21/bin/java.exe')
    parser.add_argument('--jar', type=Path, default=ROOT/'target/dsl-doris-compiler.jar')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    client = WslDoris(args.distribution, 'dsl-doris-official')
    database = 'dsl_precision_' + uuid.uuid4().hex[:12]
    assert re.fullmatch(r'dsl_precision_[0-9a-f]{12}', database)
    original_registry = client.query('SELECT * FROM newzl.data_snapshot_registry')
    report = {'purpose':'SYNTHETIC_NUMERICAL_REGRESSION_NOT_OFFICIAL_ACCEPTANCE',
              'startedAtUtc':datetime.now(timezone.utc).isoformat(), 'fixtureDatabase':database,
              'jarSha256':hashlib.sha256(args.jar.read_bytes()).hexdigest(),
              'semanticViewSha256':hashlib.sha256((ROOT/'data/doris/ddl/002_semantic_view.sql').read_bytes()).hexdigest(),
              'checks':[], 'vectors':[]}
    created = False
    def check(name, correct, **evidence):
        report['checks'].append({'name':name, 'status':'PASS' if correct else 'FAIL', **evidence})
    def insert(table, columns, rows):
        client.query('INSERT INTO '+database+'.'+table+' ('+','.join(columns)+') VALUES '+','.join(
            '('+','.join(sql_literal(v) for v in row)+')' for row in rows))
    try:
        # The replacement is a fixed trusted schema token, not DSL or user SQL.
        ddl = (ROOT/'data/doris/ddl/001_rebuild_tables.sql').read_text(encoding='utf-8')
        client.query('CREATE DATABASE '+database); created = True
        client.query(ddl.replace('newzl', database).replace('BUCKETS 16','BUCKETS 1'))
        client.query((ROOT/'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8').replace('USE newzl;', 'USE '+database+';'))
        basic = []; extension = []; categories = {}; code_index = 0
        def vector(name, metric, values, expected, raw_field='closePx', multiplier=10000, missing_current=False):
            nonlocal code_index
            code_index += 1; code = f'{code_index:06}'
            categories.setdefault(metric, {})[code] = expected
            dates = DAYS[:len(values)] if missing_current else DAYS[-len(values):]
            for day, value in zip(dates, values):
                raw = None if value is None else D(str(value))*multiplier
                if raw is not None:
                    assert raw == raw.to_integral_value()
                    raw = int(raw)
                row = {'mktcode':1,'tgtcode':code,'bizdate':day,'lastPx':10000,'preClosePx':10000,
                       'closePx':10000,'volume':1,'turnover':100,'totalShare':1}
                row[raw_field] = raw
                basic.append(tuple(row.get(k) for k in basic_columns))
                if metric == '主力净流入':
                    extension.append((1,code,day,raw))
            report['vectors'].append({'name':name,'metric':metric,'code':code,'observations':values,
                                      'dates':dates,'expectedCategory':expected})
        basic_columns = ['mktcode','tgtcode','bizdate','lastPx','preClosePx','closePx','volume','turnover','totalShare']
        for suffix, current, category in [('low-edge','16.35','低'),('high-edge','16.50','高'),
                                          ('below-low-edge','16.3499','低'),('above-low-edge','16.3501','中'),
                                          ('below-high-edge','16.4999','中'),('above-high-edge','16.5001','高')]:
            vector(suffix,'收盘价',['16.2','16.65','16.41','16.51',current],category)
        vector('official-920895','收盘价',['16.51','16.41','16.65','16.20','16.35'],'低')
        vector('negative-low-edge','收盘价',['-16.65','-16.2','-16.41','-16.51','-16.50'],'低')
        vector('negative-high-edge','收盘价',['-16.65','-16.2','-16.41','-16.51','-16.35'],'高')
        vector('flat','收盘价',['16.2']*5,None)
        vector('insufficient','收盘价',['16.2','16.65','16.35'],None)
        vector('null-current','收盘价',['16.2','16.65','16.41','16.51',None],None)
        vector('null-window','收盘价',['16.2',None,'16.41','16.51','16.35'],None)
        vector('all-null','收盘价',[None]*5,None)
        vector('missing-current','收盘价',['16.2','16.65','16.41','16.35'],None,missing_current=True)
        for category, current in [('低',9223372036854775100),('中',9223372036854775101),('高',9223372036854775200)]:
            vector('bigint-near-limit-'+category,'成交量',[9223372036854775000,9223372036854775300,9223372036854775000,9223372036854775300,current],category,'volume',1)
        for category, current in [('低',10000000000000100),('中',10000000000000101),('高',10000000000000200)]:
            vector('large-amount-'+category,'成交额',[10000000000000000,10000000000000300,10000000000000000,10000000000000300,current],category,'turnover',100)
        for category, current in [('低',1000000000000100),('中',1000000000000101),('高',1000000000000200)]:
            vector('large-cap-'+category,'总市值',[1000000000000000,1000000000000300,1000000000000000,1000000000000300,current],category,'totalShare',1)
        for category, current in [('低',1),('中',3),('高',2)]:
            vector('small-mean-'+category,'均价',[0,3,0,3,current],category,'turnover',1)
            # Amount is cents; with this volume each turnover unit is 1e-12 CNY.
            for i in range(len(basic)-5,len(basic)):
                row = list(basic[i]); row[basic_columns.index('volume')] = 10000000000; basic[i] = tuple(row)
            if category=='中':
                row=list(basic[-1]);row[basic_columns.index('volume')]=20000000000;basic[-1]=tuple(row)
        vector('negative-net-edge','主力净流入',[-300,-3,-300,-3,-201],'低','net',1)
        vector('net-sentinel','主力净流入',[-300,-3,-999999,-3,-201],None,'net',1)
        insert('hsj_stock_hq_basic',basic_columns,basic)
        insert('hsj_stock_hq_basic',['mktcode','tgtcode','bizdate','closePx'],[(1,'000007','2026-04-15',999999999)])
        if extension: insert('hsj_stock_hq_ext',['mktcode','tgtcode','bizdate','ZJLXMainNetTur'],extension)
        with tempfile.TemporaryDirectory(prefix='precision-regression-') as directory:
            for metric, codes in categories.items():
                actual = {code:None for code in codes}
                for label in ['低','中','高']:
                    dsl = f"position('', '', '{metric}', '5日', '{DATE}', '', '', '') = '{label}'"
                    artifact = compile_case(args.java,args.jar,dsl,Path(directory)/'case.dsl')
                    sql = bind_sql(artifact['sql'],artifact['bindings']).replace('newzl.',database+'.')
                    rows = client.query(sql)
                    for market, code in rows:
                        if code in codes:
                            assert actual[code] is None, 'A category overlaps another category'
                            actual[code] = label
                for code, expected in codes.items():
                    check('position-'+metric+'-'+code,actual[code]==expected,expected=expected,actual=actual[code])
            # Historical / one-row contracts and pattern rejection stay intact.
            historical_low=[]
            for vector_ in report['vectors']:
                if vector_['metric']!='收盘价' or DATE not in vector_['dates'] or vector_['observations'][-1] is None:continue
                values=[D(str(v)) for v in vector_['observations'] if v is not None]
                if max(values)!=min(values) and 3*(values[-1]-min(values))<=max(values)-min(values):
                    historical_low.append(('1',vector_['code']))
            for period in ['1日','历史']:
                dsl=f"position('', '', '收盘价', '{period}', '{DATE}', '', '', '') = '低'"
                artifact=compile_case(args.java,args.jar,dsl,Path(directory)/'case.dsl')
                rows=client.query(bind_sql(artifact['sql'],artifact['bindings']).replace('newzl.',database+'.'))
                if period=='1日':check('one-row-flat-null',not rows)
                else:check('historical-null-policy-and-future-cutoff',sorted(rows)==sorted(historical_low),expected=historical_low,actual=rows)
            for metric in ['5日均线','RSI(14)']:
                try:
                    compile_case(args.java,args.jar,f"position('', '', '{metric}', '5日', '{DATE}', '', '', '') = '低'",Path(directory)/'case.dsl')
                except RuntimeError as error:
                    check('pattern-rejected-'+metric,'EXECUTION_INDICATOR_WINDOW' in str(error))
                else:check('pattern-rejected-'+metric,False)
        rise_vectors=[('positive',111580,110680),('negative',110700,110900),('fraction',103800,102000),
                      ('zero-previous',10000,0),('null-last',None,10000),('null-previous',10000,None),
                      ('wide-subtraction',9223372036854775000,-9223372036854775000)]
        rise_rows=[(1,'R'+str(i),DATE,a,b) for i,(_,a,b) in enumerate(rise_vectors)]
        insert('hsj_stock_hq_basic',['mktcode','tgtcode','bizdate','lastPx','preClosePx'],rise_rows)
        for i,(name,a,b) in enumerate(rise_vectors):
            expected=None if a is None or b in (None,0) else (D(a)-D(b))*100/D(b)
            text=client.query(f"SELECT risePct FROM {database}.v_hsj_stock_hq_basic WHERE tgtcode='R{i}'")[0][0]
            actual=None if text=='NULL' else D(text)
            correct=(actual is None) if expected is None else (actual is not None and abs(actual-expected)<=D('1e-10')*max(D(1),abs(expected)))
            check('rise-'+name,correct,expected=str(expected),actual=str(actual))
        # A value beyond the declared decimal domain must fail explicitly.
        insert('hsj_stock_hq_basic',['mktcode','tgtcode','bizdate','lastPx','totalShare'],
               [(1,'OVER',day,9000000000000000000,9000000000000000000) for day in DAYS])
        with tempfile.TemporaryDirectory(prefix='precision-overflow-') as directory:
            artifact=compile_case(args.java,args.jar,f"position('', '', '总市值', '5日', '{DATE}', '', '', '') = '低'",Path(directory)/'case.dsl')
            try:
                client.query(bind_sql(artifact['sql'],artifact['bindings']).replace('newzl.',database+'.'))
            except RuntimeError as error:
                check('out-of-domain-is-explicit-error','overflow' in str(error).lower(),error=str(error))
            else:check('out-of-domain-is-explicit-error',False)
        check('official-registry-preserved',client.query('SELECT * FROM newzl.data_snapshot_registry')==original_registry)
    except Exception as error:
        report['fatalError']=str(error)
        raise
    finally:
        if created:
            assert re.fullmatch(r'dsl_precision_[0-9a-f]{12}',database)
            client.query('DROP DATABASE '+database)
        report['fixtureCleanup']='DONE'
        report['completedAtUtc']=datetime.now(timezone.utc).isoformat()
        report['total']=len(report['checks']);report['passed']=sum(c['status']=='PASS' for c in report['checks'])
        report['status']='PASS' if 'fatalError' not in report and report['total']>0 and report['total']==report['passed'] else 'FAIL'
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','passed','total','fixtureCleanup']}))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
