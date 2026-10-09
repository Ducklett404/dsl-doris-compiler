"""Offline validation of the exact eight requested Doris JUnit report cases."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import contextlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_wsl_integration


REQUIRED_CASES = {
    'com.acme.dorisdsl.DorisExplainIntegrationTest': ['dorisExplainsLayeredRsiSql'],
    'com.acme.dorisdsl.stockslot.DorisControlledExecutionIntegrationTest': [
        'executesRealPreparedSelectOnTheValidatedSyntheticDataset',
        'returnCapIsEnforcedAndResultResourcesRemainUsable',
        'unvalidatedAndInjectedSnapshotIdsAreRejectedThenAnotherThreadCanExecute',
        'scanLimitRejectsBeforeExecutionAndReleasesTheQueueSlot',
        'accountsWithWritePrivilegeCannotInitializeTheExecutor',
        'queuedRequestTimesOutWhileFirstRequestHoldsTheSlotAndBothRecover',
        'realDatabaseTimeoutMapsToTimeoutAndTheNextRequestRecovers',
    ],
}


class RequiredJUnitReportContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='junit-required-report-selftest-')
        self.root = Path(self.temp.name)
        self.folder = self.root / 'surefire-reports'
        self.folder.mkdir()
        self.rows = {name: [{'name': method, 'status': 'PASS', 'classname': name} for method in methods]
                     for name, methods in REQUIRED_CASES.items()}
        self.write_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def report_file(self, name):
        return self.folder / ('TEST-' + name + '.xml')

    def write_suite(self, name, rows, attributes=None):
        attrs = {
            'name': name, 'tests': str(len(rows)),
            'failures': str(sum(item['status'] == 'FAIL' for item in rows)),
            'errors': str(sum(item['status'] == 'ERROR' for item in rows)),
            'skipped': str(sum(item['status'] == 'SKIPPED' for item in rows)),
            'time': '0.008', 'timestamp': '2026-10-06T12:00:00',
        }
        if attributes:
            attrs.update(attributes)
        suite = ET.Element('testsuite', attrs)
        ET.SubElement(suite, 'properties')
        for row in rows:
            case = ET.SubElement(suite, 'testcase', {
                'name': row['name'], 'classname': row['classname'], 'time': '0.001'})
            if row['status'] != 'PASS':
                tag = {'FAIL': 'failure', 'ERROR': 'error', 'SKIPPED': 'skipped'}[row['status']]
                child = ET.SubElement(case, tag, {'message': 'Synthetic test evidence', 'type': 'Synthetic'})
                child.text = 'Synthetic report fixture, not a real Doris or Maven run.'
        ET.ElementTree(suite).write(self.report_file(name), encoding='utf-8', xml_declaration=True)

    def write_fixture(self):
        for name, rows in self.rows.items():
            self.write_suite(name, rows)

    def summarize(self):
        return run_wsl_integration.summarize_required_junit(self.folder)

    def assert_fail(self):
        report = self.summarize()
        self.assertIsInstance(report, dict)
        self.assertEqual('FAIL', report['status'], report)
        return report

    def alter_attribute(self, suite_name, key, value):
        tree = ET.parse(self.report_file(suite_name))
        tree.getroot().set(key, value)
        tree.write(self.report_file(suite_name), encoding='utf-8', xml_declaration=True)

    def test_required_suite_counts_match_the_exact_eight_source_tests(self):
        self.assertEqual({name: len(methods) for name, methods in REQUIRED_CASES.items()},
                         run_wsl_integration.REQUIRED_SUITES)

    def test_eight_passing_cases_produce_pass_and_detailed_case_evidence(self):
        report = self.summarize()
        self.assertEqual('PASS', report['status'])
        self.assertEqual((8, 8, 0, 0, 0),
                         (report['tests'], report['passed'], report['failures'], report['errors'], report['skipped']))
        self.assertEqual(2, len(report['suites']))
        serialized_details = json.dumps(report['suites'])
        for methods in REQUIRED_CASES.values():
            for method in methods:
                self.assertIn(method, serialized_details)

    def test_one_skipped_case_must_not_count_as_pass(self):
        name = next(iter(REQUIRED_CASES))
        self.rows[name][0]['status'] = 'SKIPPED'
        self.write_fixture()
        report = self.assert_fail()
        self.assertEqual(1, report['skipped'])
        self.assertLess(report['passed'], 8)

    def test_one_failure_is_fail(self):
        name = next(iter(REQUIRED_CASES))
        self.rows[name][0]['status'] = 'FAIL'
        self.write_fixture()
        report = self.assert_fail()
        self.assertEqual(1, report['failures'])

    def test_one_error_is_fail(self):
        name = next(iter(REQUIRED_CASES))
        self.rows[name][0]['status'] = 'ERROR'
        self.write_fixture()
        report = self.assert_fail()
        self.assertEqual(1, report['errors'])

    def test_missing_explain_suite_is_fail(self):
        self.report_file(next(iter(REQUIRED_CASES))).unlink()
        self.assert_fail()

    def test_missing_controlled_execution_suite_is_fail(self):
        self.report_file(list(REQUIRED_CASES)[1]).unlink()
        self.assert_fail()

    def test_empty_report_directory_is_fail(self):
        empty = self.root / 'empty-reports'
        empty.mkdir()
        self.assertEqual('FAIL', run_wsl_integration.summarize_required_junit(empty)['status'])

    def test_nonexistent_report_directory_is_fail_and_is_not_created(self):
        missing = self.root / 'does-not-exist'
        self.assertEqual('FAIL', run_wsl_integration.summarize_required_junit(missing)['status'])
        self.assertFalse(missing.exists())

    def test_wrong_test_attribute_is_fail(self):
        self.alter_attribute(list(REQUIRED_CASES)[1], 'tests', '6')
        self.assert_fail()

    def test_missing_testcase_despite_correct_suite_attribute_is_fail(self):
        name = list(REQUIRED_CASES)[1]
        self.write_suite(name, self.rows[name][:-1], {'tests': '7'})
        self.assert_fail()

    def test_extra_testcase_does_not_replace_the_required_count(self):
        name = list(REQUIRED_CASES)[1]
        rows = self.rows[name] + [{'name': 'extraUnrequestedMethod', 'status': 'PASS', 'classname': name}]
        self.write_suite(name, rows)
        self.assert_fail()

    def test_unknown_method_with_same_count_is_not_the_required_eight(self):
        name = list(REQUIRED_CASES)[1]
        self.rows[name][0]['name'] = 'notTheRequiredPreparedExecutionTest'
        self.write_fixture()
        self.assert_fail()

    def test_duplicate_method_with_same_count_is_fail(self):
        name = list(REQUIRED_CASES)[1]
        self.rows[name][0] = copy.deepcopy(self.rows[name][1])
        self.write_fixture()
        self.assert_fail()

    def test_wrong_suite_name_is_not_the_required_suite(self):
        self.alter_attribute(next(iter(REQUIRED_CASES)), 'name', 'com.example.UnrelatedTest')
        self.assert_fail()

    def test_wrong_testcase_class_is_not_the_required_test(self):
        name = next(iter(REQUIRED_CASES))
        self.rows[name][0]['classname'] = 'com.example.UnrelatedTest'
        self.write_fixture()
        self.assert_fail()

    def test_skip_child_with_zero_reported_skips_is_fail(self):
        name = next(iter(REQUIRED_CASES))
        self.rows[name][0]['status'] = 'SKIPPED'
        self.write_suite(name, self.rows[name], {'skipped': '0'})
        self.assert_fail()

    def test_failure_child_with_zero_reported_failures_is_fail(self):
        name = next(iter(REQUIRED_CASES))
        self.rows[name][0]['status'] = 'FAIL'
        self.write_suite(name, self.rows[name], {'failures': '0'})
        self.assert_fail()

    def test_error_child_with_zero_reported_errors_is_fail(self):
        name = next(iter(REQUIRED_CASES))
        self.rows[name][0]['status'] = 'ERROR'
        self.write_suite(name, self.rows[name], {'errors': '0'})
        self.assert_fail()

    def test_reported_skip_without_child_is_inconsistent_and_fail(self):
        self.alter_attribute(next(iter(REQUIRED_CASES)), 'skipped', '1')
        self.assert_fail()

    def test_reported_failure_without_child_is_inconsistent_and_fail(self):
        self.alter_attribute(next(iter(REQUIRED_CASES)), 'failures', '1')
        self.assert_fail()

    def test_reported_error_without_child_is_inconsistent_and_fail(self):
        self.alter_attribute(next(iter(REQUIRED_CASES)), 'errors', '1')
        self.assert_fail()

    def test_noninteger_suite_counts_are_fail(self):
        self.alter_attribute(next(iter(REQUIRED_CASES)), 'tests', 'not-an-integer')
        self.assert_fail()

    def test_negative_suite_counts_are_fail(self):
        self.alter_attribute(next(iter(REQUIRED_CASES)), 'failures', '-1')
        self.assert_fail()

    def test_missing_suite_count_attribute_is_fail(self):
        name = next(iter(REQUIRED_CASES))
        tree = ET.parse(self.report_file(name))
        del tree.getroot().attrib['skipped']
        tree.write(self.report_file(name), encoding='utf-8', xml_declaration=True)
        self.assert_fail()

    def test_invalid_xml_is_fail_without_an_unexplained_crash(self):
        self.report_file(next(iter(REQUIRED_CASES))).write_text('<testsuite><testcase>', encoding='utf-8')
        self.assert_fail()

    def test_wrong_xml_root_is_fail(self):
        name = next(iter(REQUIRED_CASES))
        tree = ET.parse(self.report_file(name))
        tree.getroot().tag = 'unrelated-root'
        tree.write(self.report_file(name), encoding='utf-8', xml_declaration=True)
        self.assert_fail()

    def test_summarization_does_not_modify_reports(self):
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        self.summarize()
        after = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        self.assertEqual(before, after)


class MockedJUnitOnlyOrchestrationContracts(unittest.TestCase):
    """No processes or SQL execute: every external boundary is a strict fake."""
    write_suite = RequiredJUnitReportContracts.write_suite
    report_file = RequiredJUnitReportContracts.report_file

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='junit-only-orchestration-selftest-')
        self.root = Path(self.temp.name)
        self.folder = self.root / 'target/surefire-reports'
        self.folder.mkdir(parents=True)
        self.output = self.root / 'new-evidence'
        self.maven = self.root / 'synthetic-mvn.cmd'
        self.maven.write_text('Synthetic file: never executed.', encoding='utf-8')
        (self.root / 'pom.xml').write_text('<project/>', encoding='utf-8')
        resources = self.root / 'src/main/resources'
        resources.mkdir(parents=True)
        configs = {
            'stock-slot-registry-v1.json': {'tables': {'basic': {'qualifiedName': 'newzl.v_hsj_stock_hq_basic'}}},
            'registry.json': {'datasets': {'quote': 'newzl.dwd_quote_daily'}},
            'catalog-snapshot.json': {'tables': {'quote': 'newzl.dwd_quote_daily'}},
        }
        for name, value in configs.items():
            (resources / name).write_text(json.dumps(value), encoding='utf-8')
        java_source = self.root / 'src/main/java/Compiler.java'
        java_source.parent.mkdir(parents=True)
        java_source.write_text('// synthetic source', encoding='utf-8')
        self.java_source = java_source
        test_source = self.root / 'src/test/java/DorisExplainIntegrationTest.java'
        test_source.parent.mkdir(parents=True)
        test_source.write_text('// synthetic integration test source', encoding='utf-8')
        for directory in ('classes', 'test-classes'):
            path = self.root / 'target' / directory
            path.mkdir()
            (path / 'Synthetic.class').write_bytes(b'Synthetic, not loadable Java bytecode')
        (self.root / 'target/dsl-doris-compiler.jar').write_bytes(b'Synthetic, never executed JAR')
        self.fresh_xml = True
        self.cleanup_fail = False
        self.source_identity_changed = False
        self.mutate_source = False
        self.secret_exception = False
        self.secret_log = False
        self.observed_secrets = []
        self.maven_calls = 0
        outer = self

        class FakeDoris:
            query_port, fe_http_port, be_http_port = 9030, 8030, 8040

            def query(self, sql):
                sql = sql.strip()
                if sql.startswith('SELECT * FROM newzl.data_snapshot_registry'):
                    return []
                if sql.startswith("SELECT 'basic',COUNT"):
                    rows = '19' if outer.source_identity_changed else '18'
                    return [('basic', rows, '2026-04-12', '2026-04-14'),
                            ('extension', '18', '2026-04-12', '2026-04-14'), ('code', '6', 'NULL', 'NULL')]
                if sql.startswith('SELECT TABLE_NAME,SHA2'):
                    return [('v_hsj_stock_hq_basic', 'synthetic-view-hash')]
                if sql.startswith('SELECT') and 'dsl_executor_fixture_' in sql and 'COUNT(*)' in sql:
                    return [('18', '18', '6', '0', '0', '18')]
                if sql.startswith('DROP USER') and outer.cleanup_fail:
                    raise RuntimeError('Injected fixture user cleanup failure')
                if sql.startswith(('SHOW ALL GRANTS', 'SHOW DATABASES LIKE')):
                    return []
                if sql.startswith(('CREATE ', 'INSERT ', 'ANALYZE ', 'DROP ', 'GRANT ')):
                    return []
                raise AssertionError('Unexpected mocked SQL boundary')

        self.client = FakeDoris()

    def tearDown(self):
        self.temp.cleanup()

    def write_fresh_reports(self):
        for name, methods in REQUIRED_CASES.items():
            self.write_suite(name, [{'name': method, 'status': 'PASS', 'classname': name} for method in methods])
            # Explicit fake freshness, not an assertion that any real test ran.
            timestamp = time.time_ns() + 1000000
            os.utime(self.report_file(name), ns=(timestamp, timestamp))

    def fake_process(self, command, **kwargs):
        if command[0] == 'wsl.exe':
            return subprocess.CompletedProcess(command, 0, stdout='127.0.0.1\n', stderr='')
        if command[0] == 'java':
            return subprocess.CompletedProcess(command, 0, stdout='', stderr=' java.home = ' + str(self.root / 'fake-java') + '\n')
        if command[0] != str(self.maven):
            raise AssertionError('Unexpected process; actual Maven/Doris execution is forbidden')
        self.maven_calls += 1
        self.assertIn('-Dtest=DorisExplainIntegrationTest,DorisControlledExecutionIntegrationTest', command)
        environment = kwargs['env']
        self.observed_secrets = [environment['DORIS_JDBC_PASSWORD'], environment['DORIS_WRITER_PASSWORD'], environment['DSL_FIXTURE_TOKEN']]
        if self.secret_log:
            kwargs['stdout'].write(('Injected log ' + ' '.join(self.observed_secrets)).encode('utf-8'))
        if self.secret_exception:
            raise RuntimeError('Injected exception ' + ' '.join(self.observed_secrets))
        if self.fresh_xml:
            self.write_fresh_reports()
        if self.mutate_source:
            with self.java_source.open('ab') as stream:
                stream.write(b'\n// changed during synthetic run')
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

    def call_main(self):
        with patch.object(run_wsl_integration, 'ROOT', self.root), \
             patch.object(run_wsl_integration, 'verify_test_environment', return_value=None), \
             patch.object(run_wsl_integration, 'WslDoris', return_value=self.client), \
             patch.object(run_wsl_integration.subprocess, 'run', side_effect=self.fake_process), \
             patch.object(run_wsl_integration.subprocess, 'Popen', side_effect=AssertionError('No real processes allowed')), \
             contextlib.redirect_stdout(io.StringIO()):
            return run_wsl_integration.main(['--junit-only', '--distribution', 'synthetic-not-real',
                '--maven', str(self.maven), '--report-dir', str(self.output)])

    def final_report(self):
        return json.loads((self.output / 'integration-result.json').read_text('utf-8'))

    def test_exact_eight_success_reaches_final_pass_without_record_parameter_clash(self):
        self.assertEqual(0, self.call_main())
        report = self.final_report()
        self.assertEqual(('PASS', 'DONE'), (report['status'], report['fixtureCleanup']))
        self.assertEqual((8, 8, 0), (report['requiredJunit']['tests'], report['requiredJunit']['passed'], report['requiredJunit']['skipped']))
        self.assertEqual(1, self.maven_calls)

    def test_fixture_cleanup_failure_overrides_success_and_return_zero(self):
        self.cleanup_fail = True
        with self.assertRaises(RuntimeError):
            self.call_main()
        report = self.final_report()
        self.assertEqual(('FAIL', 'FAILED'), (report['status'], report['fixtureCleanup']))
        self.assertTrue(report['cleanupErrors'])
        self.assertEqual('PASS', report['requiredJunit']['status'])
        self.assertEqual(1, self.maven_calls)

    def test_original_source_identity_change_cannot_pass(self):
        real_fake_process = self.fake_process

        def mutate_source_identity(command, **kwargs):
            result = real_fake_process(command, **kwargs)
            if command[0] == str(self.maven):
                self.source_identity_changed = True
            return result

        with patch.object(self, 'fake_process', side_effect=mutate_source_identity):
            with self.assertRaises(RuntimeError):
                self.call_main()
        self.assertEqual(('FAIL', 'FAILED'), (self.final_report()['status'], self.final_report()['fixtureCleanup']))
        self.assertEqual('PASS', self.final_report()['requiredJunit']['status'])
        self.assertEqual(1, self.maven_calls)

    def test_old_successful_xml_cannot_be_reused_as_a_new_pass(self):
        self.write_fresh_reports()
        for name in REQUIRED_CASES:
            os.utime(self.report_file(name), ns=(1000000000, 1000000000))
        self.fresh_xml = False
        with self.assertRaises(RuntimeError):
            self.call_main()
        self.assertEqual('FAIL', self.final_report()['status'])
        self.assertEqual(1, self.maven_calls)

    def test_source_changed_during_mocked_execution_cannot_pass(self):
        self.mutate_source = True
        with self.assertRaises(Exception):
            self.call_main()
        self.assertEqual('FAIL', self.final_report()['status'])
        self.assertEqual('PASS', self.final_report()['requiredJunit']['status'])
        self.assertEqual(1, self.maven_calls)

    def test_exception_trace_and_final_report_do_not_expose_fixture_secrets(self):
        self.secret_exception = True
        with self.assertRaises(Exception) as caught:
            self.call_main()
        exception_text = ''.join(traceback.format_exception(caught.exception))
        report_text = json.dumps(self.final_report())
        self.assertEqual(3, len(self.observed_secrets))
        self.assertIn('[REDACTED]', exception_text)
        for secret in self.observed_secrets:
            self.assertNotIn(secret, exception_text)
            self.assertNotIn(secret, report_text)

    def test_raw_process_log_is_redacted_before_final_evidence(self):
        self.secret_log = True
        self.assertEqual(0, self.call_main())
        log = (self.output / 'unified-integration.log').read_text('utf-8')
        for secret in self.observed_secrets:
            self.assertNotIn(secret, log)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({'name': test.id(), 'status': 'PASS'})

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.records.append({'name': test.id(), 'status': 'FAIL',
                             'error': ''.join(traceback.format_exception(*error))})

    def addError(self, test, error):
        super().addError(test, error)
        self.records.append({'name': test.id(), 'status': 'ERROR',
                             'error': ''.join(traceback.format_exception(*error))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New JSON report; existing evidence is never overwritten')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('--output must be a new file')
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    with Path(run_wsl_integration.__file__).open('rb') as source:
        implementation_hash = hashlib.file_digest(source, 'sha256').hexdigest()
    report = {
        'status': 'PASS' if result.wasSuccessful() else 'FAIL',
        'purpose': 'OFFLINE_EXACT_EIGHT_JUNIT_REPORT_CONTRACTS',
        'officialAcceptance': False, 'dorisExecuted': False, 'mavenExecuted': False,
        'timestampUtc': datetime.now(timezone.utc).isoformat(),
        'total': result.testsRun,
        'passed': sum(item['status'] == 'PASS' for item in result.records),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'elapsedMs': round((time.perf_counter() - started) * 1000, 3),
        'implementationSha256': implementation_hash, 'checks': result.records,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(str(args.output.resolve()))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
