"""Repeat the previous six-template workbench workload with the original request order."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import random
from replay import HERE, http, record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('out',type=Path)
    p.add_argument('--url',default='http://127.0.0.1:8082/execute')
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    cases=json.loads((HERE/'load-cases.json').read_text())
    batch=cases*5
    random.Random(87).shuffle(batch)
    with (args.out/'samples.jsonl').open('w') as f:
        for workers in (1,4,8):
            def run(pair):
                n,case=pair
                raw=http(case,args.url)
                with gzip.open(args.out/f'{workers}-{n}.json.gz','wt') as archive:
                    json.dump(raw,archive,ensure_ascii=False)
                return dict(record(case,'HTTP',1,raw),workers=workers,request=n,
                            message=raw['response'].get('message'))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for s in pool.map(run,enumerate(batch)):
                    print(json.dumps(s,ensure_ascii=False),file=f,flush=True)
            print(workers,len(batch),flush=True)


if __name__=='__main__':
    main()
