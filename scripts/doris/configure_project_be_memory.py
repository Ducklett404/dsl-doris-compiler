"""Reversibly change only the owned diagnostic BE share; retain query/container budgets."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import time
from validate_project_sources import WslDoris

CONTAINER = 'dsl-doris-official'
PURPOSE = 'official-data-diagnostic'
CONF = '/opt/apache-doris/be/conf/be.conf'
FE_CONF = '/opt/apache-doris/fe/conf/fe.conf'
ENTRYPOINT = '/run/dsl-entrypoint.sh'
OVERRIDE = '/run/dsl-be-memory-percent'
ENTRYPOINT_MARKER = 'DSL_BE_MEMORY_PERCENT_OVERRIDE_V1'
SUPPORTED = {5368709120: 768, 10737418240: 2048}
QUERY_MEMORY_BYTES = 2147483648


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def parse_override(text):
    if text == 'ABSENT\n':
        return None
    if not text.startswith('PRESENT\n'):
        raise ValueError('Unrecognized BE override backup response')
    value = text[len('PRESENT\n'):]
    if not re.fullmatch(r'(40|60)(?:\r?\n)?', value):
        raise ValueError('BE override must be one line containing 40 or 60')
    return value


def override_archive(data):
    """One fixed regular file, streamed to WSL Docker without a host path."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        member = tarfile.TarInfo(OVERRIDE.rsplit('/', 1)[1])
        member.size = len(data)
        member.mode = 0o600
        archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


class Application:
    def __init__(self, client):
        self.client = client
        self.container_id = None

    def execute(self, command, data=None, timeout=90):
        # Binary stdin preserves LF on Windows. Never capture the full env.
        result = subprocess.run(command, input=data, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError('Diagnostic command failed (exit ' + str(result.returncode) + ')')
        return result.stdout.decode('utf-8', errors='strict')

    def run(self, command, data=None, timeout=90):
        return self.execute(self.client.prefix + command, data, timeout)

    def query(self, sql, timeout=30):
        output = self.execute(self.client.command, (sql.rstrip(';\n') + ';\n').encode('utf-8'), timeout)
        return [tuple(line.split('\t')) for line in output.splitlines() if line]

    def ownership(self):
        fields = self.run(['inspect', '-f', '{{.Id}} {{index .Config.Labels "com.acme.dorisdsl.purpose"}}', CONTAINER], timeout=20).split()
        if len(fields) != 2 or not re.fullmatch(r'[0-9a-f]{64}', fields[0]) or fields[1] != PURPOSE:
            raise ValueError('Refusing container without dedicated diagnostic ownership')
        if self.container_id is not None and fields[0] != self.container_id:
            raise ValueError('Diagnostic container identity changed')
        self.container_id = fields[0]

    def environment(self):
        limits = self.run(['inspect', '-f', '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}', CONTAINER], timeout=20).split()
        if len(limits) != 2:
            raise ValueError('Unrecognized diagnostic container resource limits')
        memory, cpus = map(int, limits)
        heaps = self.run(['inspect', '-f', '{{range .Config.Env}}{{if or '
            '(eq (index (split . "=") 0) "FE_HEAP") (eq (index (split . "=") 0) "BE_HEAP")}}'
            '{{println .}}{{end}}{{end}}', CONTAINER], timeout=20).splitlines()
        selected = {}
        for line in heaps:
            if not line.strip():
                continue
            key, separator, value = line.partition('=')
            if not separator or key not in ('FE_HEAP', 'BE_HEAP') or key in selected or not re.fullmatch(r'[0-9]+m', value):
                raise ValueError('Unrecognized diagnostic heap configuration')
            selected[key] = value
        active_fe = self.run(['exec', CONTAINER, 'sed', '-n',
            r's/.*-Xmx\([0-9][0-9]*\)m.*/\1/p', FE_CONF], timeout=20).splitlines()
        if memory not in SUPPORTED or selected.get('FE_HEAP') != str(SUPPORTED[memory]) + 'm' or active_fe != [str(SUPPORTED[memory])]:
            raise ValueError('Expected owned 5GiB/FE768m or 10GiB/FE2048m diagnostic container')
        if memory == 5368709120 and selected.get('BE_HEAP') != '128m':
            raise ValueError('Expected the existing 128m BE JNI heap')
        return dict(containerMemoryBytes=memory, containerNanoCpus=cpus, feHeap=selected['FE_HEAP'],
                    beHeap=selected.get('BE_HEAP'), activeFeHeapMiB=int(active_fe[0]))

    def require_entrypoint(self):
        mounts = json.loads(self.run(['inspect', '-f', '{{json .Mounts}}', CONTAINER], timeout=20))
        mounted = [m for m in mounts if m.get('Destination') == ENTRYPOINT]
        if len(mounted) != 1 or mounted[0].get('Type') != 'bind' or mounted[0].get('RW') is not False:
            raise ValueError('Expected the read-only diagnostic entrypoint bind mount')
        tmpfs = json.loads(self.run(['inspect', '-f', '{{json .HostConfig.Tmpfs}}', CONTAINER], timeout=20)) or {}
        destinations = [m.get('Destination', '') for m in mounts if m.get('Destination') != ENTRYPOINT] + list(tmpfs)
        if any(path and (OVERRIDE == path or OVERRIDE.startswith(path.rstrip('/') + '/')) for path in destinations):
            raise ValueError('BE override must remain in the persistent container filesystem, not a mounted run path')
        text = self.run(['exec', CONTAINER, 'cat', ENTRYPOINT], timeout=20)
        if any(marker not in text for marker in (ENTRYPOINT_MARKER, OVERRIDE, 'BE_CONFIG_EXTRA')):
            raise ValueError('Mounted diagnostic entrypoint lacks reviewed BE override support')
        return sha(text)

    def runtime(self, timeout=20):
        rows = json.loads(self.run(['exec', CONTAINER, 'curl', '-fsS', '--max-time', '10',
                                  f'http://127.0.0.1:{self.client.be_http_port}/api/show_config'], timeout=timeout))
        shares = [row[2] for row in rows if row[0] == 'mem_limit']
        if len(shares) != 1 or shares[0] not in ('40%', '60%'):
            raise ValueError('Unrecognized active BE memory share')
        return shares[0]

    def state(self):
        queries = dict(
            tableCounts="SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info",
            dateBounds="SELECT 'basic',MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'extension',MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_ext",
            viewDefinitions="SELECT TABLE_NAME,SHA2(VIEW_DEFINITION,256) FROM information_schema.views WHERE TABLE_SCHEMA='newzl' AND TABLE_NAME IN ('v_hsj_stock_hq_basic','v_hsj_stock_hq_ext') ORDER BY TABLE_NAME",
            formalRegistry='SELECT * FROM newzl.data_snapshot_registry')
        return {key: sorted(self.query(sql)) for key, sql in queries.items()}

    def read_override(self):
        response = self.run(['exec', CONTAINER, 'sh', '-c',
            'if test -L "$1"; then exit 45; elif test -e "$1"; then '
            'test -f "$1" || exit 46; printf "PRESENT\\n"; cat -- "$1"; '
            'else printf "ABSENT\\n"; fi', 'dsl-be-memory-read', OVERRIDE], timeout=20)
        return parse_override(response)

    def write_override_command(self, temporary):
        return ['exec', '-i', CONTAINER, 'sh', '-c',
            'test ! -L "$1" && test ! -e "$2" && test ! -L "$2" && '
            'umask 077 && cat > "$2" && mv -- "$2" "$1"', 'dsl-be-memory-write', OVERRIDE, temporary]

    def restart(self):
        self.ownership()
        self.run(['restart', CONTAINER])

    def wait_ready(self, share, attempts, sleeper):
        deadline = time.monotonic() + 180
        for attempt in range(attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                if self.runtime(min(20, remaining)) == share:
                    remaining = deadline - time.monotonic()
                    if remaining > 0 and self.query('SELECT 1', min(10, remaining)) == [('1',)]:
                        return
            except Exception:
                pass
            if attempt + 1 < attempts and time.monotonic() < deadline:
                sleeper(1)
        raise RuntimeError('Diagnostic BE/source readiness failed for ' + share)


def validate_source_state(state):
    if state['formalRegistry']:
        raise ValueError('Expected an empty formal snapshot registry')
    if len(state['tableCounts']) != 3 or {row[0] for row in state['tableCounts']} != {'basic', 'ext', 'code'} or sum(int(row[1]) for row in state['tableCounts']) != 19826855:
        raise ValueError('Unexpected official diagnostic source counts')
    if len(state['dateBounds']) != 2 or {row[0] for row in state['dateBounds']} != {'basic', 'extension'}:
        raise ValueError('Incomplete source date bounds')
    if len(state['viewDefinitions']) != 2 or {row[0] for row in state['viewDefinitions']} != {'v_hsj_stock_hq_basic', 'v_hsj_stock_hq_ext'} or any(not re.fullmatch(r'[0-9a-fA-F]{64}', row[1]) for row in state['viewDefinitions']):
        raise ValueError('Expected both semantic view definition hashes')


def apply_configuration(client, folder, attempts=180, sleeper=time.sleep):
    folder = Path(folder).resolve()
    app = Application(client)
    report = dict(purpose='OWNED_DIAGNOSTIC_BE_MEMORY_CONFIGURATION', officialAcceptanceEligible=False,
        queryMaxExecutionMemoryBytes=QUERY_MEMORY_BYTES, queryTimeoutSeconds=10,
        overridePath=OVERRIDE, configurationPath=CONF, status='RUNNING', rollbackStatus='NOT_NEEDED',
        startedAtUtc=datetime.now(timezone.utc).isoformat())
    mutation_started = False
    before = environment = old_override = None
    token = secrets.token_hex(8)
    backup = OVERRIDE + '.rollback-' + token
    pending = OVERRIDE + '.new-' + token
    rollback_file = folder / 'override-rollback.txt'
    try:
        app.ownership()
        report['containerId'] = app.container_id
        environment = app.environment()
        report['environmentBefore'] = environment
        report['entrypointSha256'] = app.require_entrypoint()
        if app.runtime() != '40%':
            raise ValueError('Expected the current active 40% BE share')
        old_override = app.read_override()
        if old_override is not None and old_override.rstrip('\r\n') != '40':
            raise ValueError('Existing override conflicts with the active 40% BE share')
        active = app.run(['exec', CONTAINER, 'cat', CONF], timeout=20)
        (folder / 'be-conf-before.txt').write_bytes(active.encode('utf-8'))
        (folder / 'override-before.txt').write_bytes(b'ABSENT\n' if old_override is None else old_override.encode('utf-8'))
        # The new entrypoint defaults to 60; ABSENT rollback must explicitly
        # restore the old effective 40%, rather than remove the override.
        rollback_file.write_bytes(b'40\n' if old_override is None else old_override.encode('utf-8'))
        rollback_tar = override_archive(rollback_file.read_bytes())
        (folder / 'override-rollback.tar').write_bytes(rollback_tar)
        report.update(overrideBefore='ABSENT' if old_override is None else old_override,
            rollbackFileState='EXPLICIT_40_RESTORES_PREVIOUS_EFFECTIVE_SHARE' if old_override is None else 'ORIGINAL_BYTES',
            activeConfigurationBeforeSha256=sha(active), before='40%', after='60%',
            beforeBeBytes=environment['containerMemoryBytes'] * 40 // 100,
            afterBeBytes=environment['containerMemoryBytes'] * 60 // 100)
        before = app.state()
        validate_source_state(before)
        report['sourceStateBefore'] = before
        app.ownership()
        if old_override is not None:
            app.run(['exec', CONTAINER, 'sh', '-c', 'test ! -L "$1" && test ! -e "$2" && '
                'test ! -L "$2" && cp -- "$1" "$2"', 'dsl-be-memory-backup', OVERRIDE, backup])
            report['containerOverrideBackupPath'] = backup
        restore_command = ['cp', '-', CONTAINER + ':/run']
        report['rollbackCommands'] = [client.prefix + restore_command, client.prefix + ['restart', CONTAINER]]
        report['rollbackStdinArtifact'] = 'override-rollback.tar'
        report['rollbackInstructions'] = 'Feed the recorded tar artifact as binary stdin to the first rollback command; then run the second command. The archive contains only dsl-be-memory-percent.'
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        mutation_started = True
        app.run(app.write_override_command(pending), b'60\n')
        if app.read_override() != '60\n':
            raise ValueError('BE override write did not match the requested value')
        app.restart()
        app.wait_ready('60%', attempts, sleeper)
        app.ownership()
        after = app.state()
        report['sourceStateAfter'] = after
        if after != before:
            raise ValueError('Source counts, date bounds, semantic views or formal registry changed')
        if app.environment() != environment or app.require_entrypoint() != report['entrypointSha256']:
            raise ValueError('Container budgets, heaps or mounted entrypoint changed')
        active_after = app.run(['exec', CONTAINER, 'cat', CONF], timeout=20)
        (folder / 'be-conf-after.txt').write_bytes(active_after.encode('utf-8'))
        report.update(status='PASS', runtimeBeShare=app.runtime(), sourceStateUnchanged=True,
                      containerAndHeapBudgetsUnchanged=True, activeConfigurationAfterSha256=sha(active_after))
    except Exception as error:
        report.update(status='FAIL', fatalError=str(error))
        if mutation_started:
            rollback_errors = []
            try:
                app.ownership()
                # docker cp also works when failed startup has stopped the
                # container. /run mounts and symlinks were rejected pre-write.
                app.run(['cp', '-', CONTAINER + ':/run'], rollback_tar)
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
            try:
                app.restart()
                app.wait_ready('40%', attempts, sleeper)
                app.ownership()
                if app.state() != before or app.environment() != environment:
                    raise ValueError('Rollback did not restore original source state and budgets')
                report['rollbackRuntimeBeShare'] = app.runtime()
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
            report.update(rollbackStatus='FAILED' if rollback_errors else 'DONE', rollbackErrors=rollback_errors)
    finally:
        report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    args = parser.parse_args()
    folder = args.output_dir.resolve()
    if folder.exists():
        raise ValueError('Use a fresh output directory')
    folder.mkdir(parents=True)
    try:
        client = WslDoris(args.distribution, CONTAINER)
    except Exception as error:
        report = dict(status='FAIL', fatalError=str(error), rollbackStatus='NOT_NEEDED', officialAcceptanceEligible=False)
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return 1
    report = apply_configuration(client, folder)
    print(json.dumps({key: report[key] for key in ('status', 'rollbackStatus', 'queryMaxExecutionMemoryBytes')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
