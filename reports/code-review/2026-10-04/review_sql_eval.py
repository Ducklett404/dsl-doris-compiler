import json, sqlite3, datetime, hashlib
from pathlib import Path

cases = {x['case']: x for x in json.loads(Path('target/review-probe.json').read_text(encoding='utf-8'))}
db = sqlite3.connect(':memory:')
db.execute("ATTACH DATABASE ':memory:' AS newzl")
db.executescript('''
CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INTEGER,tgtcode TEXT,bizdate TEXT,closePrice REAL);
CREATE TABLE newzl.stock_daily_features_v1(mktcode INTEGER,tgtcode TEXT,bizdate TEXT,ma60 REAL);
CREATE TABLE newzl.hsj_stock_code_info(mktcode INTEGER,tgtcode TEXT,name TEXT,hyBlkRefName TEXT);
''')
end = datetime.date(2026,4,14)
for day in range(61):
    db.execute('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(1,?,?,?)', ('A',(end-datetime.timedelta(days=60-day)).isoformat(),None if day==20 else 2))
db.executescript('''
INSERT INTO newzl.stock_daily_features_v1
WITH observed AS (SELECT * FROM newzl.v_hsj_stock_hq_basic WHERE closePrice IS NOT NULL AND bizdate<='2026-04-14'),
windowed AS (SELECT mktcode,tgtcode,bizdate,CASE WHEN COUNT(closePrice) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)=60 THEN AVG(closePrice) OVER (PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) ELSE NULL END ma60 FROM observed)
SELECT mktcode,tgtcode,bizdate,ma60 FROM windowed WHERE bizdate='2026-04-14';
''')
evidence = {}
for label in ['frozen_ma60','historical_ma60','missing_industry']:
    case = cases[label]
    result = db.execute(case['sql'],case['bindings']).fetchall()
    item = {'actual':result}
    if 'referenceSql' in case:
        item['reference'] = db.execute(case['referenceSql'],case['bindings']).fetchall()
    evidence[label] = item
    print(label,item)
db.execute('UPDATE newzl.v_hsj_stock_hq_basic SET closePrice=2 WHERE closePrice IS NULL')
case = cases['historical_ma60']
evidence['historical_ma60_complete_data'] = {'actual':db.execute(case['sql'],case['bindings']).fetchall(),'reference':db.execute(case['referenceSql'],case['bindings']).fetchall()}
print('historical_ma60_complete_data', evidence['historical_ma60_complete_data'])
raw = Path('src/main/resources/stock-slot-registry-v1.json').read_bytes()
freeze = json.loads(Path('config/acceptance/stock-slot-phase1-scope-v1.json').read_text(encoding='utf-8'))
evidence['registry_hashes'] = {'raw':hashlib.sha256(raw).hexdigest(),'lf':hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest(),'freeze':freeze}
Path('target/review-sql-eval.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print('registry hashes:',{k:v for k,v in evidence['registry_hashes'].items() if k!='freeze'})
