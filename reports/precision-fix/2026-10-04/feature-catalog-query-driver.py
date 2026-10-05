"""Independent result keys and actual selection of the rebuilt feature catalogs."""
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pom.xml').exists())
sys.path.insert(0, str(ROOT / 'scripts/doris'))
import check_official_field_acceptance as oracle

folder = ROOT / 'reports/precision-fix/2026-10-04'
history_path = folder / 'history-build/catalog.json'
rolling_path = folder / 'rolling-build-final/catalog.json'
history = json.loads(history_path.read_text())
rolling = json.loads(rolling_path.read_text())
reference = json.loads((folder / 'independent-rolling.json').read_text())
jar = ROOT / 'target/dsl-doris-compiler.jar'
assert reference['jarSha256'] == oracle.digest(jar) and reference['catalogSha256'] == oracle.digest(rolling_path)
assert history['registryFingerprint'] == rolling['registryFingerprint']
cases = []
for name, expected in reference['queryExpectations'].items():
    match = re.fullmatch(r'ma(\d+)-(\d{4}-\d{2}-\d{2})-(all|沪)', name)
    if match:
        n, date, market = match.groups()
        market = '' if market == 'all' else market
        dsl = f"indicator('{market}', '', '{n}日均线', '{date}', '', '', '') > 10"
    else:
        function, date = re.fullmatch(r'record-(high|low)-(\d{4}-\d{2}-\d{2})-all', name).groups()
        metric = '最高价' if function == 'high' else '最低价'
        dsl = f"record_{function}('', '', '{metric}', '250日', '{date}', '', '', '') = True"
    cases.append((name, dsl, [tuple(key) for key in expected], 'RollingFeatureScan'))
con = oracle.duckdb.connect(str(ROOT / 'target/data-audit/acceptance-a0f7260.duckdb'), read_only=True)
for date in sorted(history['completeDates']):
    rows = con.execute('SELECT mktcode,tgtcode,' + ','.join(f'MIN({field}),MAX({field}),MAX(CASE WHEN bizdate=CAST(? AS DATE) THEN {field} END)' for field in ['closePx','highPx','lowPx']) +
        ',MAX(CASE WHEN bizdate=CAST(? AS DATE) THEN 1 ELSE 0 END) has_current FROM newzl.hsj_stock_hq_basic WHERE bizdate<=CAST(? AS DATE) GROUP BY mktcode,tgtcode HAVING has_current=1 ORDER BY mktcode,tgtcode', [date]*5).fetchall()
    for index, metric in enumerate(['收盘价', '最高价', '最低价']):
        for function, offset in [('low', 0), ('high', 1)]:
            expected = [(int(m), code) for m, code, *values in rows if values[3*index+2] is not None and values[3*index+offset] is not None and values[3*index+2] == values[3*index+offset]]
            cases.append((f'history-{function}-{metric}-{date}', f"record_{function}('', '', '{metric}', '历史', '{date}', '', '', '') = True", expected, 'HistoricalFeatureScan'))
con.close()
client = oracle.WslDoris('dsl-doris-official-01a104f9', 'dsl-doris-official')
report = {'purpose': 'NEW_REGISTRY_FEATURE_COMPATIBILITY_DIAGNOSTIC', 'acceptanceEligible': False,
    'jarSha256': oracle.digest(jar), 'historyCatalogSha256': oracle.digest(history_path),
    'rollingCatalogSha256': oracle.digest(rolling_path), 'checks': []}
with tempfile.TemporaryDirectory() as temp:
    for name, dsl, expected, required in cases:
        artifact = oracle.compile_case('D:/Java/jdk-21/bin/java.exe', jar, dsl, Path(temp) / 'case.dsl', history['snapshotId'],
            historical_features=history_path, manifest_sha256=history['manifestSha256'], rolling_features=rolling_path)
        kinds = [node['kind'] for node in artifact['logicalPlan']]
        actual = [(int(m), code) for m, code in client.query(oracle.bind_sql(artifact['sql'], artifact['bindings']))]
        report['checks'].append({'name': name, 'dsl': dsl, 'status': 'PASS' if actual == expected and required in kinds else 'FAIL',
            'requiredPlanNode': required, 'planNodes': kinds, 'rows': len(actual), 'referenceRows': len(expected),
            'onlyActual': sorted(set(actual)-set(expected))[:10], 'onlyExpected': sorted(set(expected)-set(actual))[:10]})
assert client.query('SELECT COUNT(*) FROM newzl.data_snapshot_registry') == [('0',)]
report['passed'] = sum(row['status'] == 'PASS' for row in report['checks'])
report['total'] = len(cases)
report['status'] = 'PASS' if report['passed'] == report['total'] == 42 else 'FAIL'
(folder / 'feature-catalog-query-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(report['status'], report['passed'], report['total'])
assert report['status'] == 'PASS'
