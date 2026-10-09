"""Offline FE runtime ownership, exact-byte, process and rollback tests."""
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import configure_project_be_memory as memory
import configure_project_be_runtime as be_runtime
import configure_project_fe_runtime as runtime
from test_project_be_runtime import FakeContainer as BeContainer


class FakeContainer(BeContainer):
    def __init__(self, original=None, **kwargs):
        super().__init__(original=be_runtime.PROFILE + '\n', **kwargs)
        self.fe_override = original
        self.active = dict(be_runtime.RUNTIME_TARGET)
        self.conf_before = self.conf_after
        self.fe_enabled = original is not None and original.rstrip('\r\n') == runtime.PROFILE

    def capture(self, client):
        if self.stopped:
            raise RuntimeError('Private credential must not be emitted')
        profile_enabled = self.fe_override is not None and self.fe_override.rstrip('\r\n') == runtime.PROFILE
        if profile_enabled != self.fe_enabled:
            raise ValueError('FE private profile and running process options differ')
        value = dict(profile=runtime.PROFILE if self.fe_enabled else runtime.DISABLED,
            mallocArenaMax=4 if self.fe_enabled else None,
            activeProcessorCount=4 if self.fe_enabled else None,
            heapInitialMiB=768, heapMaxMiB=768,
            feConfigurationSha256='f' * 64,
            entrypointSha256=memory.sha(self.entrypoint()))
        if self.failure == 'process-heap':
            value['heapMaxMiB'] = 1024
        if self.failure == 'process-unknown':
            value['unreviewed'] = 'private credential'
        if self.failure == 'process-cpu' and self.restart_count == 1:
            value['activeProcessorCount'] = 8
        if self.failure == 'fe-configuration' and self.restart_count == 1:
            value['feConfigurationSha256'] = 'e' * 64
        return value

    def entrypoint(self):
        text = '\n'.join([memory.ENTRYPOINT_MARKER, memory.OVERRIDE, 'BE_CONFIG_EXTRA',
            be_runtime.ENTRYPOINT_MARKER, be_runtime.OVERRIDE, be_runtime.PROFILE,
            be_runtime.DISABLED, 'JEMALLOC_CONF', runtime.ENTRYPOINT_MARKER, runtime.OVERRIDE,
            'MALLOC_ARENA_MAX', 'JAVA_TOOL_OPTIONS'])
        if self.failure == 'fe-entrypoint':
            text = text.replace(runtime.ENTRYPOINT_MARKER, 'UNREVIEWED')
        if self.failure == 'entrypoint-change' and self.restart_count == 1:
            text += '\nchanged'
        return text

    def run(self, command, input=None, **kwargs):
        args = command[1:] if command[0] == 'docker' else []
        if args and args[0] == 'cp':
            self.commands.append((command, input, kwargs))
            if self.failure == 'rollback-fail':
                return SimpleNamespace(returncode=7, stdout=b'', stderr=b'private credential')
            if args[1:] != ['-', runtime.CONTAINER + ':/run'] or not isinstance(input, bytes):
                raise AssertionError('Rollback must use binary stdin and fixed owned target')
            with tarfile.open(fileobj=io.BytesIO(input), mode='r') as archive:
                members = archive.getmembers()
                if (len(members) != 1 or members[0].name != 'dsl-fe-runtime-profile'
                        or not members[0].isreg() or members[0].mode != 0o600):
                    raise AssertionError('Unexpected FE rollback archive')
                self.fe_override = archive.extractfile(members[0]).read().decode('ascii')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        if 'dsl-fe-runtime-read' in args:
            self.commands.append((command, input, kwargs))
            if self.failure in ('fe-symlink', 'fe-directory'):
                return SimpleNamespace(returncode=45, stdout=b'', stderr=b'private credential')
            value = self.fe_override
            if self.failure == 'fe-bad-readback' and value == runtime.PROFILE + '\n':
                value = runtime.DISABLED + '\n'
            result = 'ABSENT\n' if value is None else 'PRESENT\n' + value
            return SimpleNamespace(returncode=0, stdout=result.encode('ascii'), stderr=b'')
        if 'dsl-fe-runtime-write' in args:
            self.commands.append((command, input, kwargs))
            if self.failure == 'write':
                return SimpleNamespace(returncode=3, stdout=b'', stderr=b'private credential')
            if not isinstance(input, bytes):
                raise AssertionError('FE writes require binary stdin')
            self.fe_override = input.decode('ascii')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        if 'cat' in args and memory.ENTRYPOINT in args:
            self.commands.append((command, input, kwargs))
            return SimpleNamespace(returncode=0, stdout=self.entrypoint().encode('ascii'), stderr=b'')
        if args and args[0] == 'inspect' and '.Mounts' in args[2] and self.failure == 'fe-mount':
            self.commands.append((command, input, kwargs))
            result = [dict(Type='bind', Destination=memory.ENTRYPOINT, RW=False),
                      dict(Type='bind', Destination=runtime.OVERRIDE, RW=True)]
            return SimpleNamespace(returncode=0, stdout=json.dumps(result).encode(), stderr=b'')
        if args and args[0] == 'inspect' and '.HostConfig.Tmpfs' in args[2] and self.failure == 'fe-tmpfs':
            self.commands.append((command, input, kwargs))
            return SimpleNamespace(returncode=0, stdout=json.dumps({runtime.OVERRIDE: ''}).encode(), stderr=b'')
        if 'cat' in args and memory.CONF in args and self.failure == 'be-configuration' and self.restart_count == 1:
            self.commands.append((command, input, kwargs))
            return SimpleNamespace(returncode=0, stdout=(self.conf_before + '\n# changed\n').encode(), stderr=b'')
        result = super().run(command, input=input, **kwargs)
        if args and args[0] == 'restart':
            self.fe_enabled = self.fe_override is not None and self.fe_override.rstrip('\r\n') == runtime.PROFILE
            if self.failure == 'budget-change':
                self.cpus = 8000000000 if self.restart_count == 1 else 4000000000
        return result


class FeRuntimeSafetyTest(unittest.TestCase):
    def apply(self, container):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        with patch.object(memory.subprocess, 'run', side_effect=container.run), \
                patch.object(runtime, 'capture_fe_runtime', side_effect=container.capture):
            report = runtime.apply_configuration(container, folder, attempts=1, sleeper=lambda _: None)
        self.assertEqual(json.loads((folder / 'result.json').read_text(encoding='utf-8'))['status'], report['status'])
        return report, folder

    def test_success_retains_container_query_heap_be_and_source_budgets(self):
        container = FakeContainer()
        report, folder = self.apply(container)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['processAfter']['mallocArenaMax'], 4)
        self.assertEqual(report['processAfter']['activeProcessorCount'], 4)
        self.assertEqual(report['processAfter']['heapMaxMiB'], 768)
        self.assertEqual(report['queryMaxExecutionMemoryBytes'], 2147483648)
        self.assertEqual(report['queryTimeoutSeconds'], 10)
        self.assertEqual(report['environmentBefore']['containerMemoryBytes'], 5368709120)
        self.assertEqual(report['beConfigurationBeforeSha256'], report['beConfigurationAfterSha256'])
        self.assertEqual(report['sourceStateBefore'], report['sourceStateAfter'])
        self.assertFalse(report['officialAcceptanceEligible'])
        self.assertEqual(container.restart_count, 1)
        self.assertEqual(container.fe_override, 'bounded-v1\n')
        self.assertEqual((folder / 'override-before.txt').read_bytes(), b'ABSENT\n')
        self.assertEqual([value for command, value, _ in container.commands if 'dsl-fe-runtime-write' in command], [b'bounded-v1\n'])

    def test_unowned_resource_heap_mount_link_and_source_rejections_precede_mutation(self):
        failures = ['owner', 'entrypoint-rw', 'tmpfs', 'fe-mount', 'fe-tmpfs', 'fe-entrypoint',
                    'fe-symlink', 'fe-directory', 'counts', 'dates', 'registered',
                    'missing-runtime', 'duplicate-runtime', 'workload-scan', 'process-heap', 'process-unknown']
        containers = [FakeContainer(failure=failure) for failure in failures]
        containers += [FakeContainer(memory_bytes=10737418240, fe='2048m'),
                       FakeContainer(cpus=8000000000), FakeContainer(fe='1024m'), FakeContainer(be='256m')]
        for container in containers:
            with self.subTest(failure=container.failure, memory=container.memory, fe=container.fe):
                report, _ = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(report['rollbackStatus'], 'NOT_NEEDED')
                self.assertEqual(container.restart_count, 0)
                self.assertFalse(any('dsl-fe-runtime-write' in command for command, _, _ in container.commands))
                self.assertNotIn('private credential', json.dumps(report))

    def test_already_enabled_or_unknown_override_is_not_reapplied(self):
        for value in ['bounded-v1\n', 'unreviewed\n', 'disabled-v1\nATTACK\n']:
            with self.subTest(value=value):
                container = FakeContainer(original=value)
                report, _ = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(container.restart_count, 0)

    def test_be_bounded_profile_and_budget_are_required(self):
        for kind in ['share', 'override', 'knob']:
            with self.subTest(kind=kind):
                container = FakeContainer()
                if kind == 'share':
                    container.share = '40%'
                elif kind == 'override':
                    container.override = 'disabled-v1\n'
                else:
                    container.active['pipeline_executor_size'] = '32'
                report, _ = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(container.restart_count, 0)

    def test_existing_disabled_crlf_bytes_are_preserved_in_backup_and_rollback(self):
        for original in ['disabled-v1', 'disabled-v1\n', 'disabled-v1\r\n']:
            with self.subTest(original=repr(original)):
                container = FakeContainer(original=original, failure='data-change')
                report, folder = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(report['rollbackStatus'], 'DONE')
                self.assertEqual(container.fe_override, original)
                self.assertEqual((folder / 'override-before.txt').read_bytes(), original.encode('ascii'))
                self.assertEqual((folder / 'override-rollback.txt').read_bytes(), original.encode('ascii'))
                self.assertEqual(report['rollbackFileState'], 'ORIGINAL_BYTES')

    def test_failed_runtime_readiness_or_source_identity_is_rolled_back(self):
        for failure in ['readiness', 'process-cpu', 'fe-configuration', 'be-configuration',
                        'entrypoint-change', 'budget-change', 'views', 'data-change', 'stopped']:
            with self.subTest(failure=failure):
                container = FakeContainer(failure=failure)
                report, _ = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(report['rollbackStatus'], 'DONE')
                self.assertEqual(container.restart_count, 2)
                self.assertEqual(container.fe_override, 'disabled-v1\n')
                self.assertEqual(report['processRollback'], report['processBefore'])

    def test_write_and_readback_failures_restore_without_echoing_stderr(self):
        for failure in ['write', 'fe-bad-readback']:
            with self.subTest(failure=failure):
                container = FakeContainer(failure=failure)
                report, _ = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(report['rollbackStatus'], 'DONE')
                self.assertEqual(container.restart_count, 1)
                self.assertNotIn('private credential', json.dumps(report))

    def test_identity_change_prevents_rollback_writes_and_restarts(self):
        container = FakeContainer(failure='identity')
        report, _ = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'FAILED')
        self.assertEqual(container.restart_count, 1)
        self.assertFalse(any(command[:2] == ['docker', 'cp'] for command, _, _ in container.commands))

    def test_failed_recovery_preserves_failure_and_does_not_claim_pass(self):
        container = FakeContainer(failure='rollback-fail')
        report, _ = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'FAILED')
        self.assertTrue(report['rollbackErrors'])
        self.assertNotIn('private credential', json.dumps(report))

    def test_fixed_regular_tar_member_mode_and_exact_payload(self):
        payload = b'disabled-v1\r\n'
        with tarfile.open(fileobj=io.BytesIO(runtime.override_archive(payload)), mode='r') as archive:
            self.assertEqual(archive.getnames(), ['dsl-fe-runtime-profile'])
            member = archive.getmembers()[0]
            self.assertTrue(member.isreg())
            self.assertEqual(member.mode, 0o600)
            self.assertEqual(archive.extractfile(member).read(), payload)
        for payload in [b'disabled-v1\nATTACK\n', b'../../other', b'bounded-v2\n']:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                runtime.override_archive(payload)

    def test_override_parser_accepts_only_one_exact_reviewed_line(self):
        self.assertIsNone(runtime.parse_override('ABSENT\n'))
        self.assertEqual(runtime.parse_override('PRESENT\nbounded-v1\r\n'), 'bounded-v1\r\n')
        for value in ['ABSENT\nbounded-v1', 'PRESENT\n', 'PRESENT\n bounded-v1\n', 'PRESENT\ndisabled-v1\n\n']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.parse_override(value)

    def test_process_capture_contract_rejects_unknown_fields_types_heaps_and_hashes(self):
        before = FakeContainer().capture(None)
        self.assertEqual(runtime.validate_capture(before), before)
        changes = [('heapInitialMiB', True), ('heapMaxMiB', 1024), ('activeProcessorCount', 4),
                   ('feConfigurationSha256', 'bad'), ('entrypointSha256', None), ('profile', 'unknown')]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(ValueError):
                runtime.validate_capture(dict(before, **{key: value}))

    def test_timeout_or_unexpected_command_error_cannot_echo_args(self):
        for error in [subprocess.TimeoutExpired(['private credential'], 1), OSError('private credential')]:
            with self.subTest(error=type(error).__name__), patch.object(memory.subprocess, 'run', side_effect=error):
                app = runtime.Application(FakeContainer())
                with self.assertRaises(RuntimeError) as raised:
                    app.execute(['command'])
                self.assertNotIn('private credential', str(raised.exception))

    def test_explicit_apply_is_required_before_client_or_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'fresh'
            with patch('sys.argv', ['runner', '--report-dir', str(folder)]), patch.object(runtime, 'WslDoris') as client:
                with self.assertRaises(SystemExit) as raised:
                    runtime.main()
                self.assertEqual(raised.exception.code, 2)
                client.assert_not_called()
                self.assertFalse(folder.exists())

    def test_existing_artifact_directory_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            evidence = folder / 'result.json'
            evidence.write_text('immutable evidence', encoding='utf-8')
            with patch('sys.argv', ['runner', '--report-dir', directory, '--apply']), patch.object(runtime, 'WslDoris') as client:
                with self.assertRaisesRegex(ValueError, 'fresh report'):
                    runtime.main()
                client.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'fresh empty'):
                runtime.apply_configuration(FakeContainer(), folder)
            self.assertEqual(evidence.read_text(encoding='utf-8'), 'immutable evidence')

    def test_entrypoint_and_application_share_reviewed_fe_contract(self):
        text = (Path(__file__).resolve().parent / 'wsl-doris-entrypoint.sh').read_text(encoding='utf-8')
        for token in [runtime.ENTRYPOINT_MARKER, runtime.OVERRIDE, runtime.PROFILE, runtime.DISABLED,
                      'MALLOC_ARENA_MAX=4', 'JAVA_TOOL_OPTIONS', '-XX:ActiveProcessorCount=4',
                      '[ ! -L /run/dsl-fe-runtime-profile ]', 'Invalid project FE runtime profile']:
            self.assertIn(token, text)


if __name__ == '__main__':
    unittest.main()
