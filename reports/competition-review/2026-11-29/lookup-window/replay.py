"""Replay the frozen 112 cases, then two further serial rounds of the 21 target cases."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def digest(rows):
    data = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def http(case, url):
    body = json.dumps(dict(dsl=case['dsl'], snapshotId='stock-20060104-20260414-v1', maxRows=10000)).encode()
    req = urllib.request.Request(url, body, {'Content-Type': 'application/json',
                                            'Authorization': 'Bearer '+os.environ['DSL_HTTP_TOKEN']})
    start = time.perf_counter_ns()
    try:
        with urllib.request.urlopen(req, timeout=90) as res:
            status, raw = res.status, res.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except OSError as e:
        status, raw = 0, json.dumps({'error': str(e)}).encode()
    ms = (time.perf_counter_ns()-start)/1e6
    try:
        response = json.loads(raw)
    except ValueError:
        response = {'error': 'Invalid JSON response'}
    return dict(ms=ms, status=status, response=response)


def record(case, lane, epoch, raw):
    result = raw['response'] if lane=='HTTP' else raw
    rows = result.get('rows')
    return dict(id=case['id'], lane=lane, epoch=epoch, ms=raw['ms'],
                status=raw.get('status'), columns=result.get('columns'), truncated=result.get('truncated'),
                actualRows=len(rows) if rows is not None else None,
                actualDigest=digest(rows) if rows is not None else None,
                error=result.get('error'), timings=result.get('timings'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out', type=Path)
    p.add_argument('--cases', type=Path, default=HERE/'cases.json')
    p.add_argument('--rounds', type=int, choices=(1,2,3), default=3)
    p.add_argument('--url', default='http://127.0.0.1:8082/execute')
    p.add_argument('--jar', type=Path, default=REPO/'target/dsl-doris-compiler.jar')
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.cases.read_text())
    with tempfile.TemporaryDirectory() as tmp, (args.out/'samples.jsonl').open('w') as logs:
        jar = str(args.jar.resolve())
        subprocess.run(['javac','-cp',jar,'-d',tmp,str(HERE/'LookupProbe.java'),
                        str(REPO/'scripts/doris/DorisPerformanceDiagnostic.java')], check=True)
        for epoch in range(1, args.rounds+1):
            batch = [x for x in cases if epoch==1 or x['target']]
            random.Random(20261129+epoch).shuffle(batch)
            for lane in (('HTTP','JDBC') if epoch%2 else ('JDBC','HTTP')):
                folder = args.out/f'{lane}-{epoch}'
                folder.mkdir()
                if lane=='JDBC':
                    inputs = Path(tmp)/'inputs.json'
                    inputs.write_text(json.dumps(batch,ensure_ascii=False))
                    subprocess.run(['java','-cp',jar+os.pathsep+tmp,'LookupProbe',
                                    str(inputs),str(folder)],check=True)
                for case in batch:
                    path = folder/(case['id']+'.json.gz')
                    if lane=='JDBC':
                        with gzip.open(path,'rt') as f: raw=json.load(f)
                    else:
                        raw = http(case,args.url)
                        with gzip.open(path,'wt') as f: json.dump(raw,f,ensure_ascii=False)
                    print(json.dumps(record(case,lane,epoch,raw),ensure_ascii=False),file=logs,flush=True)
                print(lane, epoch, len(batch), flush=True)


if __name__=='__main__':
    main()
