"""Offline tests for the actual nested matrix/resource environment snapshots.

Only the nested function is AST-extracted; neither runner's main() is executed.
Every subprocess call is mocked and allowlisted to inspect/curl/config cat.
"""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import check_project_resource_stability as resource
import check_project_window_performance as matrix
import project_fe_runtime as fe_runtime
from configure_project_be_runtime import RUNTIME_TARGET


def extract_environment(module, client):
    source_path = Path(module.__file__)
    syntax = ast.parse(source_path.read_text(encoding='utf-8'), filename=str(source_path))
    main = next(node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    environments = [node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'environment']
    if len(environments) != 1:
        raise AssertionError('Exactly one main-local environment snapshot function required')
    extracted = ast.fix_missing_locations(ast.Module(body=[deepcopy(environments[0])], type_ignores=[]))
    namespace = dict(module.__dict__)
    ownership = Mock()
    namespace.update(client=client, ownership=ownership)
    exec(compile(extracted, str(source_path), 'exec'), namespace)
    return namespace['environment'], ownership


class FakeEnvironment:
    def __init__(self, module, rows=None, configuration=b'\xff\xfe\x00BE\x00 configuration\r\n\x80'):
        self.module = module
        self.client = SimpleNamespace(prefix=['offline-owned-docker'], be_http_port=18040)
        self.rows = rows if rows is not None else [['mem_limit', 'string', '60%'],
            ['webserver_port', 'int', '18040']] + [[key, 'int', value] for key, value in RUNTIME_TARGET.items()]
        self.configuration = configuration
        self.commands = []
        self.fe_process = 'MALLOC_ARENA_MAX=4\njvmEnvironmentCpu=4\nheapInitialMiB=768\nheapMaxMiB=768\n'
        self.fe_hashes = 'f' * 64 + '  ' + fe_runtime.FE_CONF + '\n' + 'd' * 64 + '  ' + fe_runtime.ENTRYPOINT + '\n'

    def run(self, command, **options):
        prefix = self.client.prefix
        inspect_template = ('{{.Id}} {{.State.Running}} {{index .Config.Labels "com.acme.dorisdsl.purpose"}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'
            if self.module is matrix else '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}')
        inspect = prefix + ['inspect', '-f', inspect_template, 'dsl-doris-official']
        curl = prefix + ['exec', 'dsl-doris-official', 'curl', '-fsS', '--max-time', '10',
            'http://127.0.0.1:18040/api/show_config']
        config_cat = prefix + ['exec', 'dsl-doris-official', 'cat', '/opt/apache-doris/be/conf/be.conf']
        fe_kind = ('profile' if command[-2:] == ['dsl-fe-profile-identity', fe_runtime.PROFILE_PATH] else
                   'process' if command[-1] == 'dsl-fe-runtime-identity' else
                   'hashes' if command == prefix + ['exec', 'dsl-doris-official', 'sha256sum', fe_runtime.FE_CONF, fe_runtime.ENTRYPOINT] else None)
        if command not in (inspect, curl, config_cat) and fe_kind is None:
            raise AssertionError('Only reviewed BE reads and selective FE process/configuration reads are permitted')
        if options.get('capture_output') is not True or (fe_kind is None and options.get('check') is not True) or options.get('timeout') != 20:
            raise AssertionError('Environment reads require bounded, checked, captured subprocesses')
        self.commands.append((command, options))
        if fe_kind is not None:
            output = {'profile': 'bounded-v1\n', 'process': self.fe_process, 'hashes': self.fe_hashes}[fe_kind].encode('utf-8')
        elif command == inspect:
            output = ('a' * 64 + ' true official-data-diagnostic 5368709120 4000000000\n'
                if self.module is matrix else '5368709120 4000000000\n')
        elif command == curl:
            output = json.dumps(self.rows)
        else:
            if any(key in options for key in ('text', 'encoding', 'errors', 'universal_newlines')):
                raise AssertionError('BE configuration must be captured as raw bytes, without UTF-8 decoding')
            output = self.configuration
        return SimpleNamespace(returncode=0, stdout=output, stderr=b'\xff\xfe\x00unparsed Windows stderr\x00')


class RuntimeEnvironmentEvidenceTest(unittest.TestCase):
    def snapshot(self, module, rows=None, configuration=b'\xff\xfe\x00BE\x00 configuration\r\n\x80'):
        fake = FakeEnvironment(module, rows, configuration)
        environment, ownership = extract_environment(module, fake.client)
        with patch.object(module.subprocess, 'run', side_effect=fake.run):
            observed = environment()
        return observed, fake, ownership

    def test_matrix_captures_all_eight_runtime_knobs_and_binary_config_digest(self):
        observed, fake, ownership = self.snapshot(matrix)
        self.assertEqual(observed['containerMemoryBytes'], 5368709120)
        self.assertEqual(observed['containerId'], 'a' * 64)
        self.assertEqual(observed['containerNanoCpus'], 4000000000)
        self.assertEqual(observed['beMemoryShare'], '60%')
        self.assertEqual(observed['beRuntimeSettings'], RUNTIME_TARGET)
        self.assertEqual(len(observed['beRuntimeSettings']), 8)
        self.assertEqual(observed['beConfigurationSha256'], hashlib.sha256(fake.configuration).hexdigest())
        self.assertEqual(len(fake.commands), 6)
        self.assertEqual(observed['feRuntime']['mallocArenaMax'], 4)
        self.assertEqual(observed['feRuntime']['activeProcessorCount'], 4)
        ownership.assert_not_called()

    def test_resource_captures_cpu_budget_all_knobs_and_binary_config_digest(self):
        observed, fake, ownership = self.snapshot(resource)
        self.assertEqual(observed['containerMemoryBytes'], 5368709120)
        self.assertEqual(observed['containerNanoCpus'], 4000000000)
        self.assertEqual(observed['beMemoryShare'], '60%')
        self.assertEqual(observed['beRuntimeSettings'], RUNTIME_TARGET)
        self.assertEqual(len(observed['beRuntimeSettings']), 8)
        self.assertEqual(observed['beConfigurationSha256'], hashlib.sha256(fake.configuration).hexdigest())
        self.assertEqual(len(fake.commands), 6)
        self.assertEqual(observed['feRuntime']['heapMaxMiB'], 768)
        ownership.assert_called_once_with(fake.client.prefix)

    def test_each_missing_required_runtime_key_is_rejected_by_both_actual_functions(self):
        for module in (matrix, resource):
            for missing in RUNTIME_TARGET:
                with self.subTest(module=module.__name__, missing=missing):
                    rows = [['mem_limit', 'string', '60%']] + [[key, 'int', value] for key, value in RUNTIME_TARGET.items() if key != missing]
                    fake = FakeEnvironment(module, rows)
                    environment, _ = extract_environment(module, fake.client)
                    with patch.object(module.subprocess, 'run', side_effect=fake.run):
                        with self.assertRaisesRegex(ValueError, 'Incomplete or duplicate BE runtime settings'):
                            environment()
                    self.assertEqual(len(fake.commands), 2)

    def test_fe_process_heap_config_and_entrypoint_changes_are_frozen_by_both_runners(self):
        for module in (matrix, resource):
            original, _, _ = self.snapshot(module)
            for target, changed in (('fe_process', 'MALLOC_ARENA_MAX=4\njvmEnvironmentCpu=4\nheapInitialMiB=512\nheapMaxMiB=512\n'),
                                    ('fe_hashes', 'a' * 64 + '  ' + fe_runtime.FE_CONF + '\n' + 'd' * 64 + '  ' + fe_runtime.ENTRYPOINT + '\n'),
                                    ('fe_hashes', 'f' * 64 + '  ' + fe_runtime.FE_CONF + '\n' + 'b' * 64 + '  ' + fe_runtime.ENTRYPOINT + '\n')):
                with self.subTest(module=module.__name__, target=target, changed=changed):
                    fake = FakeEnvironment(module)
                    setattr(fake, target, changed)
                    environment, _ = extract_environment(module, fake.client)
                    with patch.object(module.subprocess, 'run', side_effect=fake.run):
                        actual = environment()
                    self.assertNotEqual(original['feRuntime'], actual['feRuntime'])

    def test_each_duplicate_required_runtime_key_is_rejected_by_both_actual_functions(self):
        for module in (matrix, resource):
            for duplicate in RUNTIME_TARGET:
                with self.subTest(module=module.__name__, duplicate=duplicate):
                    rows = [['mem_limit', 'string', '60%']] + [[key, 'int', value] for key, value in RUNTIME_TARGET.items()]
                    rows.append([duplicate, 'int', RUNTIME_TARGET[duplicate]])
                    fake = FakeEnvironment(module, rows)
                    environment, _ = extract_environment(module, fake.client)
                    with patch.object(module.subprocess, 'run', side_effect=fake.run):
                        with self.assertRaisesRegex(ValueError, 'Incomplete or duplicate BE runtime settings'):
                            environment()
                    self.assertEqual(len(fake.commands), 2)

    def test_same_count_but_duplicate_and_missing_keys_is_still_rejected(self):
        keys = list(RUNTIME_TARGET)
        for module in (matrix, resource):
            with self.subTest(module=module.__name__):
                rows = [['mem_limit', 'string', '60%']] + [[key, 'int', value] for key, value in RUNTIME_TARGET.items() if key != keys[0]]
                rows.append([keys[1], 'int', RUNTIME_TARGET[keys[1]]])
                fake = FakeEnvironment(module, rows)
                environment, _ = extract_environment(module, fake.client)
                with patch.object(module.subprocess, 'run', side_effect=fake.run):
                    with self.assertRaisesRegex(ValueError, 'Incomplete or duplicate BE runtime settings'):
                        environment()

    def test_raw_byte_changes_are_detected_without_normalizing_newlines_or_decoding(self):
        for module in (matrix, resource):
            with self.subTest(module=module.__name__):
                a, _, _ = self.snapshot(module, configuration=b'\xffconf\r\n')
                b, _, _ = self.snapshot(module, configuration=b'\xffconf\n')
                self.assertNotEqual(a['beConfigurationSha256'], b['beConfigurationSha256'])
                self.assertEqual(a['beRuntimeSettings'], b['beRuntimeSettings'])

    def test_changes_to_any_selected_knob_are_visible_in_the_freeze_snapshot(self):
        for module in (matrix, resource):
            initial, _, _ = self.snapshot(module)
            for key in RUNTIME_TARGET:
                with self.subTest(module=module.__name__, key=key):
                    changed = dict(RUNTIME_TARGET)
                    changed[key] = '99999'
                    rows = [['mem_limit', 'string', '60%']] + [[name, 'int', value] for name, value in changed.items()]
                    observed, _, _ = self.snapshot(module, rows=rows)
                    self.assertNotEqual(initial, observed)
                    self.assertEqual(observed['beRuntimeSettings'][key], '99999')

    def test_matrix_rejects_unowned_stopped_or_malformed_container_metadata(self):
        valid = 'a' * 64 + ' true official-data-diagnostic 5368709120 4000000000\n'
        for output in (valid.replace('true', 'false'), valid.replace('official-data-diagnostic', 'other'),
                       valid.replace('a' * 64, 'short'), valid.replace('5368709120', '0'),
                       valid.replace('4000000000', 'untrusted-secret'), valid + 'extra metadata'):
            fake = FakeEnvironment(matrix)
            environment, _ = extract_environment(matrix, fake.client)
            def changed(command, **options):
                result = fake.run(command, **options)
                if 'inspect' in command:
                    result.stdout = output
                return result
            with self.subTest(output=output[:20]), patch.object(matrix.subprocess, 'run', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'running owned container'):
                    environment()
            self.assertEqual(1, len(fake.commands))

    def test_matrix_rejects_missing_duplicate_memory_share_and_empty_config(self):
        for rows in (FakeEnvironment(matrix).rows[1:],
                     FakeEnvironment(matrix).rows + [['mem_limit', 'string', '40%']]):
            fake = FakeEnvironment(matrix, rows)
            environment, _ = extract_environment(matrix, fake.client)
            with patch.object(matrix.subprocess, 'run', side_effect=fake.run):
                with self.assertRaisesRegex(ValueError, 'BE memory limit'):
                    environment()
        fake = FakeEnvironment(matrix, configuration=b'')
        environment, _ = extract_environment(matrix, fake.client)
        with patch.object(matrix.subprocess, 'run', side_effect=fake.run):
            with self.assertRaisesRegex(ValueError, 'Empty or non-binary'):
                environment()

    def test_restart_metadata_is_not_selected_but_replacement_id_cpu_memory_are(self):
        first, _, _ = self.snapshot(matrix)
        for original, replacement, key, value in (('a' * 64, 'b' * 64, 'containerId', 'b' * 64),
                ('4000000000', '2000000000', 'containerNanoCpus', 2000000000),
                ('5368709120', '4294967296', 'containerMemoryBytes', 4294967296)):
            fake = FakeEnvironment(matrix)
            environment, _ = extract_environment(matrix, fake.client)
            def changed(command, **options):
                result = fake.run(command, **options)
                if 'inspect' in command:
                    self.assertNotIn('RestartCount', command[command.index('-f') + 1])
                    self.assertNotIn('StartedAt', command[command.index('-f') + 1])
                    result.stdout = result.stdout.replace(original, replacement)
                return result
            with patch.object(matrix.subprocess, 'run', side_effect=changed):
                observed = environment()
            self.assertNotEqual(first, observed)
            self.assertEqual(observed[key], value)


class FailurePreservationEvidenceTest(unittest.TestCase):
    def report(self):
        return dict(sourceStateBefore=[[['basic', '1']], []], environment={'config': 'frozen'},
                    checks=[], fatalError='original SQL failure')

    def test_postconditions_are_captured_even_when_original_query_failed(self):
        report = self.report()
        matrix.capture_preservation(report, lambda: deepcopy(report['sourceStateBefore']),
                                    lambda: deepcopy(report['environment']))
        self.assertEqual([], report['preservationErrors'])
        self.assertEqual('original SQL failure', report['fatalError'])
        self.assertEqual(report['sourceStateBefore'], report['sourceStateAfter'])
        self.assertEqual(report['environment'], report['environmentAfter'])
        self.assertEqual(['PASS', 'PASS'], [c['status'] for c in report['checks']])

    def test_source_change_is_not_hidden_by_done_cleanup_or_stable_runtime(self):
        report = dict(self.report(), cleanup='DONE')
        matrix.capture_preservation(report, lambda: [[['basic', '2']], []], lambda: {'config': 'frozen'})
        self.assertEqual('FAIL', report['checks'][0]['status'])
        self.assertTrue(report['preservationErrors'])
        self.assertEqual('DONE', report['cleanup'])

    def test_missing_initial_state_and_failed_postcheck_are_explicit_not_success(self):
        report = dict(checks=[])
        matrix.capture_preservation(report, lambda: self.fail('No snapshot without initial state'),
                                    lambda: self.fail('No snapshot without initial state'))
        self.assertEqual(['NOT_RUN', 'NOT_RUN'], [c['status'] for c in report['checks']])
        self.assertEqual(2, len(report['preservationErrors']))
        report = self.report()
        def failed():
            raise OSError('private connection details must not appear')
        matrix.capture_preservation(report, failed, lambda: {'config': 'frozen'})
        self.assertEqual('FAIL', report['checks'][0]['status'])
        self.assertNotIn('private connection', json.dumps(report))
        self.assertEqual('original SQL failure', report['fatalError'])

    def test_actual_main_places_postcheck_in_finally_not_only_after_success_loop(self):
        syntax = ast.parse(Path(matrix.__file__).read_text(encoding='utf-8'))
        main = next(n for n in syntax.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        guarded = [n for n in main.body if isinstance(n, ast.Try) and n.finalbody]
        calls = [n for node in guarded for final in node.finalbody for n in ast.walk(final)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'capture_preservation']
        self.assertEqual(1, len(calls))


if __name__ == '__main__':
    unittest.main()
