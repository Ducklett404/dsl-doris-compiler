"""Export exact offending source keys without altering or repairing any row."""
import csv
import json
from pathlib import Path
import sys
import duckdb

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import sql_literal

folder = Path(__file__).resolve().parent
local = ROOT / 'target/official-acceptance-a0f7260/source-issues'
local.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(str(ROOT / 'target/data-audit/acceptance-a0f7260.duckdb'), read_only=True)
orphan = 'SELECT e.mktcode,e.tgtcode,e.bizdate FROM newzl.hsj_stock_hq_ext e ANTI JOIN newzl.hsj_stock_hq_basic b USING(mktcode,tgtcode,bizdate)'
source_report = {'purpose': 'EXACT_SOURCE_ISSUE_EXPORT_NO_REPAIR', 'exports': []}
for name, sql, expected in [
    ('orphan-extension-keys.csv', orphan+' ORDER BY bizdate,mktcode,tgtcode', 249480),
    ('close-outside-high-low.csv', 'SELECT mktcode,tgtcode,bizdate,closePx,highPx,lowPx FROM newzl.hsj_stock_hq_basic WHERE closePx<lowPx OR closePx>highPx ORDER BY bizdate,mktcode,tgtcode', 3487),
]:
    path = local / name
    con.execute('COPY ('+sql+') TO '+sql_literal(path.as_posix())+' (HEADER, DELIMITER \',\')')
    with path.open(encoding='utf-8', newline='') as file:
        reader = csv.reader(file); header = next(reader); count = sum(1 for _ in reader)
    assert count == expected
    source_report['exports'].append({'path': str(path.resolve()), 'rows': count, 'columns': header})
    con.execute('COPY ('+sql+' LIMIT 20) TO '+sql_literal((folder / ('sample-'+name)).as_posix())+' (HEADER, DELIMITER \',\')')
source_report['orphanByYearAndMarket'] = [dict(zip(['year','market','rows'], r)) for r in con.execute('SELECT YEAR(bizdate),mktcode,COUNT(*) FROM ('+orphan+') GROUP BY 1,2 ORDER BY 1,2').fetchall()]
source_report['latestOrphans'] = con.execute('SELECT MAX(bizdate),COUNT(*),COUNT(DISTINCT mktcode::VARCHAR||\':\'||tgtcode) FROM ('+orphan+') WHERE bizdate=(SELECT MAX(bizdate) FROM newzl.hsj_stock_hq_ext)').fetchone()
con.close()
(folder / 'source-issue-exports.json').write_text(json.dumps(source_report, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
print(json.dumps(source_report['exports'], ensure_ascii=False))
