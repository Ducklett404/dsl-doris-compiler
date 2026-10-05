"""Execute both generated RSI paths on hand-labelled sparse/NULL/short/future rows."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import duckdb
from validate_project_sources import ROOT, digest


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--java', default='D:/Java/jdk-21/bin/java.exe'); args = parser.parse_args()
    if args.output.exists(): raise ValueError('Preserve prior evidence')
    vectors = {'000001': [999, 3, 1, 2], '000002': [1, 2, 3], '000003': [3, None, 2],
               '000004': [3, 2], '000005': [3, 2, 1], '000006': [1, 1, 1], '000007': [3, 1, 2]}
    rows = []
    for code, values in vectors.items():
        dates = ['2006-01-04', '2026-01-04', '2026-02-01', '2026-04-14'][-len(values):]
        if code == '000007': dates[-1] = '2026-04-13'
        rows += [(1, code, day, price) for day, price in zip(dates, values)]
    rows += [(103, '000001', day, price) for day, price in zip(['2026-01-04', '2026-02-01', '2026-04-14'], [3, 1, 2])]
    rows += [(1, '000008', '2026-04-15', 99999), (1, '000001', '2026-04-15', 99999)]
    def rsi(n, count=''): return f"indicator('', '', 'RSI({n})', '2026-04-14', '', '', '{count}')"
    cases = [dict(name='gain-and-loss-sparse', dsl=rsi(2)+' > 30', expected=[['1','000001'],['103','000001']], missing=[4], tail=True),
        dict(name='zero-rsi', dsl=rsi(2)+' < 1', expected=[['1','000005']], missing=[4], tail=True),
        dict(name='null-short-flat-no-loss', dsl=rsi(2)+' >= 0', expected=[['1','000001'],['1','000005'],['103','000001']], missing=[4], tail=True),
        dict(name='one-delta', dsl=rsi(1)+' < 1', expected=[['1','000004'],['1','000005']], missing=[5], tail=True),
        dict(name='two-rsi-windows', dsl=rsi(1)+' < 1 or '+rsi(2)+' > 30', expected=[['1','000001'],['1','000004'],['1','000005'],['103','000001']], missing=[4,5], tail=True),
        dict(name='all-short', dsl=rsi(20)+' >= 0', expected=[], missing=[7], tail=True),
        dict(name='count-needs-earlier-rsi', dsl=rsi(2,'CONS>=2日')+' >= 0', expected=[['1','000001']], missing=[0,4,6], tail=True),
        dict(name='mixed-ma-tail', dsl=rsi(2)+" > 30 and indicator('', '', '3日均线', '2026-04-14', '', '', '') > 1", expected=[['1','000001'],['103','000001']], missing=[2,4], tail=True)]
    report = dict(purpose='HAND_LABELLED_PROJECT_RSI_TAIL_BOUNDARIES', engine='DuckDB', officialAcceptanceEligible=False,
        jarSha256=digest(ROOT/'target/dsl-doris-compiler.jar'), checks=[], fixtureRows=rows)
    try:
        with tempfile.TemporaryDirectory(prefix='project-rsi-') as temporary:
            path = Path(temporary)/'cases.json'; path.write_text(json.dumps([c['dsl'] for c in cases]), encoding='utf-8')
            completed = subprocess.run([args.java, '-Dfile.encoding=UTF-8', '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8', '-cp', str(ROOT/'target/dsl-doris-compiler.jar'),
                str(ROOT/'scripts/doris/ProjectWindowCompile.java'), str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            if completed.returncode: raise RuntimeError(completed.stderr)
            artifacts = json.loads(completed.stdout)
        con = duckdb.connect(); con.execute('CREATE SCHEMA newzl')
        con.execute('CREATE TABLE newzl.v_hsj_stock_hq_basic(mktcode INTEGER,tgtcode VARCHAR,bizdate DATE,closePrice DOUBLE)')
        con.executemany('INSERT INTO newzl.v_hsj_stock_hq_basic VALUES(?,?,?,?)', rows)
        def query(sql, bindings): return [list(r) for r in con.execute(sql.replace('`','"'), bindings).fetchall()]
        for case, paths in zip(cases, artifacts):
            outputs = []
            for mode, artifact in paths.items():
                result = [[str(v) for v in row] for row in query(artifact['sql'], artifact['bindings'])]
                coverage = artifact['coveragePlan']; counts = query(coverage['sql'], coverage['bindings'])[0]
                samples = query(coverage['samplesSql'], coverage['bindings'])
                combined = query(coverage['combinedSql'], coverage['bindings'])
                width = len(counts)
                merged_samples = [r[width:] for r in combined if any(v == 1 for v in r[width+2:])]
                if any(r[:width] != counts for r in combined) or merged_samples != samples:
                    raise AssertionError(case['name']+' combined diagnostics mismatch')
                correct = result == case['expected'] and counts[:2] == [7,0] and sorted(counts[2:]) == case['missing']
                tail = 'observed_tail AS' in artifact['sql']
                correct &= tail == (case['tail'] if mode == 'project' else False)
                record = dict(name=case['name'], mode=mode, status='PASS' if correct else 'FAIL', rows=result, counts=counts, samples=samples)
                report['checks'].append(record); outputs.append((result, counts, samples))
                if not correct: raise AssertionError(case['name']+' '+mode)
            if outputs[0] != outputs[1]: raise AssertionError(case['name']+' reference/project mismatch')
        con.close()
    except Exception as error: report['fatalError'] = str(error); raise
    finally:
        report.update(status='FAIL' if 'fatalError' in report else 'PASS', passed=sum(c['status']=='PASS' for c in report['checks']), total=len(report['checks']))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','passed','total']}))


if __name__ == '__main__': main()
