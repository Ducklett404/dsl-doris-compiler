import json
from decimal import Decimal
from pathlib import Path
import sys
import tempfile

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pom.xml').exists())
sys.path.insert(0, str(ROOT / 'scripts/doris'))
import check_official_field_acceptance as oracle

old_path = ROOT / 'reports/official-acceptance/2026-10-04/a0f7260/precision-boundary-probe.json'
old = json.loads(old_path.read_text(encoding='utf-8'))
jar = ROOT / 'target/dsl-doris-compiler.jar'
output = {'purpose': 'ORIGINAL_FAILURE_THRESHOLDS_AFTER_FIX', 'jarSha256': oracle.digest(jar),
          'previousProbeSha256': oracle.digest(old_path), 'checks': []}
con = oracle.duckdb.connect(str(ROOT / 'target/data-audit/acceptance-a0f7260.duckdb'), read_only=True)
client = oracle.WslDoris('dsl-doris-official-01a104f9', 'dsl-doris-official')
try:
    with tempfile.TemporaryDirectory() as temp:
        for item in old['dates']:
            probe = item['boundary']
            threshold = Decimal(probe['threshold'])
            rows = con.execute('SELECT mktcode,tgtcode,lastPx,preClosePx FROM newzl.hsj_stock_hq_basic WHERE bizdate=CAST(? AS DATE)', [item['date']]).fetchall()
            expected = sorted((int(m), code) for m, code, last, prev in rows if last is not None and prev not in (None, 0)
                and (Decimal(last) - Decimal(prev)) * 100 / Decimal(prev) > threshold)
            artifact = oracle.compile_case('D:/Java/jdk-21/bin/java.exe', jar, probe['dsl'], Path(temp) / 'case.dsl', 'stock-20060104-20260414-v1')
            actual = [(int(m), code) for m, code in client.query(oracle.bind_sql(artifact['sql'], artifact['bindings']))]
            output['checks'].append({'date': item['date'], 'dsl': probe['dsl'], 'previousBoundaryKey': probe['key'],
                'status': 'PASS' if actual == expected else 'FAIL', 'rows': len(actual),
                'expectedBoundaryKeyIncluded': tuple(probe['key']) in expected,
                'actualBoundaryKeyIncluded': tuple(probe['key']) in actual,
                'previousOnlyGenerated': probe['onlyGenerated'], 'previousOnlyReference': probe['onlyReference']})
    assert client.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry') == [('0',)]
    output['status'] = 'PASS' if len(output['checks']) == 5 and all(r['status'] == 'PASS' and r['expectedBoundaryKeyIncluded'] == r['actualBoundaryKeyIncluded'] for r in output['checks']) else 'FAIL'
finally:
    con.close()
    (ROOT / 'reports/precision-fix/2026-10-04/original-threshold-regressions-final.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(output['status'], len(output['checks']))
assert output['status'] == 'PASS'
