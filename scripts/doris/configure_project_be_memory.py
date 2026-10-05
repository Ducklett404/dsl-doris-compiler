"""Adjust only the owned 10GiB diagnostic container's BE share; retain the 2GiB query policy."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from validate_project_sources import WslDoris

CONF = '/opt/apache-doris/be/conf/be.conf'
TEMPLATE = CONF+'.orig'
BACKUP = TEMPLATE+'.before-project-matrix-20261005'


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9'); args = parser.parse_args()
    folder = args.output_dir.resolve()
    if folder.exists(): raise ValueError('Use a fresh output directory')
    folder.mkdir(parents=True); client = WslDoris(args.distribution, 'dsl-doris-official')
    report = dict(purpose='OWNED_DIAGNOSTIC_BE_MEMORY_CONFIGURATION', officialAcceptanceEligible=False,
                  queryMaxExecutionMemoryBytes=2147483648, configurationTemplatePath=TEMPLATE, backupPath=BACKUP)
    def run(command, text=None):
        completed = subprocess.run(client.prefix+command, input=text, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=90)
        if completed.returncode: raise RuntimeError(completed.stderr[:400])
        return completed.stdout
    def state():
        return [sorted(client.query("SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info")),
                client.query('SELECT * FROM newzl.data_snapshot_registry')]
    def runtime():
        rows = json.loads(run(['exec','dsl-doris-official','curl','-fsS','--max-time','10','http://127.0.0.1:8040/api/show_config']))
        return next(row[2] for row in rows if row[0] == 'mem_limit')
    try:
        container_bytes = int(run(['inspect','-f','{{.HostConfig.Memory}}','dsl-doris-official']).strip())
        if container_bytes != 10737418240: raise ValueError('Expected the existing owned 10GiB container')
        environments = json.loads(run(['inspect','-f','{{json .Config.Env}}','dsl-doris-official']))
        if any('mem_limit' in e for e in environments if e.startswith('BE_CONFIG_EXTRA=')):
            raise ValueError('Environment would override the persisted BE setting')
        fe = run(['exec','dsl-doris-official','cat','/opt/apache-doris/fe/conf/fe.conf'])
        if re.findall(r'-Xmx(\d+)m',fe) != ['2048']: raise ValueError('Expected the existing 2GiB FE heap')
        # The CI image re-renders be.conf from be.conf.orig on every restart.
        original = run(['exec','dsl-doris-official','cat',TEMPLATE])
        changed, matches = re.subn(r'(?m)^mem_limit[ \t]*=[ \t]*40%[ \t]*$', 'mem_limit = 60%', original)
        if matches != 1 or runtime() != '40%': raise ValueError('Expected one active 40% BE memory setting')
        (folder/'be-conf-before.txt').write_text(original,encoding='utf-8')
        before = state()
        if before[1] or sum(int(count) for _,count in before[0]) != 19826855: raise ValueError('Unexpected official diagnostic source')
        run(['exec','dsl-doris-official','sh','-c',f'test ! -e {BACKUP} && cp -- {TEMPLATE} {BACKUP}'])
        run(['exec','-i','dsl-doris-official','sh','-c',f'cat > {TEMPLATE}.project-matrix-new && mv -- {TEMPLATE}.project-matrix-new {TEMPLATE}'], changed)
        persisted = run(['exec','dsl-doris-official','cat',TEMPLATE])
        if persisted != changed: raise ValueError('BE configuration write did not match')
        (folder/'be-conf-after.txt').write_text(persisted,encoding='utf-8')
        report.update(containerMemoryBytes=container_bytes, feHeapBytes=2147483648,
            before='40%', after='60%', beforeBeBytes=4294967296, afterBeBytes=6442450944,
            configBeforeSha256=hashlib.sha256(original.encode()).hexdigest(), configAfterSha256=hashlib.sha256(changed.encode()).hexdigest())
        run(['restart','dsl-doris-official'])
        deadline = time.monotonic()+180; last_error=''
        while time.monotonic() < deadline:
            try:
                if runtime() == '60%' and state() == before: break
            except Exception as error: last_error=str(error)
            time.sleep(1)
        else: raise RuntimeError('BE/source readiness failed: '+last_error[:300])
        report.update(runtimeBeShare=runtime(), sourceStateUnchanged=state()==before,
            rollbackCommands=[client.prefix+['exec','dsl-doris-official','cp','--',BACKUP,TEMPLATE], client.prefix+['restart','dsl-doris-official']], status='PASS')
    except Exception as error: report.update(status='FAIL',fatalError=str(error)); raise
    finally:
        (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','before','after','containerMemoryBytes','queryMaxExecutionMemoryBytes']}))


if __name__ == '__main__': main()
