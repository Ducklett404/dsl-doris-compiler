import datetime
import hashlib
import json
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'reports/performance-diagnostic/2026-10-04/hot-30'
manifest_path=ROOT/'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
report=json.loads((folder/'diagnostic-summary.json').read_text(encoding='utf-8'))
checks=[]
for table,item in manifest['files'].items():
    source=(ROOT.parent/item['relativePath']).resolve()
    assert source.is_relative_to(ROOT.parent.resolve())
    with source.open('rb') as file:sha=hashlib.file_digest(file,'sha256').hexdigest()
    equal=sha==item['sha256'] and source.stat().st_size==item['bytes']
    checks.append({'table':table,'sha256':sha,'bytes':source.stat().st_size,'matchesManifest':equal})
    assert equal,table
(folder/'source-integrity.json').write_text(json.dumps({'status':'PASS','checkedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':checks},indent=2)+'\n',encoding='utf-8')
sources={'compilerJar':ROOT/'target/dsl-doris-compiler.jar','manifest':manifest_path,
    'matrix':ROOT/'benchmarks/doris-matrix-v1.json','audit':ROOT/'reports/data-inspection/2026-10-04/全量数据检查.json',
    'javaDiagnostic':ROOT/'scripts/doris/DorisPerformanceDiagnostic.java',
    'pythonDiagnostic':ROOT/'scripts/doris/diagnose_performance.py'}
for name,path in sources.items():assert hashlib.sha256(path.read_bytes()).hexdigest()==report['hashes'][name],name
prior=json.loads((ROOT/'reports/continuation/2026-10-04/continuation-summary.json').read_text(encoding='utf-8'))
assert prior['artifactHashes']['compilerJarSha256']==report['hashes']['compilerJar']
archive=folder/'tool-sources';archive.mkdir(exist_ok=True)
for source in (ROOT/'scripts/doris/DorisPerformanceDiagnostic.java',ROOT/'scripts/doris/diagnose_performance.py',
    ROOT/'scripts/doris/summarize_performance.py',ROOT/'target/performance-evidence-selftest.py',Path(__file__)):
    shutil.copy2(source,archive/source.name)
summary={'status':'PASS','cases':12,'timedQueries':720,'pathComparisons':360,'warmupQueries':24,'explainPlans':24,
    'evidenceSelftest':json.loads((folder/'evidence-selftest.json').read_text()),
    'sourceIntegrity':'PASS','measurementArtifactsMatchCurrent':'PASS','compilerJarUnchangedSincePreviousJavaSelftests':True,
    'previousJavaSelftestEvidence':'../../../continuation/2026-10-04/continuation-summary.json',
    'officialRegistryUnchanged':report['officialRegistryUnchanged'],'temporaryReaderRemoved':report['temporaryReaderRemoved'],
    'officialAcceptance':'BLOCKED','toolSources':[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(archive.iterdir())]}
(folder/'verification-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('PASS: 3 source files unchanged, 6 measurement artifacts match, previous tested JAR preserved')
