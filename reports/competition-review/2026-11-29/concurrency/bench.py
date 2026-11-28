"""Measure the fixed workbench mixes; preserve raw HTTP JSON separately from shareable results."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys
import time

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / 'lookup-window'
sys.path.insert(0, str(PREVIOUS))
from replay import http, record

QUALITY_FIELDS = ('coverageStatus', 'observedSecurities', 'currentMissingExtensionRows',
                  'inputs', 'unavailableSamples', 'sampleDetails')


def read(path):
    return json.loads(path.read_bytes())


def workloads():
    mixed = read(PREVIOUS/'load-cases.json')
    frozen = {c['id']:c for c in read(PREVIOUS/'cases.json')}
    spec = read(HERE/'reference.json')
    distinct = [frozen[key] for key in spec['distinct']]
    if len(distinct) != 30 or len({c['dsl'] for c in distinct}) != 30:
        raise ValueError('Expected 30 different frozen DSLs')
    return {'mixed':mixed*5, 'distinct':distinct}


def batch(workload, epoch):
    cases = list(workload)
    random.Random(87 + epoch-1).shuffle(cases)
    return cases


def quality_digest(quality):
    fields = {k:quality[k] for k in QUALITY_FIELDS}
    data = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()
    return hashlib.sha256(data).hexdigest()


def adjudicate(case, key, archive):
    raw = archive['http']
    result = raw['response']
    quality = result.get('dataQuality')
    sample = record(case, 'HTTP', key['round'], raw)
    sample.update(key, startNs=archive['startNs'], endNs=archive['endNs'], message=result.get('message'),
                  qualityDigest=quality_digest(quality) if quality and all(k in quality for k in QUALITY_FIELDS) else None,
                  manifest=result.get('dataVersion',{}).get('manifestSha256'),
                  limits=result.get('limits'), diagnosticTimings=(quality or {}).get('diagnosticTimings'))
    return sample


def raw_filename(key):
    return f"{key['workload']}-{key['workers']}-{key['round']}-{key['request']:02}.json.gz"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out', type=Path)
    p.add_argument('--workload', nargs='+', choices=['mixed','distinct'], default=['mixed','distinct'])
    p.add_argument('--workers', type=int, nargs='+', choices=[1,4,8], default=[1,4,8])
    p.add_argument('--rounds', type=int, default=1)
    p.add_argument('--url', default='http://127.0.0.1:8082/execute')
    args = p.parse_args()
    if args.rounds < 1 or len(set(args.workload))!=len(args.workload) or len(set(args.workers))!=len(args.workers):
        p.error('Choose a positive round count and distinct workload and worker values')
    args.out.mkdir(parents=True, exist_ok=False)
    raw_dir = args.out/'raw'
    raw_dir.mkdir()
    (args.out/'run.json').write_text(json.dumps(dict(workloads=args.workload, workers=args.workers,
                                                      rounds=args.rounds, shuffleSeed=87),indent=2)+'\n')
    groups = workloads()
    clock = time.perf_counter_ns
    with (args.out/'samples.jsonl').open('x') as f:
        for epoch in range(1,args.rounds+1):
            for name in args.workload:
                cases = batch(groups[name],epoch)
                for workers in args.workers:
                    origin = clock()
                    def run(pair):
                        i, case = pair
                        begin = clock()
                        raw = http(case,args.url)
                        end = clock()
                        key = dict(workload=name,workers=workers,round=epoch,request=i)
                        archive = dict(startNs=begin-origin,endNs=end-origin,http=raw)
                        return key, case, archive
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        completed = list(pool.map(run,enumerate(cases)))
                    # Disk I/O and digest computation occur after the timed batch.
                    for key,case,archive in completed:
                        with gzip.open(raw_dir/raw_filename(key),'wt',encoding='utf8') as out:
                            json.dump(archive,out,ensure_ascii=False,separators=(',',':'))
                        print(json.dumps(adjudicate(case,key,archive),ensure_ascii=False),file=f)
                    f.flush()
                    print(name,workers,epoch,len(completed),flush=True)


if __name__=='__main__':
    main()
