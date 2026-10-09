"""Offline BE override safety tests; no real Docker or SQL execution."""
import json
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tarfile
import unittest
from unittest.mock import patch

import configure_project_be_memory as memory


class FakeContainer:
    def __init__(self, original=None, memory_bytes=5368709120, fe='768m', failure=None):
        self.prefix = ['docker']
        self.command = ['mysql']
        self.be_http_port = 8040
        self.override = original
        self.share = '40%'
        self.memory = memory_bytes
        self.fe = fe
        self.heap_lines = f'FE_HEAP={self.fe}\nBE_HEAP=128m\n\n'
        self.failure = failure
        self.commands = []
        self.restart_count = 0
        self.backup = None
        self.stopped = False

    def query(self, sql):
        if sql == 'SELECT 1':
            return [('1',)]
        if 'COUNT(*)' in sql:
            return [('basic', '10000000'), ('ext', '9821169'), ('code', '5686')]
        if 'MIN(bizdate)' in sql:
            rows = [('basic', '2006-01-04', '2026-04-14'), ('extension', '2006-01-04', '2026-04-14')]
            return rows if not (self.failure == 'data-change' and self.restart_count == 1) else rows[:-1]
        if 'VIEW_DEFINITION' in sql:
            return [('v_hsj_stock_hq_basic', 'a' * 64), ('v_hsj_stock_hq_ext', 'b' * 64)]
        if 'data_snapshot_registry' in sql:
            return [('unexpected',)] if self.failure == 'registered' else []
        raise AssertionError('Unexpected SQL: ' + sql)

    def run(self, command, input=None, **kwargs):
        self.commands.append((command, input, kwargs))
        if command == self.command:
            if self.stopped:
                return SimpleNamespace(returncode=1, stdout=b'', stderr=b'')
            sql = input.decode('utf-8').strip().rstrip(';')
            rows = self.query(sql)
            text = ''.join('\t'.join(row) + '\n' for row in rows)
            return SimpleNamespace(returncode=0, stdout=text.encode('utf-8'), stderr=b'')
        args = command[1:]
        result = ''
        if args[0] == 'inspect':
            template = args[2]
            if 'Labels' in template:
                identity = 'c' * 64 if self.failure == 'identity' and self.restart_count else 'd' * 64
                result = identity + ' ' + ('production' if self.failure == 'owner' else memory.PURPOSE)
            elif '.HostConfig.Memory' in template:
                result = f'{self.memory} 4000000000'
            elif '.HostConfig.Tmpfs' in template:
                result = json.dumps({'/run': 'rw'}) if self.failure == 'tmpfs' else 'null'
            elif '.Mounts' in template:
                result = json.dumps([dict(Type='bind', Destination=memory.ENTRYPOINT, RW=False)])
            elif '.Config.Env' in template:
                if '{{json .Config.Env}}' in template:
                    raise AssertionError('Full secret environment must never be captured')
                result = self.heap_lines
            else:
                raise AssertionError('Unexpected inspect format: ' + template)
        elif args[0] == 'cp':
            if self.failure == 'rollback-fail':
                return SimpleNamespace(returncode=7, stdout=b'', stderr=b'credential must not be emitted')
            if args[1:] != ['-', memory.CONTAINER + ':/run'] or not isinstance(input, bytes):
                raise AssertionError('Cross-platform rollback must stream a tar archive')
            with tarfile.open(fileobj=io.BytesIO(input), mode='r') as archive:
                members = archive.getmembers()
                if len(members) != 1 or members[0].name != 'dsl-be-memory-percent' or not members[0].isreg():
                    raise AssertionError('Rollback tar must contain only the fixed override file')
                self.override = archive.extractfile(members[0]).read().decode('ascii')
        elif args[0] == 'restart':
            self.restart_count += 1
            self.stopped = self.failure == 'stopped' and self.restart_count == 1
            self.share = '40%' if self.failure in ('readiness', 'rollback-fail') and self.restart_count == 1 else self.override.strip() + '%'
        elif self.stopped:
            return SimpleNamespace(returncode=1, stdout=b'', stderr=b'')
        elif 'curl' in args:
            result = json.dumps([['mem_limit', 'string', self.share]])
        elif 'sed' in args:
            result = self.fe[:-1] + '\n'
        elif 'cat' in args and memory.ENTRYPOINT in args:
            result = 'unsupported' if self.failure == 'entrypoint' else '\n'.join([memory.ENTRYPOINT_MARKER, memory.OVERRIDE, 'BE_CONFIG_EXTRA'])
        elif 'cat' in args and memory.CONF in args:
            result = 'mem_limit = ' + self.share + '\n'
        elif 'dsl-be-memory-read' in args:
            if self.failure == 'bad-readback' and self.override == '60\n':
                result = 'PRESENT\n40\n'
            else:
                result = 'ABSENT\n' if self.override is None else 'PRESENT\n' + self.override
        elif 'dsl-be-memory-backup' in args:
            self.backup = self.override
        elif 'dsl-be-memory-write' in args:
            if self.failure == 'write' and input == b'60\n':
                return SimpleNamespace(returncode=3, stdout=b'', stderr=b'credential must not be emitted')
            if not isinstance(input, bytes):
                raise AssertionError('Override must use binary stdin')
            self.override = input.decode('ascii')
        else:
            raise AssertionError('Unexpected Docker operation: ' + str(args))
        return SimpleNamespace(returncode=0, stdout=result.encode('utf-8'), stderr=b'')


class BeMemorySafetyTest(unittest.TestCase):
    def apply(self, container):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        with patch.object(memory.subprocess, 'run', side_effect=container.run):
            report = memory.apply_configuration(container, folder, attempts=1, sleeper=lambda _: None)
        self.assertEqual(json.loads((folder / 'result.json').read_text(encoding='utf-8'))['status'], report['status'])
        return report, folder

    def test_owned_5g_application_retains_container_and_query_budgets(self):
        container = FakeContainer()
        report, folder = self.apply(container)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['afterBeBytes'], 3221225472)
        self.assertEqual(report['environmentBefore']['containerMemoryBytes'], 5368709120)
        self.assertEqual(report['queryMaxExecutionMemoryBytes'], 2147483648)
        self.assertEqual(report['queryTimeoutSeconds'], 10)
        self.assertEqual(report['overrideBefore'], 'ABSENT')
        self.assertEqual((folder / 'override-before.txt').read_bytes(), b'ABSENT\n')
        self.assertEqual(container.override, '60\n')
        self.assertEqual(container.restart_count, 1)
        self.assertTrue(report['sourceStateUnchanged'])
        self.assertTrue(report['containerAndHeapBudgetsUnchanged'])
        self.assertEqual([value for command, value, _ in container.commands if 'dsl-be-memory-write' in command], [b'60\n'])
        self.assertTrue((folder / 'be-conf-before.txt').is_file())
        self.assertTrue((folder / 'be-conf-after.txt').is_file())
        self.assertTrue(all(not options.get('text', False) for _, _, options in container.commands))

    def test_owned_10g_2048m_compatibility(self):
        report, _ = self.apply(FakeContainer(memory_bytes=10737418240, fe='2048m'))
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['afterBeBytes'], 6442450944)

    def test_nonempty_unknown_and_duplicate_heap_lines_remain_rejected(self):
        for extra in ['UNREVIEWED_HEAP=128m\n', 'FE_HEAP=768m\n']:
            with self.subTest(extra=extra):
                container = FakeContainer()
                container.heap_lines += extra
                report, _ = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertIn('Unrecognized diagnostic heap configuration', report['fatalError'])
                self.assertEqual(report['rollbackStatus'], 'NOT_NEEDED')
                self.assertEqual(container.restart_count, 0)
                self.assertFalse(any('dsl-be-memory-write' in command for command, _, _ in container.commands))

    def test_unowned_wrong_budget_and_unsupported_entrypoint_fail_before_mutation(self):
        for container in [FakeContainer(failure='owner'), FakeContainer(memory_bytes=6442450944),
                FakeContainer(fe='1024m'), FakeContainer(failure='entrypoint'),
                FakeContainer(failure='registered'), FakeContainer(failure='tmpfs')]:
            with self.subTest(container=container.failure):
                report, _ = self.apply(container)
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(report['rollbackStatus'], 'NOT_NEEDED')
                self.assertEqual(container.restart_count, 0)
                self.assertFalse(any('dsl-be-memory-write' in command for command, _, _ in container.commands))

    def test_existing_override_is_backed_up_without_changing_its_bytes(self):
        container = FakeContainer(original='40\r\n')
        report, folder = self.apply(container)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(container.backup, '40\r\n')
        self.assertEqual((folder / 'override-before.txt').read_bytes(), b'40\r\n')
        self.assertIn('containerOverrideBackupPath', report)

    def test_failed_readiness_restores_effective_40_when_original_override_absent(self):
        container = FakeContainer(failure='readiness')
        report, folder = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'DONE')
        self.assertEqual(container.override, '40\n')
        self.assertEqual(container.restart_count, 2)
        self.assertEqual((folder / 'override-rollback.txt').read_bytes(), b'40\n')
        self.assertEqual(report['rollbackRuntimeBeShare'], '40%')
        self.assertEqual(report['rollbackFileState'], 'EXPLICIT_40_RESTORES_PREVIOUS_EFFECTIVE_SHARE')

    def test_state_change_restores_original_override_and_preserves_failure(self):
        container = FakeContainer(original='40\r\n', failure='data-change')
        report, _ = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'DONE')
        self.assertIn('date bounds', report['fatalError'])
        self.assertEqual(container.override, '40\r\n')
        self.assertEqual(container.restart_count, 2)

    def test_failed_write_attempts_rollback_and_omits_command_stderr(self):
        container = FakeContainer(failure='write')
        report, _ = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'DONE')
        self.assertEqual(container.override, '40\n')
        self.assertNotIn('credential', json.dumps(report))

    def test_bad_readback_is_rolled_back_before_first_restart(self):
        container = FakeContainer(failure='bad-readback')
        report, _ = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'DONE')
        self.assertEqual(container.override, '40\n')
        self.assertEqual(container.restart_count, 1)

    def test_stopped_container_uses_copy_rollback_then_restarts(self):
        container = FakeContainer(failure='stopped')
        report, _ = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'DONE')
        self.assertFalse(container.stopped)
        self.assertEqual(container.override, '40\n')
        self.assertEqual(container.restart_count, 2)
        self.assertTrue(any(command[1] == 'cp' for command, _, _ in container.commands if command[0] == 'docker'))

    def test_failed_rollback_keeps_original_and_recovery_errors(self):
        report, _ = self.apply(FakeContainer(failure='rollback-fail'))
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'FAILED')
        self.assertTrue(report['fatalError'])
        self.assertEqual(len(report['rollbackErrors']), 2)
        self.assertTrue(report['rollbackCommands'])

    def test_changed_container_identity_prevents_rollback_mutation(self):
        container = FakeContainer(failure='identity')
        report, _ = self.apply(container)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['rollbackStatus'], 'FAILED')
        self.assertIn('identity changed', report['fatalError'])
        self.assertEqual(container.restart_count, 1)
        self.assertFalse(any(command[1] == 'cp' for command, _, _ in container.commands if command[0] == 'docker'))

    def test_override_shape_is_fail_closed(self):
        self.assertIsNone(memory.parse_override('ABSENT\n'))
        self.assertEqual(memory.parse_override('PRESENT\n40\r\n'), '40\r\n')
        for value in ['PRESENT\n80\n', 'PRESENT\n40\n60\n', 'PRESENT\n 40\n', 'ABSENT\n40']:
            with self.assertRaises(ValueError):
                memory.parse_override(value)

    def test_rollback_tar_has_only_fixed_regular_override_and_exact_bytes(self):
        with tarfile.open(fileobj=io.BytesIO(memory.override_archive(b'40\r\n')), mode='r') as archive:
            self.assertEqual(archive.getnames(), ['dsl-be-memory-percent'])
            member = archive.getmembers()[0]
            self.assertTrue(member.isreg())
            self.assertEqual(member.mode, 0o600)
            self.assertEqual(archive.extractfile(member).read(), b'40\r\n')

    def test_existing_evidence_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / 'result.json'
            evidence.write_text('old', encoding='utf-8')
            with patch('sys.argv', ['runner', '--output-dir', folder]), patch.object(memory, 'WslDoris') as client:
                with self.assertRaisesRegex(ValueError, 'fresh output'):
                    memory.main()
                client.assert_not_called()
            self.assertEqual(evidence.read_text(encoding='utf-8'), 'old')


if __name__ == '__main__':
    unittest.main()
