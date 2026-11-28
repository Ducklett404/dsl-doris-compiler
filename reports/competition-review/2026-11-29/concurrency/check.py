"""Audit a concurrency run and print metrics. Add --raw to rederive every sample from its saved response."""
import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path

from bench import HERE, PREVIOUS, adjudicate, batch, raw_filename, read, workloads


def require(value, message):
    if not value:
        raise ValueError(message)


def nearest_p95(values):
    return sorted(values)[math.ceil(0.95*len(values))-1] if values else None


def elapsed_stats(values):
    return dict(p95Ms=nearest_p95(values), maxMs=max(values,default=None))


def audit_group(rows, ordered, reference, manifest, raw_dir):
    n = len(ordered)
    require(len(rows)==n and sorted(r['request'] for r in rows)==list(range(n)),
            'Incomplete or duplicate request sequence')
    workers = rows[0]['workers']
    complete = []
    late = []
    errors = Counter()
    observed = []
    intervals = []
    for r in sorted(rows,key=lambda x:x['request']):
        case = ordered[r['request']]
        require(case['id']==r['id'], 'Frozen request order mismatch')
        key = {k:r[k] for k in ('workload','workers','round','request')}
        if raw_dir:
            with gzip.open(raw_dir/raw_filename(key),'rt') as f:
                rebuilt = adjudicate(case,key,json.load(f))
            require(rebuilt==r,'Raw response differs: '+str(key))
        require(r['lane']=='HTTP' and r['epoch']==r['round'], 'Wrong lane or round')
        start, end = r['startNs'], r['endNs']
        ms = r['ms']
        require(type(start) is int and type(end) is int and 0<=start<end,
                'Invalid monotonic timestamps')
        require(isinstance(ms,(int,float)) and math.isfinite(ms) and 0<ms<=(end-start)/1e6+1e-6,
                'Invalid HTTP elapsed time')
        intervals.extend([(start,1),(end,-1)])
        observed.append(ms)
        if ms>10000:
            late.append(r['request'])
        if r['status']!=200 or r['error']:
            errors[r['message'] or r['error'] or str(r['status'])]+=1
            continue
        if r['actualDigest']!=case['expectedDigest'] or r['actualRows']!=case['expectedRows']:
            errors['Ordered list mismatch']+=1
        elif r['columns']!=['mktcode','tgtcode'] or r['truncated'] is not False:
            errors['Wrong columns or incomplete response']+=1
        elif r['qualityDigest']!=reference[case['id']]:
            errors['Data quality differs from validated serial run']+=1
        elif r['manifest']!=manifest:
            errors['Snapshot mismatch']+=1
        elif not isinstance(r['limits'],dict) or any(
                r['limits'].get(k)!=v for k,v in {
                    'queryTimeoutSeconds':10,'maxEstimatedScanRows':100000000,
                    'maxReturnRows':10000,'maxExecutionMemoryBytes':2147483648}.items()):
            errors['Resource limits differ']+=1
        else:
            complete.append(ms)

    concurrent, peak = 0, 0
    for timestamp, delta in sorted(intervals):
        concurrent+=delta
        peak=max(peak,concurrent)
    require(0<peak<=workers and concurrent==0, 'Concurrency exceeds requested workers')
    wall = (max(r['endNs'] for r in rows)-min(r['startNs'] for r in rows))/1e9
    within = sum(ms<=10000 for ms in complete)
    return dict(attempts=n,complete=len(complete),within10s=within,over10s=len(late),
                completeOver10s=len(complete)-within,allLatency=elapsed_stats(observed),
                completeLatency=elapsed_stats(complete),wallSeconds=wall,
                attemptsPerSecond=n/wall,correctPerSecond=len(complete)/wall,
                within10sPerSecond=within/wall,peakWorkers=peak,errors=dict(errors))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path,help='Directory containing run.json and samples.jsonl')
    p.add_argument('--raw', action='store_true',help='Also inspect run/raw/*.json.gz')
    p.add_argument('--require-sla',action='store_true',help='Exit with status 1 unless every attempt is complete within 10 s')
    args=p.parse_args()
    config=read(args.run/'run.json')
    groups=workloads()
    reference=read(HERE/'reference.json')['quality']
    manifest=read(PREVIOUS/'environment.json')['manifestSha256']
    names,workers,rounds=config['workloads'],config['workers'],config['rounds']
    require(names and len(names)==len(set(names)) and set(names)<=set(groups),'Invalid workloads')
    require(workers and len(workers)==len(set(workers)) and set(workers)<={1,4,8},'Invalid worker counts')
    require(type(rounds) is int and rounds>0 and config['shuffleSeed']==87,'Invalid run configuration')
    rows=[json.loads(line) for line in (args.run/'samples.jsonl').read_text().splitlines()]
    expected={(name,w,r) for name in names for w in workers for r in range(1,rounds+1)}
    require({(s['workload'],s['workers'],s['round']) for s in rows}==expected,'Wrong epoch inventory')
    summary=[]
    for name,w,r in sorted(expected):
        samples=[s for s in rows if (s['workload'],s['workers'],s['round'])==(name,w,r)]
        stats=audit_group(samples,batch(groups[name],r),reference,manifest,args.run/'raw' if args.raw else None)
        summary.append(dict(workload=name,workers=w,round=r,**stats))
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    if args.require_sla and any(s['within10s']!=s['attempts'] for s in summary):
        raise SystemExit(1)


if __name__=='__main__':
    main()
