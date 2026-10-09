"""Apply a reversible owned FE allocator/CPU profile without widening budgets.

Only the fixed private override is written. The original diagnostic container
is restarted with its data volumes retained; neither SQL nor data is changed.
"""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import time

import configure_project_be_memory as memory
import configure_project_be_runtime as be_runtime
from validate_project_sources import WslDoris

CONTAINER = memory.CONTAINER
OVERRIDE = '/run/dsl-fe-runtime-profile'
ENTRYPOINT_MARKER = 'DSL_FE_BOUNDED_RUNTIME_PROFILE_V1'
PROFILE = 'bounded-v1'
DISABLED = 'disabled-v1'
MALLOC_ARENA_MAX = 4
ACTIVE_PROCESSOR_COUNT = 4
QUERY_MEMORY_BYTES = memory.QUERY_MEMORY_BYTES
CAPTURE_KEYS = {'profile', 'mallocArenaMax', 'activeProcessorCount',
                'heapInitialMiB', 'heapMaxMiB', 'feConfigurationSha256', 'entrypointSha256'}


def capture_fe_runtime(client):
    # Imported only when used, so offline tests never construct a real client.
    from project_fe_runtime import capture_fe_runtime as capture
    return capture(client)


def safe_error(error):
    if isinstance(error, ValueError):
        return str(error)
    if isinstance(error, RuntimeError) and re.fullmatch(
            r'Diagnostic command failed \(exit -?[0-9]+\)', str(error)):
        return str(error)
    return 'Diagnostic operation failed (type ' + type(error).__name__ + ')'


def parse_override(text):
    if text == 'ABSENT\n':
        return None
    if not text.startswith('PRESENT\n'):
        raise ValueError('Unrecognized FE runtime-profile backup response')
    value = text[len('PRESENT\n'):]
    if not re.fullmatch(r'(bounded-v1|disabled-v1)(?:\r?\n)?', value):
        raise ValueError('FE runtime profile must be one reviewed single line')
    return value


def override_archive(data):
    parse_override('PRESENT\n' + data.decode('ascii'))
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        member = tarfile.TarInfo(OVERRIDE.rsplit('/', 1)[1])
        member.size = len(data)
        member.mode = 0o600
        archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def validate_capture(value):
    if not isinstance(value, dict) or set(value) != CAPTURE_KEYS:
        raise ValueError('Unrecognized selected FE process specification')
    if value['profile'] not in (PROFILE, DISABLED):
        raise ValueError('Unknown selected FE process profile')
    for key in ('heapInitialMiB', 'heapMaxMiB'):
        if type(value[key]) is not int or value[key] != 768:
            raise ValueError('Expected the unchanged 768MiB FE initial and maximum heap')
    enabled = value['profile'] == PROFILE
    for key in ('mallocArenaMax', 'activeProcessorCount'):
        if enabled:
            if type(value[key]) is not int or value[key] != 4:
                raise ValueError('Selected FE process does not match the reviewed bounded profile')
        elif value[key] is not None:
            raise ValueError('Unreviewed FE allocator or CPU option before first application')
    for key in ('feConfigurationSha256', 'entrypointSha256'):
        if not isinstance(value[key], str) or not re.fullmatch(r'[0-9a-f]{64}', value[key]):
            raise ValueError('Missing selected FE configuration or entrypoint hash')
    return value


class Application(be_runtime.Application):
    def execute(self, command, data=None, timeout=90):
        try:
            return super().execute(command, data, timeout)
        except (subprocess.TimeoutExpired, OSError, UnicodeError) as error:
            raise RuntimeError('Diagnostic operation failed (type ' + type(error).__name__ + ')') from None

    def require_entrypoint(self):
        fingerprint = super().require_entrypoint()
        mounts = json.loads(self.run(['inspect', '-f', '{{json .Mounts}}', CONTAINER], timeout=20))
        tmpfs = json.loads(self.run(['inspect', '-f', '{{json .HostConfig.Tmpfs}}', CONTAINER], timeout=20)) or {}
        destinations = [m.get('Destination', '') for m in mounts if m.get('Destination') != memory.ENTRYPOINT] + list(tmpfs)
        if any(path and (OVERRIDE == path or OVERRIDE.startswith(path.rstrip('/') + '/')) for path in destinations):
            raise ValueError('FE runtime override must not be hidden by a mount or tmpfs')
        text = self.run(['exec', CONTAINER, 'cat', memory.ENTRYPOINT], timeout=20)
        if any(token not in text for token in (ENTRYPOINT_MARKER, OVERRIDE, PROFILE, DISABLED,
                                              'MALLOC_ARENA_MAX', 'JAVA_TOOL_OPTIONS')):
            raise ValueError('Mounted entrypoint lacks reviewed FE runtime-profile support')
        return fingerprint

    def read_override(self):
        response = self.run(['exec', CONTAINER, 'sh', '-c',
            'if test -L "$1"; then exit 45; elif test -e "$1"; then '
            'test -f "$1" || exit 46; printf "PRESENT\\n"; cat -- "$1"; '
            'else printf "ABSENT\\n"; fi', 'dsl-fe-runtime-read', OVERRIDE], timeout=20)
        return parse_override(response)

    def write_override_command(self, temporary):
        return ['exec', '-i', CONTAINER, 'sh', '-c',
            'test ! -L "$1" && { test ! -e "$1" || test -f "$1"; } && '
            'test ! -e "$2" && test ! -L "$2" && '
            'umask 077 && cat > "$2" && mv -- "$2" "$1"',
            'dsl-fe-runtime-write', OVERRIDE, temporary]

    def be_configuration(self):
        if self.runtime() != '60%' or self.selected_runtime() != be_runtime.RUNTIME_TARGET:
            raise ValueError('Expected the unchanged 60% BE budget and reviewed eight bounded settings')
        if be_runtime.Application.read_override(self) not in (be_runtime.PROFILE, be_runtime.PROFILE + '\n',
                                                              be_runtime.PROFILE + '\r\n'):
            raise ValueError('The BE bounded runtime-profile override must already be enabled')
        configuration = self.run(['exec', CONTAINER, 'cat', memory.CONF], timeout=20)
        be_runtime.configured_jemalloc(configuration, configuration)
        self.workload_scan_limit()
        return configuration

    def process(self):
        return validate_capture(capture_fe_runtime(self.client))

    def wait_profile_ready(self, expected, attempts, sleeper):
        deadline = time.monotonic() + 180
        for attempt in range(attempts):
            if time.monotonic() >= deadline:
                break
            try:
                if (self.runtime() == '60%' and self.selected_runtime() == be_runtime.RUNTIME_TARGET
                        and self.process() == expected and self.query('SELECT 1', timeout=10) == [('1',)]):
                    return
            except Exception:
                pass
            if attempt + 1 < attempts and time.monotonic() < deadline:
                sleeper(1)
        raise ValueError('Owned FE process/readiness did not match the expected profile')

    def verify_baseline(self, environment, entrypoint, be_configuration, process):
        self.ownership()
        if self.environment() != environment or self.require_entrypoint() != entrypoint:
            raise ValueError('Container budgets, heap or mounted entrypoint changed')
        if self.be_configuration() != be_configuration:
            raise ValueError('The frozen BE configuration changed during FE application')
        if self.process() != process:
            raise ValueError('Actual FE process specification or configuration changed')


def apply_configuration(client, folder, attempts=180, sleeper=time.sleep):
    folder = Path(folder).resolve()
    if not folder.is_dir() or any(folder.iterdir()):
        raise ValueError('Use a fresh empty report directory')
    app = Application(client)
    report = dict(purpose='OWNED_DIAGNOSTIC_FE_RUNTIME_PROFILE', officialAcceptanceEligible=False,
        overridePath=OVERRIDE, targetProfile=PROFILE, status='RUNNING', rollbackStatus='NOT_NEEDED',
        queryMaxExecutionMemoryBytes=QUERY_MEMORY_BYTES, queryTimeoutSeconds=10,
        mallocArenaMaxTarget=MALLOC_ARENA_MAX, activeProcessorCountTarget=ACTIVE_PROCESSOR_COUNT,
        startedAtUtc=datetime.now(timezone.utc).isoformat())
    mutated = False
    before = environment = entrypoint = before_be = before_process = rollback_bytes = rollback_tar = None
    pending = OVERRIDE + '.new-' + secrets.token_hex(8)
    try:
        app.ownership()
        report['containerId'] = app.container_id
        environment = app.environment()
        entrypoint = app.require_entrypoint()
        before_be = app.be_configuration()
        old_override = app.read_override()
        if old_override is not None and old_override.rstrip('\r\n') != DISABLED:
            raise ValueError('Expected an absent or disabled FE override before first application')
        before_process = app.process()
        if before_process['profile'] != DISABLED or before_process['entrypointSha256'] != entrypoint:
            raise ValueError('Expected the original disabled FE process and same mounted entrypoint')
        before = app.state()
        be_runtime.validate_source_state(before)
        rollback_bytes = (DISABLED + '\n').encode('ascii') if old_override is None else old_override.encode('ascii')
        rollback_tar = override_archive(rollback_bytes)
        (folder / 'override-before.txt').write_bytes(b'ABSENT\n' if old_override is None else old_override.encode('ascii'))
        (folder / 'override-rollback.txt').write_bytes(rollback_bytes)
        (folder / 'override-rollback.tar').write_bytes(rollback_tar)
        # BE is nonsecret configuration, stored for exact-byte recovery proof only.
        (folder / 'be-conf-before.txt').write_bytes(before_be.encode('utf-8'))
        report.update(environmentBefore=environment, entrypointSha256=entrypoint,
            processBefore=before_process, sourceStateBefore=before,
            beConfigurationBeforeSha256=memory.sha(before_be), overrideBefore='ABSENT' if old_override is None else old_override,
            rollbackFileState='EXPLICIT_DISABLED_RESTORES_PREVIOUS_EFFECTIVE_PROFILE' if old_override is None else 'ORIGINAL_BYTES',
            rollbackCommands=[client.prefix + ['cp', '-', CONTAINER + ':/run'], client.prefix + ['restart', CONTAINER]],
            rollbackStdinArtifact='override-rollback.tar',
            rollbackInstructions='Feed the fixed single-member tar as binary stdin, then restart only the same owned container. Data volumes are retained.')
        expected = dict(before_process, profile=PROFILE, mallocArenaMax=4, activeProcessorCount=4)
        app.verify_baseline(environment, entrypoint, before_be, before_process)
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        mutated = True
        app.run(app.write_override_command(pending), (PROFILE + '\n').encode('ascii'))
        if app.read_override() != PROFILE + '\n':
            raise ValueError('FE profile write did not match the requested bytes')
        app.restart()
        app.wait_profile_ready(expected, attempts, sleeper)
        app.verify_baseline(environment, entrypoint, before_be, expected)
        after = app.state()
        report['sourceStateAfter'] = after
        be_runtime.validate_source_state(after)
        if after != before:
            raise ValueError('Source counts, dates, semantic views or formal registry changed')
        report.update(status='PASS', processAfter=app.process(),
            beConfigurationAfterSha256=memory.sha(app.be_configuration()), sourceStateUnchanged=True,
            containerAndHeapBudgetsUnchanged=True, beConfigurationUnchanged=True)
    except Exception as error:
        report.update(status='FAIL', fatalError=safe_error(error), errorType=type(error).__name__)
        if mutated:
            errors = []
            try:
                app.ownership()
                app.run(['cp', '-', CONTAINER + ':/run'], rollback_tar)
            except Exception as rollback_error:
                errors.append(safe_error(rollback_error))
            try:
                app.restart()
                app.wait_profile_ready(before_process, attempts, sleeper)
                if app.read_override() != rollback_bytes.decode('ascii'):
                    raise ValueError('Rollback did not restore the exact override bytes')
                app.verify_baseline(environment, entrypoint, before_be, before_process)
                restored = app.state()
                be_runtime.validate_source_state(restored)
                if restored != before:
                    raise ValueError('Rollback did not restore the frozen source state')
                report.update(processRollback=app.process(), sourceStateRollback=restored,
                    beConfigurationRollbackSha256=memory.sha(app.be_configuration()))
            except Exception as rollback_error:
                errors.append(safe_error(rollback_error))
            report.update(rollbackStatus='FAILED' if errors else 'DONE', rollbackErrors=errors)
    finally:
        report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', '--output-dir', dest='report_dir', type=Path, required=True)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        parser.error('--apply is required for the private override and retained-data restart')
    folder = args.report_dir.resolve()
    if folder.exists():
        raise ValueError('Use a fresh report directory')
    folder.mkdir(parents=True)
    try:
        client = WslDoris(args.distribution, CONTAINER)
    except Exception as error:
        report = dict(status='FAIL', fatalError=safe_error(error), errorType=type(error).__name__,
                      rollbackStatus='NOT_NEEDED', officialAcceptanceEligible=False)
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return 1
    report = apply_configuration(client, folder)
    print(json.dumps({key: report[key] for key in ('status', 'rollbackStatus', 'queryMaxExecutionMemoryBytes')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
