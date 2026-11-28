"""Verify published case counts and paired timings using the Python standard library."""
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def p95(samples):
    return sorted(samples)[math.ceil(len(samples) * 0.95) - 1]


def main():
    summary = json.loads((ROOT / '汇总.json').read_bytes())
    groups = defaultdict(list)
    for line in (ROOT / '逐例判定.jsonl').read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        ok = (record['expectedDigest'] == record['actualDigest']
              and record['expectedRows'] == record['actualRows'])
        if record['lane'] == 'HTTP':
            ok = (ok and record['http'] == 200 and record['truncated'] is False
                  and record['columns'] == ['mktcode', 'tgtcode'])
        require(ok == record['match'], record['id'])
        groups[record['lane'], record['group']].append(record)

    for lane, section, limit_field in [('HTTP', 'http', 'completeWithin10'), ('JDBC', 'direct', 'within10')]:
        require({g for l, g in groups if l == lane} == set(summary[section]), lane)
        for name, result in summary[section].items():
            cases = groups[lane, name]
            within = sum(r['match'] and r['ms'] <= 10000 for r in cases)
            matched = sum(r['match'] for r in cases)
            require(len(set(r['id'] for r in cases)) == len(cases) == result['total'], name)
            require(matched == result['correct'] and within == result[limit_field], name)
            print(f'{lane} {name}  matched={matched}/{len(cases)}  within10s={within}')

    for lane in ('history-30', 'aggregate-30'):
        data = json.loads((ROOT/'特征复测'/lane/'jdbc-results.json').read_bytes())
        case = next(r for r in data['results'] if r['id'] == 'nineteen-year-history')
        samples = case['samples']
        require(case['status'] == 'PASS' and len(samples) == 30 and all(s['resultEqual'] for s in samples), lane)
        ratio = p95([s['baselineMillis'] for s in samples]) / p95([s['optimizedMillis'] for s in samples])
        require(math.isclose(ratio, case['p95Ratio'], rel_tol=1e-12), lane)
        print(f'{lane}  P95 speedup={ratio:.2f}x')


if __name__ == '__main__':
    main()
