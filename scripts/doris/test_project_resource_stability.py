"""Portable contracts for native resource evidence; these are not native measurements."""
import unittest
from unittest.mock import Mock, patch
from copy import deepcopy
import builtins
import json
import os
from pathlib import Path
import tempfile
import check_project_resource_stability as resource


class ResourceStabilityContractTest(unittest.TestCase):
    def test_serial_warmup_is_distinct_from_concurrent_and_performance_samples(self):
        chosen = [dict(case=dict(name=name)) for name in ('one', 'two')]
        trace = []
        def request(endpoint, case):
            trace.append(('request', case['name']))
            return 200, {'rows': []}, 0.1
        def check(name, ok, **detail):
            self.assertTrue(ok)
            trace.append(('check', name))
        def verify(case, data, phase, replica, wall):
            self.assertEqual((phase, replica, wall), ('warmup', 1, 0.1))
            trace.append(('verify', case['name']))
        resource.warmup_cases('endpoint', chosen, request, verify, check)
        self.assertEqual(trace, [('request', 'one'), ('check', 'warmup-http-one'), ('verify', 'one'),
                                 ('request', 'two'), ('check', 'warmup-http-two'), ('verify', 'two')])

    def test_failed_warmup_fails_closed_without_retrying_or_running_next_case(self):
        request = Mock(return_value=(504, {'category': 'timeout'}, 10.0))
        verify = Mock()
        def check(name, ok, **detail):
            if not ok: raise AssertionError(name)
        with self.assertRaisesRegex(AssertionError, 'warmup-http-one'):
            resource.warmup_cases('endpoint', [dict(case=dict(name='one')), dict(case=dict(name='two'))], request, verify, check)
        self.assertEqual(request.call_count, 1)
        verify.assert_not_called()

    def test_http_failure_is_saved_with_reason_and_secrets_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = resource.save_http_failure(tmp, {'name': 'market/a|b'}, 504,
                {'category': 'timeout', 'message': 'queue wait exceeded token=secret'}, 10.1, ['secret'])
            evidence = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(path.parent, Path(tmp))
            self.assertEqual(evidence['httpStatus'], 504)
            self.assertEqual(evidence['wallSeconds'], 10.1)
            self.assertEqual(evidence['response']['category'], 'timeout')
            self.assertNotIn('secret', path.read_text(encoding='utf-8'))
            self.assertIn('[REDACTED]', evidence['response']['message'])

    def test_timeout_probe_uses_compiled_application_classpath_not_source_launcher(self):
        with patch.object(resource.shutil, 'which', return_value=None), tempfile.TemporaryDirectory() as tmp:
            compile_command, command = resource.timeout_probe_commands('D:/java/bin/java.exe', tmp, ['--driver-self-check'])
            self.assertEqual(compile_command[0], str(Path('D:/java/bin/javac.exe')))
            self.assertEqual(compile_command[-1], str(resource.ROOT / 'scripts/doris/ProjectResourceTimeoutProbe.java'))
            self.assertEqual(compile_command[compile_command.index('-d') + 1], str(Path(tmp).resolve()))
            self.assertEqual(command[command.index('-cp') + 1], os.pathsep.join((str(Path(tmp).resolve()), str(resource.ROOT / 'target/dsl-doris-compiler.jar'))))
            self.assertEqual(command[-2:], ['ProjectResourceTimeoutProbe', '--driver-self-check'])
            self.assertFalse(any(arg.endswith('.java') for arg in command))

    def test_timeout_probe_resolves_javac_from_same_java_installation(self):
        with patch.object(resource.shutil, 'which', return_value='/opt/jdk/bin/java'):
            compile_command, command = resource.timeout_probe_commands('java', 'classes')
            self.assertEqual(compile_command[0], str(Path('/opt/jdk/bin/javac')))
            self.assertEqual(command[0], '/opt/jdk/bin/java')

    def test_timeout_driver_self_check_is_required_and_not_a_native_timeout_pass(self):
        proof = dict(status='PASS', executorClassLoaderVisible=True, driverManagerVisible=True, nativeRuntime='NOT_RUN')
        resource.validate_driver_registration(proof)
        for key, value in [('status', 'COMPILE_ONLY'), ('executorClassLoaderVisible', False),
                           ('driverManagerVisible', False), ('nativeRuntime', 'PASS')]:
            with self.subTest(key=key), self.assertRaises(AssertionError):
                resource.validate_driver_registration(dict(proof, **{key: value}))
        with self.assertRaises(AssertionError): resource.validate_timeout(proof)

    def data(self):
        return dict(limits=dict(resource.BUDGET), dataQuality=dict(certificateSha256='cert', diagnosticTimings={
            name: 1.0 for name in ['sourceValidationMillis', 'mainExplainMillis', 'availabilityExplainMillis', 'missingStatisticsMillis', 'sampleDetailsMillis']}))

    def test_http_queue_budget_is_explicit_without_relaxing_query_limits(self):
        connection = ['--host', '127.0.0.1', '--port', '9030', '--database', 'newzl',
            '--user', 'readonly', '--password-env', 'DSL_PROJECT_PASSWORD',
            '--max-scan-rows', '100000000', '--max-exec-memory-bytes', '2147483648',
            '--max-return-rows', '10000']
        command = resource.http_server_command(['java', '-jar', 'compiler.jar'], connection, 'certificate.json')
        self.assertEqual(command.count('--max-queue-wait-ms'), 1)
        self.assertEqual(command[command.index('--max-queue-wait-ms') + 1], '10000')
        for name, value in [('--max-scan-rows', '100000000'),
                            ('--max-exec-memory-bytes', '2147483648'), ('--max-return-rows', '10000')]:
            self.assertEqual(command[command.index(name) + 1], value)
        self.assertNotIn('--max-queue-wait-ms', connection)
        self.assertEqual(resource.BUDGET['queryTimeoutSeconds'], 10)

    def test_budget_and_diagnostic_stage_contract(self):
        checks = resource.validate_execution(self.data(), {}, 'cert', lambda actual, expected: dict(fullRows=True, coverage=True))
        self.assertTrue(all(checks.values()))
        for key, changed in [('queryTimeoutSeconds', 11), ('maxExecutionMemoryBytes', 3 << 30), ('maxReturnRows', 10001), ('maxEstimatedScanRows', 100000001)]:
            data = self.data(); data['limits'][key] = changed
            with self.assertRaisesRegex(AssertionError, 'policy mismatch'):
                resource.validate_execution(data, {}, 'cert', lambda a, e: {})

    def test_complete_results_and_coverage_are_required(self):
        for check in ['fullRows', 'orderEqual', 'missingCounts', 'completeResult']:
            with self.assertRaisesRegex(AssertionError, check):
                resource.validate_execution(self.data(), {}, 'cert', lambda a, e: {check: False})

    def test_missing_stage_measurement_is_not_a_performance_pass(self):
        for changed in [None, {}, {'sourceValidationMillis': -1}]:
            data = self.data(); data['dataQuality']['diagnosticTimings'] = changed
            with self.assertRaisesRegex(AssertionError, 'diagnosticTimingsAvailable'):
                resource.validate_execution(data, {}, 'cert', lambda a, e: {})

    def test_certificate_change_is_detected(self):
        with self.assertRaisesRegex(AssertionError, 'certificateEqual'):
            resource.validate_execution(self.data(), {}, 'wrong', lambda a, e: {})

    def test_boolean_and_nonfinite_timings_are_rejected(self):
        for invalid in (True, False, float('inf'), float('-inf'), float('nan')):
            data=self.data();data['dataQuality']['diagnosticTimings']['missingStatisticsMillis']=invalid
            with self.subTest(invalid=invalid),self.assertRaisesRegex(AssertionError,'diagnosticTimingsAvailable'):
                resource.validate_execution(data, {}, 'cert', lambda a,e: {})

    def test_only_actual_jdbc_timeout_control_counts(self):
        proof = dict(status='PASS', controlQuery='SELECT SLEEP(4)', jdbcTimeoutSeconds=1,
                     actualSlowQueryReached=True, timeoutCategory='TIMEOUT', recovery={})
        resource.validate_timeout(proof)
        for key, value in [('controlQuery', 'invalid-http-param'), ('actualSlowQueryReached', False),
                           ('timeoutCategory', 'SEMANTIC'), ('recovery', None), ('status', 'NOT_RUN')]:
            altered = dict(proof); altered[key] = value
            with self.assertRaises(AssertionError): resource.validate_timeout(altered)

    def test_unowned_restart_is_refused(self):
        for output in ['production', '', 'official-data-diagnostic-maybe']:
            with patch.object(resource.subprocess, 'run', return_value=Mock(returncode=0, stdout=output)):
                with self.assertRaisesRegex(ValueError, 'ownership label'): resource.ownership(['docker'])
        with patch.object(resource.subprocess, 'run', return_value=Mock(returncode=0, stdout=resource.PURPOSE + '\n')):
            resource.ownership(['docker'])

    def test_representatives_are_frozen_deterministic_and_diverse(self):
        def case(name, calls, **extra): return dict(name=name, calls=calls, date='2026-04-14', **extra)
        combination = [case('multi', [dict(kind='field')] * 3), case('window', [dict(kind='ma')]),
                       case('fund', [dict(kind='field', metric='net')])]
        rank = [case('then-rank', [dict(kind='rank')], pre=['cmp']), case('query', [dict(kind='query')]), case('count', [dict(kind='count')])]
        chosen = resource.select_cases(combination, rank)
        self.assertEqual(chosen, resource.select_cases(deepcopy(combination), deepcopy(rank)))
        self.assertEqual({item['oracle'] for item in chosen}, {'combination', 'rank'})
        self.assertEqual([item['case']['name'] for item in chosen], ['multi', 'window', 'fund', 'then-rank', 'query', 'count'])
        with self.assertRaises(ValueError): resource.select_cases([], rank)

    def test_logs_do_not_disclose_generated_secrets(self):
        self.assertEqual(resource.redact('pwd=secret token=credential', ['secret', 'credential']), 'pwd=[REDACTED] token=[REDACTED]')

    def test_missing_environment_publishes_not_run_exit_two(self):
        actual_import = builtins.__import__
        def import_without_duckdb(name, *args, **kwargs):
            if name == 'duckdb': raise ImportError('synthetic missing dependency')
            return actual_import(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'new-run'
            arguments = ['runner', '--certificate', 'missing.json', '--output-dir', str(output),
                         '--matrix', 'missing-matrix.json', '--reference-database', 'missing.duckdb']
            with patch.object(resource.sys, 'argv', arguments), patch('builtins.__import__', side_effect=import_without_duckdb):
                self.assertEqual(resource.main(), 2)
            report = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'NOT_RUN')
            self.assertEqual(report['executions'], [])
            self.assertEqual(report['timeoutStatus'], 'NOT_RUN')
            self.assertEqual(report['cleanup'], 'NOT_NEEDED')
            concurrency = report['concurrency']
            self.assertEqual(concurrency['concurrentRequests'], 2)
            self.assertEqual(concurrency['databaseQueryParallelism'], 1)
            self.assertEqual(concurrency['executorMode'], 'SHARED_SINGLE_CONNECTION_SERIALIZED')
            command = resource.http_server_command(['java'], [], 'certificate.json')
            self.assertEqual(int(command[command.index('--max-queue-wait-ms') + 1]), concurrency['maxQueueWaitMillis'])
            self.assertIn('Two concurrent HTTP requests', concurrency['interpretation'])
            self.assertIn('database queries are serialized', concurrency['interpretation'])

    def test_output_protection_precedes_external_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'old-run'; output.mkdir()
            preserved = output / 'result.json'; preserved.write_text('old evidence', encoding='utf-8')
            arguments = ['runner', '--certificate', 'missing.json', '--output-dir', str(output),
                         '--matrix', 'missing.json', '--reference-database', 'missing.duckdb']
            with patch.object(resource.sys, 'argv', arguments), patch.object(resource.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'fresh output'): resource.main()
                run.assert_not_called()
            self.assertEqual(preserved.read_text(encoding='utf-8'), 'old evidence')


if __name__ == '__main__':
    unittest.main()
