"""Re-derive denominators, row comparisons and percentiles from evidence on disk."""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
def read(p):
    return json.loads(gzip.open(p,'rb').read() if p.suffix=='.gz' else p.read_bytes())

def stats(times):
    data=sorted(times)
    if not data:return {}
    return {k:data[math.ceil(q*len(data))-1] for k,q in [('p50',.5),('p95',.95),('p99',.99),('max',1.)]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path,nargs='?',default=HERE)
    args=parser.parse_args()
    root=args.folder.resolve()
    summary={'http':{},'quality':{},'direct':{},'history':{},'compiler':[],'httpCompile':{},'load':{}}
    expected_sizes={'complex':48,'holdout':64,'fields':94,'expanded':67,'golden':24,'combination':79,'rank':172}
    for folder in ['接口全量','接口补充','冻结组合与排名']:
        raw=[read(p) for p in sorted((root/folder).glob('*.gz'))]
        index=[json.loads(l) for l in (root/folder/'index.jsonl').read_text().splitlines()]
        assert len(raw)==len(index) and {x['summary']['id']+x['summary']['group'] for x in raw}=={x['id']+x['group'] for x in index}
        for group,records in __import__('itertools').groupby(sorted(raw,key=lambda v:v['summary']['group']),key=lambda v:v['summary']['group']):
            records=list(records)
            assert len({x['summary']['id'] for x in records})==len(records)==expected_sizes[group]
            failures=[]
            ok_rows=[]
            errors=collections.Counter()
            observed_checks=[]
            for x in records:
                r=x['response']
                s=x['summary']
                rows=r.get('rows')
                expected=x['expected']
                match=rows==expected if x.get('ordered',True) else rows is not None and sorted(rows)==sorted(expected)
                ok=s['status']==200 and match and r.get('columns')==['mktcode','tgtcode'] and r.get('truncated') is False
                assert ok==s['match']
                if ok:
                    ok_rows.append(s)
                    if 'observed' in x:
                        q=r['dataQuality']
                        observed_checks.append((s['id'],q['observedSecurities']==x['observed'] and q['coverageStatus']==x['coverageStatus']))
                else:
                    reason=r.get('error') or ('TRUNCATED' if r.get('truncated') else 'MISMATCH')
                    errors[reason]+=1
                    failures.append(dict(id=s['id'],error=reason,httpMs=s['httpMs']))
            summary['http'][group]=dict(total=len(records),correct=len(ok_rows),completeWithin10=sum(s['httpMs']<=10000 for s in ok_rows),expectedEmpty=sum(not x['expected'] for x in records),returnedEmpty=sum(s['actualRows']==0 for s in ok_rows),successWall=stats([s['httpMs'] for s in ok_rows]),allResponsesWall=stats([x['summary']['httpMs'] for x in records]),mainExecuteFetch=stats([s['timings']['dorisExecutionMillis']+s['timings']['returnMillis'] for s in ok_rows]),errors=errors,failures=failures)
            if observed_checks:summary['quality'][group]=dict(compared=len(observed_checks),failures=[k for k,v in observed_checks if not v])
    direct_input={x['id']:x for x in read(root/'主SQL输入.json.gz')}
    direct_records=[read(p) for p in sorted((root/'主SQL全量').glob('*.gz'))]
    assert set(direct_input)=={x['id'] for x in direct_records} and len(direct_records)==112
    for g in ['complex','holdout']:
        rec=[x for x in direct_records if x['id'].startswith(g+'-')]
        for x in rec:assert x['match']==('rows' in x and x['rows']==direct_input[x['id']]['expected'])
        summary['direct'][g]=dict(total=len(rec),correct=sum(x['match'] for x in rec),within10=sum(x['match'] and x['ms']<=10000 for x in rec),successTime=stats([x['ms'] for x in rec if x['match']]),failures=[dict(id=x['id'],error=x.get('error','MISMATCH'),ms=x.get('ms')) for x in rec if not x['match']],slow=[dict(id=x['id'],ms=x['ms']) for x in rec if x.get('ms',0)>10000])
    expected=read(root/'长周期独立预期.json')
    for group in ['history-30','aggregate-30','matrix-5','no-page-cache-20','history-recheck-30']:
        folder=root/'特征复测'/group
        result=read(folder/'jdbc-results.json')
        required={'history-30':7,'aggregate-30':7,'matrix-5':28,'no-page-cache-20':3,'history-recheck-30':2}[group]
        assert len({x['id'] for x in result['results']})==result['total']==required
        cases=[]
        for x in result['results']:
            ident=x['id']
            record={k:x[k] for k in ('id','category','status','error','rows','p95Ratio','historicalFeatureSelected','rollingFeatureSelected') if k in x}
            if x['status']=='PASS':
                assert len(x['samples'])==result['iterationsPerPath']
                for mode in ['baseline','optimized']:
                    record[mode]=stats([s[mode+'Millis'] for s in x['samples']])
                    assert record[mode]['p95']==x[mode]['p95Millis']
                ratios=sorted(s['baselineMillis']/s['optimizedMillis'] for s in x['samples'])
                record['pairedSpeedup']=dict(min=ratios[0],median=ratios[math.ceil(len(ratios)/2)-1],over10=sum(v>=10 for v in ratios))
                record['independentRowsMatch']=read(folder/ident/'result-rows.json')==expected[ident]['rows'] if ident in expected else None
                if record['independentRowsMatch'] is False:record['status']='MISMATCH'
            cases.append(record)
        summary['history'][group]=dict(cases=cases,rounds=result['iterationsPerPath'],concurrent=result.get('concurrentReadDiagnostic',{}).get('requests'))
    for i in range(1,4):
        doc=read(root/f'编译-{i}.json')
        summary['compiler'].append(doc['uncachedPipeline']['stages']['total'])
    for i in (1,4):
        doc=read(root/f'HTTP编译-{i}.json.gz')['samples']
        summary['httpCompile'][i]=dict(n=len(doc),passed=sum(x['ok'] for x in doc),time=stats([x['ms'] for x in doc if x['ok']]))
    for i in (1,4,8):
        doc=read(root/'接口并发'/f'workers-{i}.json')
        summary['load'][i]=dict(n=len(doc),passed=sum(x['match'] for x in doc),within10=sum(x['match'] and x['ms']<=10000 for x in doc),successTime=stats([x['ms'] for x in doc if x['match']]),errors=collections.Counter(x['error'] for x in doc if not x['match']))
    (root/'汇总.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
