"""Validate the run inventory, compare ordered digests, and recompute serial acceptance metrics."""
import argparse
import hashlib
from collections import Counter
import json
import math
from pathlib import Path
from replay import HERE, record
import gzip


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def stats(rows):
    times = sorted(s['ms'] for s in rows if s['ok'])
    def q(p): return round(times[math.ceil(len(times)*p)-1],3) if times else None
    return dict(attempts=len(rows), matched=len(times),
                within10s=sum(s['ok'] and s['ms']<=10000 for s in rows),
                medianMs=q(.5),p95Ms=q(.95),maxMs=q(1))


def verify(cases, rows, rounds, raw_dir):
    manifest=json.loads((HERE/'environment.json').read_text())['manifestSha256']
    index = {c['id']:c for c in cases}
    require(len(index)==len(cases),'Duplicate case ID')
    expected = {(case['id'],lane,n) for case in cases for lane in ('HTTP','JDBC')
                for n in range(1,rounds+1) if n==1 or case['target']}
    observed = Counter((s['id'],s['lane'],s['epoch']) for s in rows)
    require(observed==Counter(expected),'Missing, unexpected, or repeated attempts')
    for s in rows:
        case = index[s['id']]
        if raw_dir:
            with gzip.open(raw_dir/f"{s['lane']}-{s['epoch']}"/(s['id']+'.json.gz'),'rt') as f:
                raw=json.load(f)
                require(record(case,s['lane'],s['epoch'],raw)==s,'Raw evidence differs: '+s['id'])
                if s['lane']=='HTTP' and raw['status']==200:
                    response=raw['response']
                    limits=response['limits']
                    fields=('queryTimeoutSeconds','maxEstimatedScanRows','maxReturnRows','maxExecutionMemoryBytes')
                    require(tuple(limits[k] for k in fields)==(10,100000000,10000,2147483648),'Execution policy')
                    require(response['dataVersion']['manifestSha256']==manifest,'Snapshot mismatch')
                    if case['target']:
                        path='HistoricalLookup' if case['id'].startswith('count-') else 'EvaluationDateLookup'
                        require(any(n['kind']==path for n in response['compilation']['logicalPlan']),
                                'Unexpected lookup plan: '+case['id'])
        require(isinstance(s['ms'], (int,float)) and math.isfinite(s['ms']) and s['ms']>0,s['id'])
        s['ok'] = (s['error'] is None and s['actualDigest']==case['expectedDigest']
                   and s['actualRows']==case['expectedRows'] and s['columns']==['mktcode','tgtcode']
                   and (s['lane']=='JDBC' or s['status']==200 and s['truncated'] is False))
    return index


def load_stats(path, raw_dir):
    cases={c['id']:c for c in json.loads((HERE/'load-cases.json').read_text())}
    all_samples=lines(path)
    require(len(all_samples)==90,'Mixed load inventory')
    result={}
    for w in (1,4,8):
        batch=[s for s in all_samples if s['workers']==w]
        require(Counter(s['id'] for s in batch)==Counter({k:5 for k in cases}),'Mixed workload cases')
        require(sorted(s['request'] for s in batch)==list(range(30)),'Mixed workload IDs')
        for s in batch:
            c=cases[s['id']]
            if raw_dir:
                with gzip.open(raw_dir/'load'/f"{w}-{s['request']}.json.gz",'rt') as f:
                    raw=json.load(f)
                    expected=record(c,'HTTP',1,raw)
                    require(dict(expected,workers=w,request=s['request'],message=raw['response'].get('message'))==s,'Raw load evidence differs')
            s['ok']=(s['status']==200 and s['truncated'] is False and s['columns']==['mktcode','tgtcode']
                     and s['actualRows']==c['expectedRows'] and s['actualDigest']==c['expectedDigest'])
        result[w]=dict(stats(batch), errors=dict(Counter(s['error'] or 'unexpected result' for s in batch if not s['ok'])))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--samples', type=Path, default=HERE/'samples.jsonl')
    p.add_argument('--edges', type=Path, default=HERE/'edge-samples.jsonl')
    p.add_argument('--raw', type=Path, help='Parent containing final/ and edges/ raw archives')
    p.add_argument('--load', type=Path, default=HERE/'load-samples.jsonl')
    args=p.parse_args()
    cases=json.loads((HERE/'cases.json').read_text())
    edge_cases=json.loads((HERE/'edge-cases.json').read_text())
    samples=lines(args.samples)
    edges=lines(args.edges)
    index=verify(cases,samples,3,args.raw/'final' if args.raw else None)
    verify(edge_cases,edges,3,args.raw/'edges' if args.raw else None)
    require(len(index)==112 and sum(c['target'] for c in cases)==21 and len(edge_cases)==8,'Wrong matrix')
    summary={}
    baseline=lines(HERE.parent/'逐例判定.jsonl')
    for lane in ('HTTP','JDBC'):
        old=[dict(s,id=s['group']+'-'+s['id'],ok=s['match']) for s in baseline
             if s['lane']==lane and s['group'] in ('complex','holdout')]
        require({s['id'] for s in old}==set(index) and len(old)==len(index),'Baseline case IDs')
        for s in old:
            c=index[s['id']]
            require((s['expectedRows'],s['expectedDigest'])==(c['expectedRows'],c['expectedDigest']),s['id'])
        current=[s for s in samples if s['lane']==lane]
        target=[s for s in current if index[s['id']]['target']]
        summary[lane]=dict(beforeAll=stats(old),beforeTarget=stats([s for s in old if index[s['id']]['target']]),
                           afterAll=stats([s for s in current if s['epoch']==1]),
                           afterTargetFirst=stats([s for s in target if s['epoch']==1]),
                           afterTargetAllRounds=stats(target),additionalCases=stats([s for s in edges if s['lane']==lane]))
    quality=json.loads((HERE/'quality-digests.json').read_text())
    require({x['id'] for x in quality['cases']}=={x['group']+'-'+x['id'] for x in baseline
            if x['lane']=='HTTP' and x['group'] in ('complex','holdout') and x['match']},'Coverage inventory')
    for q in quality['cases']:
        require(q['before']==q['after'],'Changed availability: '+q['id'])
        if args.raw:
            with gzip.open(args.raw/'final/HTTP-1'/(q['id']+'.json.gz'),'rt') as f:
                data=json.load(f)['response']['dataQuality']
            encoded=json.dumps({k:data[k] for k in quality['keys']},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            require(hashlib.sha256(encoded).hexdigest()==q['after'],'Availability digest: '+q['id'])
    print(json.dumps(dict(serial=summary,mixedLoad=load_stats(args.load,args.raw)),indent=2))
    if any(v['within10s']!=v['attempts'] for lane in summary.values()
           for k,v in lane.items() if not k.startswith('before')):
        raise SystemExit('At least one serial case exceeded the limit or returned an incorrect/incomplete result')


if __name__=='__main__':
    main()
