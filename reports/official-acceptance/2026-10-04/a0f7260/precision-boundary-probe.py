"""Read-only reproduction of risePct precision and screening boundary errors."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris, bind_sql, compile_case, sql_literal
import duckdb

folder = Path(__file__).resolve().parent
con = duckdb.connect(str(ROOT / 'target/data-audit/acceptance-a0f7260.duckdb'), read_only=True)
client = WslDoris('dsl-doris-official-01a104f9', 'dsl-doris-official')
jar = ROOT / 'target/dsl-doris-compiler.jar'
report = {'purpose': 'READ_ONLY_PRECISION_BUG_REPRODUCTION', 'changesApplied': False,
          'oracleSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'jarSha256': hashlib.sha256(jar.read_bytes()).hexdigest(),
          'viewRisePctType': [r for r in client.query('DESCRIBE newzl.v_hsj_stock_hq_basic') if r[0] == 'risePct'],
          'scopeNumericTolerance': {'absolute': '0.000001', 'relative': '0.00000001'}, 'dates': []}
with tempfile.TemporaryDirectory(prefix='rise-precision-') as temp:
    for date in ['2006-01-04', '2018-08-20', '2026-04-10', '2026-04-13', '2026-04-14']:
        raw = con.execute('SELECT mktcode,tgtcode,lastPx,preClosePx FROM newzl.hsj_stock_hq_basic WHERE bizdate=CAST(? AS DATE)', [date]).fetchall()
        expected = {(int(m), code): None if last is None or previous in (None, 0) else (Decimal(last) - Decimal(previous)) * 100 / Decimal(previous) for m, code, last, previous in raw}
        cast_expression = 'CASE WHEN preClosePx IS NULL OR preClosePx=0 THEN NULL ELSE (CAST(lastPx AS DOUBLE)-CAST(preClosePx AS DOUBLE))*100.0/CAST(preClosePx AS DOUBLE) END'
        sql = 'SELECT mktcode,tgtcode,risePct,' + cast_expression + ' corrected FROM newzl.v_hsj_stock_hq_basic WHERE bizdate=' + sql_literal(date) + ' ORDER BY mktcode,tgtcode'
        values = client.query(sql)
        mismatches = []
        cast_mismatches = []
        for m, code, actual, cast in values:
            key = (int(m), code); e = expected[key]
            a = None if actual == 'NULL' else Decimal(actual)
            c = None if cast == 'NULL' else Decimal(cast)
            tolerance = max(Decimal('0.000001'), abs(e or 0) * Decimal('0.00000001'))
            if (e is None and a is not None) or (e is not None and (a is None or abs(a-e) > tolerance)):
                mismatches.append({'key': key, 'expected': str(e), 'actual': str(a), 'absoluteError': str(abs(a-e))})
            if (e is None and c is not None) or (e is not None and (c is None or abs(c-e) > tolerance)):
                cast_mismatches.append({'key': key, 'expected': str(e), 'cast': str(c)})
        record = {'date': date, 'rowsChecked': len(values), 'existingOutOfTolerance': len(mismatches),
                  'explicitDoubleCastOutOfTolerance': len(cast_mismatches), 'examples': mismatches[:5]}
        if mismatches:
            example = mismatches[0]
            key = tuple(example['key'])
            threshold = (Decimal(example['expected']) + Decimal(example['actual'])) / 2
            dsl = f"indicator('', '', '涨跌幅', '{date}', '', '', '') > {threshold}"
            artifact = compile_case('D:/Java/jdk-21/bin/java.exe', jar, dsl, Path(temp) / 'case.dsl', 'stock-20060104-20260414-v1')
            generated = [(int(m), code) for m, code in client.query(bind_sql(artifact['sql'], artifact['bindings']))]
            reference = sorted(k for k, v in expected.items() if v is not None and v > threshold)
            corrected = [(int(m), code) for m, code in client.query('SELECT mktcode,tgtcode FROM newzl.v_hsj_stock_hq_basic WHERE bizdate=' + sql_literal(date) + ' AND (' + cast_expression + ')>' + str(threshold) + ' ORDER BY mktcode,tgtcode')]
            record['boundary'] = {'dsl': dsl, 'key': key, 'threshold': str(threshold),
                  'projectGeneratedMatchesRaw': generated == reference,
                  'explicitDoubleCastMatchesRaw': corrected == reference,
                  'onlyGenerated': sorted(set(generated)-set(reference))[:10],
                  'onlyReference': sorted(set(reference)-set(generated))[:10],
                  'sql': artifact['sql'], 'bindings': artifact['bindings']}
        report['dates'].append(record)
        print(date + ': old out-of-tolerance=' + str(len(mismatches)) + ', explicit cast=' + str(len(cast_mismatches)), flush=True)
con.close()
report['bugReproduced'] = all(r['existingOutOfTolerance'] > 0 and not r['boundary']['projectGeneratedMatchesRaw'] for r in report['dates'])
report['proposedExpressionVerified'] = all(r['explicitDoubleCastOutOfTolerance'] == 0 and r['boundary']['explicitDoubleCastMatchesRaw'] for r in report['dates'])
(folder / 'precision-boundary-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
if not report['bugReproduced'] or not report['proposedExpressionVerified']:
    raise SystemExit(1)
