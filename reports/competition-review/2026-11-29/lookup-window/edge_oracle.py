"""Generate additional frozen expectations from the read-only raw CSV import with Python row logic."""
import argparse
from decimal import Decimal
import json
import sys
from pathlib import Path

import duckdb
from replay import REPO, digest

sys.path.insert(0, str(REPO/'scripts/doris'))
from project_matrix_reference import load, value

# id, market, date, lookup targets (keyword, metric, aggregate), inside occurrence
CASES = [
    ('current-name', '沪|深|京', '2026-04-14', [('浦发银行','close','AVG')], False),
    ('current-two-targets', '沪|深|京', '2026-04-14', [('600000','close','MAX'),('平安银行','open','SUM')], False),
    ('count-name', '沪|深|京', '2026-04-14', [('浦发银行','close','MAX')], True),
    ('count-extension', '沪|深|京', '2026-04-14', [('浦发银行','net','MAX')], True),
    ('count-market-excludes-target', '深', '2025-01-02', [('600000','close','MAX')], True),
    ('count-no-full-window', '沪', '2006-01-06', [('600000','close','MIN')], True),
    ('count-two-targets', '沪|深|京', '2026-04-14', [('600000','close','MAX'),('平安银行','open','MIN')], True),
    ('count-weekend', '沪', '2026-04-12', [('浦发银行','close','MAX')], True),
]
LABELS = {'close':'收盘价','open':'开盘价','net':'主力净流入'}
MARKETS = {'沪':'1','深':'0','京':'103'}


def build(con):
    results = []
    cache = {}
    for key, market, date, targets, counted in CASES:
        markets = {MARKETS[m] for m in market.split('|')}
        if date not in cache:
            cache[date] = load(con, date, 24)
        data = cache[date]
        targets_by_date = []
        calls = []
        for word, metric, aggregate in targets:
            # Read the target's entire series. It can lack an observation on a date
            # where a candidate traded, or have an older row outside its own last 24.
            field = {'close':'b.closePx', 'open':'b.openPx', 'net':'NULLIF(e.ZJLXMainNetTur,-999999)'}[metric]
            rows = con.execute(f"""SELECT b.mktcode,b.bizdate,{field} FROM newzl.hsj_stock_hq_basic b
                LEFT JOIN newzl.hsj_stock_code_info c USING(mktcode,tgtcode)
                LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate)
                WHERE b.bizdate<=? AND (b.tgtcode=? OR c.name=?)""",[date,word,word]).fetchall()
            groups = {}
            for m, d, v in rows:
                if str(m) in markets and v is not None:
                    groups.setdefault(str(d),[]).append(Decimal(v)/(1 if metric=='net' else 10000))
            fn = {'AVG':lambda vs:sum(vs)/len(vs), 'MAX':max, 'MIN':min, 'SUM':sum}[aggregate]
            targets_by_date.append({d:fn(vs) for d,vs in groups.items()})
            calls.append(f"queryData('{market}', '{word}', '{LABELS[metric]}', '{date}', '{aggregate}')")
        occurrence = 'EXIST>=6日' if counted else ''
        ma = f"indicator('{market}', '', '5日均线', '{date}', '', '', '{occurrence}')"
        expr = '+'.join(calls)
        dsl = f'{ma} > ({expr})'
        expected = []
        for (m, code), history in data['histories'].items():
            if m not in markets or (counted and len(history)<20): continue
            hits = 0
            for end in range(max(0,len(history)-(20 if counted else 1)),len(history)):
                day = history[end]['date']
                operands = [s.get(day) for s in targets_by_date]
                avg = value({'kind':'ma','n':5},history[:end+1])
                if avg is not None and None not in operands and avg>sum(operands): hits+=1
            if hits >= (6 if counted else 1): expected.append([m,code])
        expected.sort(key=lambda row:(int(row[0]),row[1]))
        results.append(dict(id=key,dsl=dsl,target=True,expectedRows=len(expected),expectedDigest=digest(expected)))
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('raw_database',type=Path)
    p.add_argument('output',type=Path)
    args=p.parse_args()
    with duckdb.connect(str(args.raw_database),read_only=True) as con:
        con.execute("SET threads=2")
        results=build(con)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
