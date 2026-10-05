"""Keep exact raw-price boundaries separate from DOUBLE window arithmetic."""
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris, bind_sql

folder = Path(__file__).resolve().parent
client = WslDoris('dsl-doris-official-01a104f9', 'dsl-doris-official')
results = json.loads((folder / 'independent-fields-and-functions.json').read_text(encoding='utf-8'))
case = next(r for r in results['queries'] if r['id'] == 'position-低-2026-04-14')
history = client.query("SELECT bizdate,closePx,closePrice FROM newzl.v_hsj_stock_hq_basic WHERE mktcode=103 AND tgtcode='920895' AND bizdate<='2026-04-14' ORDER BY bizdate DESC LIMIT 5")
raw = [Decimal(r[1]) for r in history]
low, high, current = min(raw), max(raw), raw[0]
assert len(raw) == 5 and 3 * (current-low) == high-low
sql = bind_sql(case['sql'], case['bindings'])
diagnostic = sql[:sql.rindex('SELECT mktcode,tgtcode')] + "SELECT mktcode,tgtcode,`v1`,`f1` FROM current_rows WHERE tgtcode='920895';"
actual = client.query(diagnostic)
# This alternative keeps comparisons as inequalities on scaled decimal values.
# It is a read-only experiment for four-decimal raw prices, not a general fix
# for arbitrary indicators with other units/ranges or computed moving averages.
expression = ('CASE WHEN NOT ({complete}) OR {max}={min} THEN NULL '
              "WHEN 3*(CAST(`v1` AS DECIMAL(38,12))-CAST({min} AS DECIMAL(38,12)))<=CAST({max} AS DECIMAL(38,12))-CAST({min} AS DECIMAL(38,12)) THEN '低' "
              "WHEN 3*(CAST(`v1` AS DECIMAL(38,12))-CAST({min} AS DECIMAL(38,12)))>=2*(CAST({max} AS DECIMAL(38,12))-CAST({min} AS DECIMAL(38,12))) THEN '高' ELSE '中' END")
over = '(PARTITION BY mktcode,tgtcode ORDER BY bizdate ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)'
replacement = expression.format(complete='COUNT(`v1`) OVER '+over+'=5', min='MIN(`v1`) OVER '+over, max='MAX(`v1`) OVER '+over)
start = sql.index('CASE WHEN NOT ('); end = sql.index(' AS `f1`', start)
alternative = sql[:start] + replacement + sql[end:]
corrected = client.query(alternative)
expected_rows = results['queries'][next(i for i,r in enumerate(results['queries']) if r['id']=='position-低-2026-04-14')]['expectedRows']
report = {'purpose': 'READ_ONLY_POSITION_BOUNDARY_REPRODUCTION', 'changesApplied': False,
          'date': '2026-04-14', 'key': [103, '920895'], 'rawLastFiveObservationsDescending': history,
          'rawMin': str(low), 'rawMax': str(high), 'rawCurrent': str(current),
          'exactIntegerBoundary': '3*(current-min)==max-min', 'expectedCategory': '低',
          'actualGeneratedCategory': actual[0][3], 'originalLowResultRows': case['actualRows'],
          'referenceLowResultRows': expected_rows, 'experimentalLowResultRows': len(corrected),
          'experimentalIncludesBoundaryKey': ('103','920895') in corrected,
          'experimentLimitation': 'Decimal(38,12) experiment only demonstrates the close-price case; general overflow, range and window-indicator behavior must be designed and tested before a compiler fix.'}
assert report['actualGeneratedCategory'] == '中' and report['experimentalIncludesBoundaryKey'] and len(corrected) == expected_rows
(folder / 'position-boundary-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
