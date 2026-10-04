import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/doris'))
from summarize_performance import verify
folder=Path(sys.argv[1]).resolve()
baseline=verify(folder)
checks=[{'name':'valid-evidence-accepted','status':'PASS'}]
with tempfile.TemporaryDirectory(prefix='dsl-performance-evidence-') as directory:
    temporary=Path(directory).resolve()
    assert temporary.is_relative_to(Path(tempfile.gettempdir()).resolve())
    staged=temporary/'report';shutil.copytree(folder,staged)
    for name in ('wrong-percentile','missing-sample','result-mismatch','cleanup-missing'):
        report=copy.deepcopy(baseline)
        result=report['measurements']['results'][0]
        if name=='wrong-percentile':result['baseline']['p95Millis']+=1
        elif name=='missing-sample':result['samples'].pop()
        elif name=='result-mismatch':result['samples'][0]['resultEqual']=False
        else:report['temporaryReaderRemoved']=False
        (staged/'diagnostic-summary.json').write_text(json.dumps(report),encoding='utf-8')
        try:verify(staged)
        except AssertionError:checks.append({'name':name+'-rejected','status':'PASS'})
        else:raise AssertionError(name+' was incorrectly accepted')
(folder/'evidence-selftest.json').write_text(json.dumps({'status':'PASS','checks':checks},indent=2)+'\n',encoding='utf-8')
print('PASS: valid evidence accepted; four malformed evidence variants rejected')
