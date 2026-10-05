"""Manual project formulas, units and NULL operands, independent of registry/view/SQL output."""
from collections import defaultdict
from decimal import Decimal, localcontext, ROUND_HALF_UP
from check_official_field_acceptance import FIELDS, RAW_COLUMNS, raw_values
from project_matrix_reference import METRICS, render

KEYS=list(METRICS)
# Align with the already independent manual field inventory, not registry order.
KEYS=[next(k for k,v in METRICS.items() if v==name) for name,_,_ in FIELDS]
OPERANDS={'cap':['lastPx','totalShare'],'listedCap':['lastPx','listedShare'],
    'rise':['lastPx','preClosePx'],'average':['turnover','volume'],
    'qfq':['closePx','qfqMulti','qfqAdd'],'hfq':['closePx','hfqMulti','hfqAdd']}
SCALES=dict.fromkeys(KEYS,4)
SCALES.update(volume=0,net=0,amount=2,rise=18,average=18,qfq=12,hfq=12)


def observation(day,raw,extension=True):
    with localcontext() as context:
        context.prec=80
        normalized=dict(zip(KEYS,raw_values(raw)))
        positions={}
        for key,v in normalized.items():
            if v is not None:
                # Actual DECIMAL companions use 14/18 fractional places before the final position cast.
                if key=='rise':v=(Decimal(raw['lastPx'])/Decimal(raw['preClosePx'])-1)*100;v=v.quantize(Decimal('1e-14'),rounding=ROUND_HALF_UP)
                if key=='average':v=v.quantize(Decimal('1e-18'),rounding=ROUND_HALF_UP)
                v=v.quantize(Decimal(1).scaleb(-SCALES[key]),rounding=ROUND_HALF_UP)
            positions[key]=v
    return dict(date=str(day),close=raw['closePx'],open=raw['openPx'],volume=raw['volume'],
        net=None if raw['net']==-999999 else raw['net'],rawNet=raw['net'],ext=extension,
        normalized=normalized,positions=positions,operands=raw)


def null_causes(row,metric):
    label=METRICS[metric]
    if metric not in OPERANDS:return [('SOURCE_NULL',label)]
    result=[]
    for operand in OPERANDS[metric]:
        v=row['operands'][operand]
        if v is None:result.append(('SOURCE_OPERAND_NULL',label+' / '+operand))
        elif (metric,operand) in [('rise','preClosePx'),('average','volume')] and v==0:
            result.append(('ZERO_DENOMINATOR',label+' / '+operand))
    if not result:raise AssertionError('NULL formula without causal raw evidence: '+label)
    return result


def load(con,date,retained_rows=64):
    if not isinstance(retained_rows,int) or retained_rows<1:raise ValueError('Invalid row budget')
    rows=con.execute('WITH tail AS (SELECT mktcode,tgtcode,bizdate,'+','.join(RAW_COLUMNS)+
        ' FROM newzl.hsj_stock_hq_basic WHERE bizdate<=CAST(? AS DATE) QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=?) '+
        'SELECT b.*,e.tgtcode,e.ZJLXMainNetTur FROM tail b LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) ORDER BY b.mktcode,b.tgtcode,b.bizdate',[date,retained_rows]).fetchall()
    histories=defaultdict(list)
    for m,code,day,*values in rows:
        ext,net=values[-2:];raw=dict(zip(RAW_COLUMNS,values[:-2]));raw['net']=net
        histories[(str(m),code)].append(observation(day,raw,ext is not None))
    names={(str(m),c):name for m,c,name in con.execute('SELECT mktcode,tgtcode,name FROM newzl.hsj_stock_code_info').fetchall()}
    return dict(histories={k:h for k,h in histories.items() if h[-1]['date']==date},names=names)


def cases():
    suite=[]
    def add(name,call,op,threshold,date='2026-04-14'):
        expr=('cmp',0,op,threshold)
        suite.append(dict(name=name,calls=[call],expr=expr,date=date,market='',dsl=render(expr,[call],date,'')))
    for day in ['2006-01-04','2018-08-20','2026-04-14']:
        for key,(_,_,threshold) in zip(KEYS,FIELDS):add('field-'+key+'-'+day,dict(kind='field',metric=key),'>',float(threshold),day)
    for key in KEYS:add('position-'+key,dict(kind='position',metric=key,n=3),'=','高')
    for key in OPERANDS:
        add('count-'+key,dict(kind='count',metric=key,n=3,mode='CONS',countOp='=',op='>',threshold=0),'=',True)
        for day in ['2026-04-10','2026-04-13']:add('field-'+key+'-'+day,dict(kind='field',metric=key),'>',0,day)
    return suite
