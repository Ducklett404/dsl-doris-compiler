"""Hand-labelled regressions for project window SQL and its accompanying coverage queries.

Run after packaging the compiler with Python, DuckDB and java on PATH.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import duckdb
from validate_project_sources import ROOT


DAY = '2026-04-14'
WEEKEND = '2026-04-12'
# For a three-row window the recent interval starts on March 5 (inclusive).
# The two SHARED listings deliberately have different prices and trading dates.
PRICES = {
    (0, 'SHARED'): [('2026-03-05', 2), ('2026-04-13', 2), (DAY, 2)],
    (1, 'SHARED'): [('2019-01-02', 90), ('2025-11-03', 2), ('2026-03-05', 5), (DAY, 11)],
    (1, 'DENSE'): [('2026-03-04', 2), ('2026-03-05', 8), ('2026-04-13', 8), (DAY, 8)],
    (1, 'LATE'): [(DAY, 22)],
    (1, 'NULL-DAY'): [('2026-03-01', 1), ('2026-04-13', 3), (DAY, None)],
    (1, 'NULL-OLD'): [('2025-08-11', 100), ('2025-12-18', None), ('2026-04-13', 3), (DAY, 50)],
    (1, 'SUSPENDED'): [('2026-03-04', 9), ('2026-03-05', 9), ('2026-04-13', 9)],
    (1, 'FUTURE'): [('2026-04-15', 42)],
}
FLOWS = [(0, 'SHARED', DAY, 1), (1, 'SHARED', DAY, 7), (1, 'DENSE', DAY, 1),
         (1, 'LATE', DAY, -999999), (1, 'NULL-DAY', DAY, 1), (1, 'NULL-OLD', '2026-04-13', 1)]

MA = f"indicator('', '', '3日均线', '{DAY}', '', '', '') >= 6"
RANK = (f"indicator('', '', '主力净流入', '{DAY}', '', '', '') > 0 then "
        f"rank('', '', '收盘价', 'desc:row_number', '{DAY}', '', '', '') <= 2")
CASES = [
    (MA, [(1, 'DENSE'), (1, 'SHARED')], 6, 0, {'3日均线': {'LATE', 'NULL-DAY', 'NULL-OLD'}}),
    (RANK, [(1, 'SHARED'), (1, 'DENSE')], 6, 1, {'主力净流入': {'LATE', 'NULL-OLD'}, '收盘价': {'NULL-DAY'}}),
    (MA.replace(DAY, WEEKEND), [], 0, 0, {'3日均线': set()}),
    (RANK.replace(DAY, WEEKEND), [], 0, 0, {'主力净流入': set(), '收盘价': set()}),
]


class RecentHistoryTest(unittest.TestCase):
    def test_generated_selection_and_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            inp = Path(temp)/'inputs.json'
            inp.write_text(json.dumps([c[0] for c in CASES]), encoding='utf-8')
            artifacts = json.loads(subprocess.check_output([
                'java', '-Dfile.encoding=UTF-8', '-cp', str(ROOT/'target/dsl-doris-compiler.jar'),
                str(ROOT/'scripts/doris/ProjectWindowCompile.java'), str(inp)], timeout=45))
        self.assertEqual(len(artifacts), len(CASES))
        with duckdb.connect() as con:
            con.execute('CREATE SCHEMA newzl')
            con.execute('CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INT,tgtcode VARCHAR,bizdate DATE,closePrice DECIMAL(19,4))')
            con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES (?,?,?,?)',
                            [(m, c, d, v) for (m,c), history in PRICES.items() for d,v in history])
            con.execute('CREATE TABLE newzl.v_hsj_stock_hq_ext(mktcode INT,tgtcode VARCHAR,bizdate DATE,ZJLXMainNetTur BIGINT)')
            con.executemany('INSERT INTO newzl.v_hsj_stock_hq_ext VALUES (?,?,?,?)', FLOWS)

            def run(sql, params):
                return con.execute(sql.replace('`','"'), params).fetchall()

            for (dsl, expected, observed, ext_missing, unavailable), paths in zip(CASES, artifacts):
                self.assertEqual(set(paths), {'reference', 'project'})
                for mode, artifact in paths.items():
                    with self.subTest(dsl=dsl, mode=mode):
                        self.assertEqual(run(artifact['sql'], artifact['bindings']), expected)
                        plan = artifact['coveragePlan']
                        fields = [i['indicator'] for i in plan['inputs']]
                        self.assertCountEqual(fields, unavailable.keys())
                        counts = (observed, ext_missing, *(len(unavailable[k]) for k in fields))
                        self.assertEqual(run(plan['sql'], plan['bindings']), [counts])
                        missing_codes = sorted(set().union(*unavailable.values()))
                        samples = [(1, code, int(bool(ext_missing and code == 'NULL-OLD')),
                                    *(int(code in unavailable[k]) for k in fields)) for code in missing_codes]
                        self.assertEqual(run(plan['samplesSql'], plan['bindings']), samples)
                        combined = run(plan['combinedSql'], plan['bindings'])
                        self.assertTrue(combined)
                        self.assertTrue(all(row[:len(counts)] == counts for row in combined))
                        self.assertEqual([row[len(counts):] for row in combined
                                          if any(v == 1 for v in row[len(counts)+2:])], samples)
                nodes = [n['kind'] for n in paths['project']['logicalPlan']]
                if '3日均线' in dsl:
                    self.assertIn('RecentHistory', nodes)
                else:
                    self.assertNotIn('ObservedTail', nodes)
                    self.assertIn('b.bizdate = ?', paths['project']['sql'])


if __name__ == '__main__':
    unittest.main()
