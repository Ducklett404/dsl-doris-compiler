"""Recheck every sampled field with the frozen numeric acceptance tolerance."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts/doris'))
import check_official_field_acceptance as oracle

folder = Path(__file__).resolve().parent
scope = ROOT / 'config/acceptance/stock-slot-phase1-scope-v1.json'
tolerance = json.loads(scope.read_text(encoding='utf-8'))['acceptanceDenominator']['resultContract']
absolute, relative = Decimal(str(tolerance['absoluteTolerance'])), Decimal(str(tolerance['relativeTolerance']))
con = oracle.duckdb.connect(str(ROOT / 'target/data-audit/acceptance-a0f7260.duckdb'), read_only=True)
client = oracle.WslDoris('dsl-doris-official-01a104f9', 'dsl-doris-official')
report = {'purpose': 'FROZEN_TOLERANCE_FIELD_DIAGNOSTIC', 'acceptanceEligible': False,
          'oracleSha256': oracle.digest(Path(oracle.__file__)), 'scopeSha256': oracle.digest(scope),
          'absoluteTolerance': str(absolute), 'relativeTolerance': str(relative),
          'toleranceRule': 'abs(actual-expected) <= max(absoluteTolerance, relativeTolerance*abs(expected))', 'dates': []}
for date in ['2006-01-04', '2018-08-20', '2026-04-10', '2026-04-13', '2026-04-14']:
    rows = con.execute('SELECT b.mktcode,b.tgtcode,' + ','.join('b.'+c for c in oracle.RAW_COLUMNS) + ',e.ZJLXMainNetTur net FROM newzl.hsj_stock_hq_basic b LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) WHERE b.bizdate=CAST(? AS DATE)', [date]).fetchall()
    expected = {(int(m), code): oracle.raw_values(dict(zip((*oracle.RAW_COLUMNS, 'net'), values))) for m, code, *values in rows}
    sql = 'SELECT b.mktcode,b.tgtcode,' + ','.join(f[1] for f in oracle.FIELDS) + ' FROM newzl.v_hsj_stock_hq_basic b LEFT JOIN newzl.v_hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate) WHERE b.bizdate=' + oracle.sql_literal(date)
    actual = client.query(sql)
    assert len(actual) == len(expected) and {(int(r[0]), r[1]) for r in actual} == set(expected)
    metrics = [{'field': name, 'checked': 0, 'nulls': 0, 'mismatches': 0, 'examples': []} for name, _, _ in oracle.FIELDS]
    for m, code, *values in actual:
        key = (int(m), code)
        for index, text in enumerate(values):
            e = expected[key][index]; a = None if text == 'NULL' else Decimal(text)
            metric = metrics[index]; metric['checked'] += 1; metric['nulls'] += e is None
            correct = (a is None) if e is None else (a is not None and a.is_finite() and abs(a-e) <= max(absolute, relative*abs(e)))
            if not correct:
                metric['mismatches'] += 1
                if len(metric['examples']) < 3:
                    metric['examples'].append({'key': key, 'expected': str(e), 'actual': str(a)})
    failures = sum(m['mismatches'] for m in metrics)
    report['dates'].append({'date': date, 'rows': len(expected), 'valuesChecked': len(expected)*len(metrics),
                            'mismatches': failures, 'status': 'FAIL' if failures else 'PASS', 'fields': metrics})
    print(date + ': ' + str(failures) + ' out-of-tolerance values', flush=True)
con.close()
report['totalValuesChecked'] = sum(r['valuesChecked'] for r in report['dates'])
report['totalMismatches'] = sum(r['mismatches'] for r in report['dates'])
report['failedFields'] = sorted({m['field'] for r in report['dates'] for m in r['fields'] if m['mismatches']})
report['status'] = 'FAIL' if report['totalMismatches'] else 'PASS'
(folder / 'all-field-tolerance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({k: report[k] for k in ['status', 'totalValuesChecked', 'totalMismatches', 'failedFields']}, ensure_ascii=False))
