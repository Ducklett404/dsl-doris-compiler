"""Check that performance claims reject corrupted samples and feature provenance."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import tempfile
from summarize_performance import verify


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args()
    folder=args.folder.resolve();baseline=verify(folder)
    checks=[{'name':'valid-evidence-accepted','status':'PASS'}]
    with tempfile.TemporaryDirectory(prefix='dsl-performance-evidence-') as directory:
        temporary=Path(directory).resolve()
        assert temporary.is_relative_to(Path(tempfile.gettempdir()).resolve())
        staged=temporary/'report';shutil.copytree(folder,staged)
        for name in ('wrong-percentile','missing-sample','result-mismatch','cleanup-missing',
                     'wrong-feature-manifest','missing-feature-date','wrong-feature-partition'):
            report=copy.deepcopy(baseline);result=report['measurements']['results'][0];changed=None
            if name=='wrong-percentile':result['baseline']['p95Millis']+=1
            elif name=='missing-sample':result['samples'].pop()
            elif name=='result-mismatch':result['samples'][0]['resultEqual']=False
            elif name=='cleanup-missing':report['temporaryReaderRemoved']=False
            elif name=='wrong-feature-manifest':report['historicalFeatures']['manifestSha256']='0'*64
            elif name=='missing-feature-date':report['historicalFeatures']['completeDates']={}
            else:
                changed=staged/result['id']/'optimized-explain.txt';original=changed.read_bytes()
                changed.write_text(changed.read_text(encoding='utf-8').replace('partitions=1/2','partitions=2/2'),encoding='utf-8')
            (staged/'diagnostic-summary.json').write_text(json.dumps(report),encoding='utf-8')
            try:verify(staged)
            except AssertionError:checks.append({'name':name+'-rejected','status':'PASS'})
            else:raise AssertionError(name+' was incorrectly accepted')
            finally:
                if changed:changed.write_bytes(original)
    (folder/'evidence-selftest.json').write_text(json.dumps({'status':'PASS','checks':checks},indent=2)+'\n',encoding='utf-8')
    print('PASS: valid evidence accepted; seven corrupted evidence variants rejected')


if __name__=='__main__':main()
