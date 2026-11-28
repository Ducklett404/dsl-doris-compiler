"""Audit the 112 frozen expressions and eight independent boundary cases on JDBC and HTTP."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent/'lookup-window'
sys.path.insert(0,str(PREVIOUS))
from check import lines, stats, verify


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,help='Parent of regression/ and edges/ replay folders')
    args=parser.parse_args()
    result={}
    for group, fixture in [('regression','cases.json'),('edges','edge-cases.json')]:
        cases=json.loads((PREVIOUS/fixture).read_text())
        raw=args.raw/group if args.raw else None
        samples=lines(raw/'samples.jsonl' if raw else HERE/(group+'.jsonl'))
        verify(cases,samples,1,raw)
        result[group]={lane:stats([s for s in samples if s['lane']==lane]) for lane in ['HTTP','JDBC']}
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if any(lane['attempts']!=lane['within10s'] for group in result.values() for lane in group.values()):
        raise SystemExit('Regression: incorrect, incomplete or late response')


if __name__=='__main__':
    main()
