"""Restart only the owned diagnostic container and prove immutable feature persistence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--catalogs',nargs='+',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();client=WslDoris(args.distribution,'dsl-doris-official')
    catalogs=[json.loads(p.read_text(encoding='utf-8')) for p in args.catalogs]
    if any(not re.fullmatch(r'dsl_(rolling|history)_diag_[0-9a-f]{12}\.(rolling_averages|history_extrema)_v1',c['qualifiedTable']) for c in catalogs):
        raise ValueError('Expected owned diagnostic feature tables')
    queries=['SELECT * FROM newzl.data_snapshot_registry',
        "SELECT source_table,row_count FROM (SELECT 'basic' source_table,COUNT(*) row_count FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info) counts ORDER BY source_table"]
    queries += [f"SELECT * FROM {c['qualifiedTable']} ORDER BY bizdate,mktcode,tgtcode" for c in catalogs]
    before_rows=[client.query(q) for q in queries]
    if before_rows[0]:raise ValueError('Expected the unregistered diagnostic source')
    snapshot_ids={c['snapshotId'] for c in catalogs}
    if len(snapshot_ids)!=1:raise ValueError('Feature catalogs refer to different sources')
    manifest=json.loads((ROOT/'data/doris/snapshots'/next(iter(snapshot_ids))/'manifest.json').read_text(encoding='utf-8'))
    expected_counts={label:manifest['files'][name]['rows'] for label,name in
        [('basic','hsj_stock_hq_basic'),('ext','hsj_stock_hq_ext'),('code','hsj_stock_code_info')]}
    if {name:int(count) for name,count in before_rows[1]}!=expected_counts:raise ValueError('Source counts differ from manifest')
    before=[hashlib.sha256(json.dumps(rows,ensure_ascii=True,separators=(',',':')).encode()).hexdigest() for rows in before_rows]
    restart=subprocess.run(['wsl.exe','-d',args.distribution,'--exec','docker','restart','dsl-doris-official'],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    if restart.returncode:raise RuntimeError('Owned diagnostic container restart failed')
    deadline=time.monotonic()+180;ready=False
    while time.monotonic()<deadline:
        try:
            if client.query('SELECT 1')==[('1',)]:ready=True;break
        except Exception:pass
        time.sleep(1)
    if not ready:raise RuntimeError('Diagnostic Doris did not become ready')
    after_rows=[client.query(q) for q in queries]
    after=[hashlib.sha256(json.dumps(rows,ensure_ascii=True,separators=(',',':')).encode()).hexdigest() for rows in after_rows]
    report={'purpose':'RESTART_PERSISTENCE_DIAGNOSTIC','acceptanceEligible':False,'status':'PASS' if before==after else 'FAIL',
        'checks':[{'query':q,'beforeSha256':a,'afterSha256':b,'status':'PASS' if a==b else 'FAIL'} for q,a,b in zip(queries,before,after)],
        'sourceCountsBefore':{name:int(count) for name,count in before_rows[1]},
        'sourceCountsAfter':{name:int(count) for name,count in after_rows[1]},
        'cacheInterpretation':'BE/container restarted; host OS caches are not cleared. This is persistence evidence, not a formal cold-cache benchmark.'}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if before!=after:raise ValueError('Data or features changed after restart')
    print('PASS: original tables, registry and both complete feature tables unchanged after owned container restart')


if __name__=='__main__':main()
