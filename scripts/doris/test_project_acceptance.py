"""Failure/resume contracts are tested with temporary files, not a real database."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_project_acceptance as acceptance
from run_project_acceptance import StageRunner, artifact_hashes, digest, reference_identity, source_digest, verify_certificate, verify_report, verify_raw_precheck
from archive_project_selftest import collect_junit
from configure_project_be_runtime import RUNTIME_TARGET


class AcceptanceContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project-route-contract-')
        self.root = Path(self.temp.name)
        self.folder = self.root / 'run'
        self.identity = dict(sourceSha256='a'*64, compilerJarSha256='b'*64, manifestSha256='c'*64)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, folder, report=None, exit_code=0):
        value = report if report is not None else dict(status='PASS', checks=[dict(status='PASS')], total=1, passed=1)
        # Values go to a JSON fixture; this command never builds or interpolates shell code.
        (folder / 'expected-report.json').write_text(json.dumps(value), encoding='utf-8')
        return [sys.executable, '-c',
                'import shutil,sys;shutil.copyfile(sys.argv[1],sys.argv[2]);sys.exit(int(sys.argv[3]))',
                str(folder/'expected-report.json'), str(folder/'result.json'), str(exit_code)]

    def test_automatic_sleep_prevention_is_scoped_and_does_not_keep_display_on(self):
        calls = []
        with acceptance.AutomaticSleepPrevention('nt', lambda flags: calls.append(flags) or 1) as evidence:
            self.assertEqual('ACTIVE_DURING_RUN', evidence['status'])
            self.assertFalse(evidence['displayRequired'])
            self.assertEqual([acceptance.ES_CONTINUOUS | acceptance.ES_SYSTEM_REQUIRED], calls)
        self.assertEqual([acceptance.ES_CONTINUOUS | acceptance.ES_SYSTEM_REQUIRED,
                          acceptance.ES_CONTINUOUS], calls)

    def test_automatic_sleep_prevention_releases_after_failure_without_suppressing_it(self):
        calls = []
        with self.assertRaisesRegex(ValueError, 'inside'):
            with acceptance.AutomaticSleepPrevention('nt', lambda flags: calls.append(flags) or 1):
                raise ValueError('inside')
        self.assertEqual(acceptance.ES_CONTINUOUS, calls[-1])

    def test_automatic_sleep_prevention_fails_closed_and_is_explicit_off_windows(self):
        with self.assertRaisesRegex(RuntimeError, 'acquire'):
            with acceptance.AutomaticSleepPrevention('nt', lambda flags: 0):
                self.fail('unreachable')
        with acceptance.AutomaticSleepPrevention('posix', lambda flags: self.fail('setter called')) as evidence:
            self.assertEqual(dict(status='NOT_APPLICABLE', mechanism='NON_WINDOWS'), evidence)

    def test_fresh_directory_protection(self):
        self.folder.mkdir()
        (self.folder/'keep.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'new output directory'):
            StageRunner(self.folder, self.identity)
        self.assertEqual('keep', (self.folder/'keep.txt').read_text())

    def test_successful_phase_is_reused_without_execution(self):
        run = StageRunner(self.folder, self.identity)
        phase = run.stage('first', self.command)
        resumed = StageRunner(self.folder, self.identity, True)
        with patch('run_project_acceptance.subprocess.run', side_effect=AssertionError('Do not run')):
            self.assertEqual(phase, resumed.stage('first', self.command))

    def test_failure_stops_and_next_attempt_retains_failure_evidence(self):
        run = StageRunner(self.folder, self.identity)
        with self.assertRaises(RuntimeError):
            run.stage('one', lambda f:self.command(f, exit_code=1))
        first = artifact_hashes(self.folder/'one-attempt-001')
        resumed = StageRunner(self.folder, self.identity, True)
        completed = resumed.stage('one', self.command)
        self.assertEqual('one-attempt-002', completed.name)
        self.assertEqual(first, artifact_hashes(self.folder/'one-attempt-001'))
        self.assertEqual(['FAIL','PASS'], [s['status'] for s in resumed.report['stages']])

    def test_exit_zero_with_failed_machine_result_is_failure(self):
        run = StageRunner(self.folder, self.identity)
        with self.assertRaisesRegex(ValueError, 'machine status'):
            run.stage('one', lambda f:self.command(f,dict(status='FAIL')))
        self.assertEqual('FAIL', run.report['stages'][0]['status'])

    def test_correct_report_with_bad_exit_is_failure(self):
        run = StageRunner(self.folder, self.identity)
        with self.assertRaises(RuntimeError):
            run.stage('one', lambda f:self.command(f,exit_code=3))

    def test_expected_blocked_requires_its_own_exit_code_and_null_denominator(self):
        run = StageRunner(self.folder, self.identity)
        run.stage('formal', lambda f:self.command(f,dict(status='BLOCKED',cases=[],overall=dict(accuracy=None)),3),
                  expected=('BLOCKED',),exit_codes=(3,),formal_blocked=True)
        self.assertEqual('EXPECTED_BLOCKED',run.report['stages'][0]['status'])
        for value in (dict(status='BLOCKED',cases=[dict(id='fake')],overall=dict(accuracy=None)),
                      dict(status='BLOCKED',cases=[],overall=dict(accuracy=1))):
            with self.assertRaises(ValueError):verify_report(value,('BLOCKED',),True)

    def test_negative_cleanup_and_nested_checks_never_pass(self):
        for value in (dict(status='PASS',cleanup='FAILED'),dict(status='PASS',fixtureCleanup='FAILED'),
                      dict(status='PASS',cleanupErrors=['DROP failed']),dict(status='PASS',fatalError='bad'),
                      dict(status='PASS',checks=[dict(status='FAIL')]),dict(status='PASS',checks=[dict(status='NOT_RUN')]),
                      dict(status='PASS',executions=[dict(status='PASS',checks=dict(rowsEqual=False))]),
                      dict(status='PASS',passed=1,total=2)):
            with self.subTest(value=value),self.assertRaises(ValueError):verify_report(value)

    def test_changed_identity_refuses_resume(self):
        StageRunner(self.folder,self.identity)
        for field in ('sourceSha256','compilerJarSha256','manifestSha256'):
            altered=dict(self.identity);altered[field]='d'*64
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Resume refused'):
                StageRunner(self.folder,altered,True)

    def test_changed_result_file_refuses_resume(self):
        run=StageRunner(self.folder,self.identity)
        phase=run.stage('one',self.command)
        (phase/'result.json').write_text('{"status":"PASS","forged":true}')
        resumed=StageRunner(self.folder,self.identity,True)
        with self.assertRaisesRegex(ValueError,'artifacts changed'):resumed.stage('one',self.command)

    def test_deleted_or_added_artifact_refuses_resume(self):
        run=StageRunner(self.folder,self.identity)
        phase=run.stage('one',self.command)
        (phase/'extra.txt').write_text('Changed evidence')
        resumed=StageRunner(self.folder,self.identity,True)
        with self.assertRaisesRegex(ValueError,'artifacts changed'):resumed.stage('one',self.command)

    def test_timeout_preserves_failure_summary(self):
        run=StageRunner(self.folder,self.identity)
        with patch('run_project_acceptance.subprocess.run',side_effect=subprocess.TimeoutExpired('test',1)):
            with self.assertRaises(subprocess.TimeoutExpired):run.stage('one',self.command)
        self.assertEqual('FAIL',json.loads((self.folder/'project-summary.json').read_text())['stages'][0]['status'])

    def certificate(self, age=0):
        folder=self.root/'sources';folder.mkdir(exist_ok=True)
        cert=dict(status='PROJECT_READY_WITH_LIMITATIONS',definitionAuthority='PROJECT_INTERNAL',
                  manifestSha256=self.identity['manifestSha256'],sources={k:dict(status='PROJECT_READY') for k in ('basic','extension','code')})
        path=folder/'project-validation.json';path.write_text(json.dumps(cert))
        proof=dict(status='PROJECT_READY_WITH_LIMITATIONS',officialRegistryUnchanged=True,
                   certificateSha256=digest(path),jarSha256=self.identity['compilerJarSha256'],
                   manifestSha256=self.identity['manifestSha256'],
                   completedAtUtc=(datetime.now(timezone.utc)-timedelta(hours=age)).isoformat())
        (folder/'source-validation-report.json').write_text(json.dumps(proof))
        return folder

    def test_fresh_certificate_passes(self):
        folder=self.certificate()
        self.assertEqual(digest(folder/'project-validation.json'),verify_certificate(folder,self.identity))

    def test_expired_future_and_undated_certificates_rejected(self):
        for age in (25,-1):
            with self.subTest(age=age),self.assertRaisesRegex(ValueError,'expired or future'):
                verify_certificate(self.certificate(age),self.identity)
        folder=self.certificate();proof=json.loads((folder/'source-validation-report.json').read_text())
        proof['completedAtUtc']='2026-10-05T01:00:00'
        (folder/'source-validation-report.json').write_text(json.dumps(proof))
        with self.assertRaisesRegex(ValueError,'timezone'):verify_certificate(folder,self.identity)

    def test_corrupt_certificate_rejected(self):
        folder=self.certificate();path=folder/'project-validation.json'
        path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'damaged'):verify_certificate(folder,self.identity)

    def test_wrong_jar_manifest_and_blocked_source_rejected(self):
        folder=self.certificate()
        for field in ('compilerJarSha256','manifestSha256'):
            altered=dict(self.identity);altered[field]='e'*64
            with self.subTest(field=field),self.assertRaises(ValueError):verify_certificate(folder,altered)
        cert=json.loads((folder/'project-validation.json').read_text());cert['sources']['extension']['status']='BLOCKED'
        (folder/'project-validation.json').write_text(json.dumps(cert))
        proof=json.loads((folder/'source-validation-report.json').read_text());proof['certificateSha256']=digest(folder/'project-validation.json')
        (folder/'source-validation-report.json').write_text(json.dumps(proof))
        with self.assertRaisesRegex(ValueError,'all three'):verify_certificate(folder,self.identity)

    def test_source_digest_changes_with_source_not_with_generated_reports(self):
        (self.root/'src').mkdir();source=self.root/'src/Example.java';source.write_text('one')
        original=source_digest(self.root)
        (self.root/'reports').mkdir();(self.root/'reports/report.json').write_text('generated')
        self.assertEqual(original,source_digest(self.root))
        source.write_text('two');self.assertNotEqual(original,source_digest(self.root))

    def test_test_vector_csv_is_part_of_source_identity(self):
        (self.root/'src/test/resources').mkdir(parents=True)
        fixture=self.root/'src/test/resources/quotes.csv';fixture.write_text('one')
        original=source_digest(self.root);fixture.write_text('two')
        self.assertNotEqual(original,source_digest(self.root))

    def test_not_run_is_explicit_and_not_a_passing_stage(self):
        run=StageRunner(self.folder,self.identity)
        run.not_run('real','No Doris');run.not_run('real','No Doris')
        self.assertEqual(1,len(run.report['stages']))
        self.assertEqual('NOT_RUN',run.report['stages'][0]['status'])
        self.assertIn('NOT_RUN 不计为通过',(self.folder/'REPORT.md').read_text(encoding='utf-8'))

    def test_replaced_raw_reference_at_same_path_refuses_resume(self):
        reference=self.root/'raw.duckdb';reference.write_bytes(b'original raw rows')
        original=dict(self.identity,rawReference=reference_identity(reference))
        StageRunner(self.folder,original)
        reference.write_bytes(b'replaced raw rows')
        changed=dict(self.identity,rawReference=reference_identity(reference))
        self.assertNotEqual(original['rawReference'],changed['rawReference'])
        with self.assertRaisesRegex(ValueError,'reference database changed'):
            StageRunner(self.folder,changed,True)

    def test_reference_wal_and_mid_run_change_are_visible(self):
        reference=self.root/'raw.duckdb';reference.write_bytes(b'closed reference')
        original=reference_identity(reference)
        self.assertFalse(original['pendingWal'])
        Path(str(reference)+'.wal').write_bytes(b'new rows not in the main file')
        self.assertTrue(reference_identity(reference)['pendingWal'])
        reference.write_bytes(b'different content')
        self.assertNotEqual(original,reference_identity(reference))

    def test_junit_archive_excludes_old_suites_without_deleting_them(self):
        folder=self.root/'junit';folder.mkdir()
        xml='<testsuite name="fixture" tests="1" failures="0" errors="0" skipped="0"><testcase name="one"/></testsuite>'
        old=folder/'TEST-old.xml';old.write_text(xml);os.utime(old,(100,100))
        current=folder/'TEST-current.xml';current.write_text(xml);os.utime(current,(1000,1000))
        report=collect_junit(folder,999)
        self.assertEqual(1,report['tests'])
        self.assertEqual(['TEST-old.xml'],report['ignoredStaleSuiteFiles'])
        self.assertTrue(old.exists())

    def test_stability_not_run_substeps_cannot_be_a_complete_pass(self):
        proof=dict(status='PASS',timeoutStatus='PASS_REAL_JDBC_CONTROL',
                   restartStatus='PASS_PROCESS_RESTART_HOST_CACHE_RETAINED')
        verify_report(proof)
        for field in ('timeoutStatus','restartStatus'):
            changed=dict(proof);changed[field]='NOT_RUN'
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'stability acceptance'):
                verify_report(changed)

    def test_resource_evidence_cannot_omit_timeout_restart_or_requested_restart(self):
        proof = dict(status='PASS', purpose='PROJECT_FINAL_COMBINATION_RESOURCE_STABILITY',
                     timeoutStatus='PASS_REAL_JDBC_CONTROL', restartStatus='PASS_PROCESS_RESTART_HOST_CACHE_RETAINED',
                     restartRequested=True)
        verify_report(proof)
        for field in ('timeoutStatus', 'restartStatus', 'restartRequested'):
            changed = dict(proof)
            del changed[field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'stability acceptance'):
                verify_report(changed)
        changed = dict(proof)
        del changed['timeoutStatus']
        del changed['restartStatus']
        with self.assertRaisesRegex(ValueError, 'stability acceptance'):
            verify_report(changed)

    def test_summary_atomic_replace_retries_transient_permission_error(self):
        run=StageRunner(self.folder,self.identity)
        summary=self.folder/'project-summary.json'
        pending=self.folder/'project-summary.pending.json'
        old_summary=summary.read_bytes()
        run.report['status']='FAIL'
        original_replace=Path.replace
        attempts=[]
        def temporary_denial(source,destination):
            self.assertEqual(pending,source)
            self.assertEqual(summary,destination)
            attempts.append(source)
            if len(attempts)<=2:
                # A denied atomic replace must not truncate or partially write
                # the existing report while readers have it open on Windows.
                self.assertEqual(old_summary,summary.read_bytes())
                self.assertEqual(run.report,json.loads(pending.read_text(encoding='utf-8')))
                raise PermissionError(5,'Access is denied')
            return original_replace(source,destination)
        with patch('run_project_acceptance.Path.replace',autospec=True,side_effect=temporary_denial), \
             patch('run_project_acceptance.time.sleep') as sleep:
            run.save()
        self.assertEqual(3,len(attempts))
        self.assertEqual(2,sleep.call_count)
        self.assertTrue(all(call.args==(.05,) for call in sleep.call_args_list))
        self.assertEqual(run.report,json.loads(summary.read_text(encoding='utf-8')))
        self.assertFalse(pending.exists())
        self.assertIn('`FAIL`',(self.folder/'REPORT.md').read_text(encoding='utf-8'))

    def test_summary_permanent_permission_error_is_bounded_and_preserves_evidence(self):
        run=StageRunner(self.folder,self.identity)
        summary=self.folder/'project-summary.json'
        pending=self.folder/'project-summary.pending.json'
        old_summary=summary.read_bytes()
        old_markdown=(self.folder/'REPORT.md').read_bytes()
        run.report['status']='FAIL'
        error=PermissionError(5,'Access is denied')
        with patch('run_project_acceptance.Path.replace',autospec=True,side_effect=error) as replace, \
             patch('run_project_acceptance.time.sleep') as sleep:
            with self.assertRaises(PermissionError) as raised:
                run.save()
        self.assertIs(error,raised.exception)
        self.assertEqual(20,replace.call_count)
        self.assertLessEqual(sleep.call_count,20)
        self.assertTrue(all(call.args==(.05,) for call in sleep.call_args_list))
        self.assertEqual(old_summary,summary.read_bytes())
        self.assertEqual(old_markdown,(self.folder/'REPORT.md').read_bytes())
        self.assertEqual(run.report,json.loads(pending.read_text(encoding='utf-8')))
        self.assertTrue(all(call.args==(pending,summary) for call in replace.call_args_list))

    def test_summary_nonpermission_error_is_not_retried_or_overwritten(self):
        run=StageRunner(self.folder,self.identity)
        summary=self.folder/'project-summary.json'
        old_summary=summary.read_bytes()
        old_markdown=(self.folder/'REPORT.md').read_bytes()
        run.report['status']='FAIL'
        error=OSError(28,'No space left on device')
        with patch('run_project_acceptance.Path.replace',autospec=True,side_effect=error) as replace, \
             patch('run_project_acceptance.time.sleep') as sleep:
            with self.assertRaises(OSError) as raised:
                run.save()
        self.assertIs(error,raised.exception)
        self.assertEqual(1,replace.call_count)
        sleep.assert_not_called()
        self.assertEqual(old_summary,summary.read_bytes())
        self.assertEqual(old_markdown,(self.folder/'REPORT.md').read_bytes())
        self.assertEqual(run.report,json.loads((self.folder/'project-summary.pending.json').read_text(encoding='utf-8')))

    def raw_proof(self, count=94, oracle=None, folder=None):
        folder = folder or self.root / 'raw-proof'
        execution = folder / 'execution'
        execution.mkdir(parents=True, exist_ok=True)
        matrix = [dict(name='case-' + str(i), dsl='fixed-' + str(i)) for i in range(count)]
        matrix_path = folder / 'frozen-matrix.json'
        for path in (matrix_path, execution / 'matrix.json'):
            path.write_text(json.dumps(matrix), encoding='utf-8')
        flags = {name: True for name in ('keysEqual', 'inputsEqual', 'samplesEqual', 'observedEqual',
            'missingExtensionEqual', 'coverageStatusEqual', 'completeResult', 'internalAuthority',
            'certificateEqual', 'resourcePolicyEqual')}
        limits = dict(queryTimeoutSeconds=10, maxEstimatedScanRows=100000000,
                      maxReturnRows=10000, maxExecutionMemoryBytes=2147483648)
        checks = ['strict-registry-empty', 'raw-reference-lock', 'http-started', 'sources-unchanged',
                  'environment-unchanged', 'artifacts-unchanged', 'field-oracle-unchanged']
        if oracle:
            checks.append('combination-oracle-unchanged')
        state = [[['basic', '13650347'], ['code', '5686'], ['ext', '6170822']], []]
        proof = dict(status='PASS', matrixScope='FULL_MATRIX', rounds=1,
            originalCaseNames=[c['name'] for c in matrix], passed=count, total=count,
            cleanup='DONE', cleanupErrors=[], sourceStateBefore=state, sourceStateAfter=deepcopy(state),
            environment=self.runtime_snapshot(),
            jarSha256=self.identity['compilerJarSha256'], certificateSha256='e' * 64,
            checks=[dict(name=n, status='PASS') for n in checks],
            executions=[dict(case=c['name'], round=1, httpStatus=200, status='PASS',
                             checks=deepcopy(flags), limits=deepcopy(limits)) for c in matrix])
        return proof, execution, matrix_path

    def runtime_snapshot(self):
        return dict(containerId='a' * 64, containerMemoryBytes=5368709120, containerNanoCpus=4000000000,
            beMemoryShare='60%', beRuntimeSettings=deepcopy(RUNTIME_TARGET), beConfigurationSha256='e' * 64,
            feRuntime=dict(profile='bounded-v1', mallocArenaMax=4, activeProcessorCount=4,
                heapInitialMiB=768, heapMaxMiB=768, feConfigurationSha256='f' * 64, entrypointSha256='d' * 64))

    def verify_raw(self, proof, execution, matrix, count=94, oracle=None):
        return verify_raw_precheck(proof, execution, matrix, count, self.identity, 'e' * 64, oracle)

    def test_complete_single_raw_round_passes_all_three_frozen_inventories(self):
        for count, oracle in ((94, None), (79, 'project_combination_reference'), (172, 'project_rank_reference')):
            proof, execution, matrix = self.raw_proof(count, oracle, self.root / str(count))
            self.verify_raw(proof, execution, matrix, count, oracle)
        self.assertEqual(345, sum(acceptance.RAW_PRECHECK_CONTRACT['caseCounts'].values()))
        self.assertFalse(acceptance.RAW_PRECHECK_CONTRACT['performanceSamples'])

    def test_raw_precheck_rejects_partial_duplicate_reordered_and_wrong_round_coverage(self):
        proof, execution, matrix = self.raw_proof()
        mutations = [dict(proof, executions=proof['executions'][:-1]), dict(proof, total=93, passed=93),
                     dict(proof, matrixScope='SINGLE_CASE_DIAGNOSTIC'), dict(proof, rounds=30),
                     dict(proof, rounds=True), dict(proof, originalCaseNames=['fake'])]
        for kind in ('duplicate', 'reordered', 'wrong-round', 'http-failure'):
            changed = deepcopy(proof)
            if kind == 'duplicate':
                changed['executions'][-1] = changed['executions'][0]
            elif kind == 'reordered':
                changed['executions'].reverse()
            elif kind == 'wrong-round':
                changed['executions'][0]['round'] = 2
            else:
                changed['executions'][0]['httpStatus'] = 502
            mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed.get('matrixScope')), self.assertRaises(ValueError):
                self.verify_raw(changed, execution, matrix)

    def test_raw_precheck_rejects_changed_matrix_and_wrong_inventory_size(self):
        proof, execution, matrix = self.raw_proof()
        with self.assertRaisesRegex(ValueError, 'complete frozen matrix'):
            self.verify_raw(proof, execution, matrix, 79)
        copied = json.loads((execution / 'matrix.json').read_text())
        copied[0]['dsl'] = 'changed expression'
        (execution / 'matrix.json').write_text(json.dumps(copied))
        with self.assertRaisesRegex(ValueError, 'matrix changed'):
            self.verify_raw(proof, execution, matrix)

    def test_raw_precheck_requires_positive_source_environment_and_cleanup_evidence(self):
        proof, execution, matrix = self.raw_proof()
        for changes in (dict(cleanup='NOT_STARTED'), dict(cleanupErrors=['drop failed']),
                        dict(sourceStateBefore=None), dict(sourceStateBefore=True), dict(sourceStateAfter=None),
                        dict(environment={}), dict(environment=None)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.verify_raw(dict(proof, **changes), execution, matrix)
        changed = deepcopy(proof)
        changed['sourceStateAfter'][0][0][1] = 'changed'
        with self.assertRaises(ValueError):
            self.verify_raw(changed, execution, matrix)
        changed = deepcopy(proof)
        changed['sourceStateBefore'][1].append(['wrongly-validated'])
        changed['sourceStateAfter'] = deepcopy(changed['sourceStateBefore'])
        with self.assertRaises(ValueError):
            self.verify_raw(changed, execution, matrix)

    def test_raw_precheck_requires_every_preservation_check_and_unique_names(self):
        proof, execution, matrix = self.raw_proof(79, 'project_combination_reference')
        for check in proof['checks']:
            changed = deepcopy(proof)
            changed['checks'] = [c for c in changed['checks'] if c['name'] != check['name']]
            with self.subTest(missing=check['name']), self.assertRaises(ValueError):
                self.verify_raw(changed, execution, matrix, 79, 'project_combination_reference')
        changed = deepcopy(proof)
        changed['checks'].append(changed['checks'][0])
        with self.assertRaises(ValueError):
            self.verify_raw(changed, execution, matrix, 79, 'project_combination_reference')

    def test_raw_precheck_requires_exact_correctness_flags_and_original_resource_budgets(self):
        proof, execution, matrix = self.raw_proof()
        for key in proof['executions'][0]['checks']:
            for value in (False, 1, None):
                changed = deepcopy(proof)
                changed['executions'][0]['checks'][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.verify_raw(changed, execution, matrix)
            changed = deepcopy(proof)
            del changed['executions'][0]['checks'][key]
            with self.assertRaises(ValueError):
                self.verify_raw(changed, execution, matrix)
        for key in proof['executions'][0]['limits']:
            changed = deepcopy(proof)
            changed['executions'][0]['limits'][key] *= 2
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify_raw(changed, execution, matrix)

    def test_raw_precheck_binds_compiler_and_certificate_identity(self):
        proof, execution, matrix = self.raw_proof()
        for key in ('jarSha256', 'certificateSha256'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'identity differs'):
                self.verify_raw(dict(proof, **{key: 'f' * 64}), execution, matrix)

    def test_stage_custom_validator_failure_is_recorded_before_passing(self):
        run = StageRunner(self.folder, self.identity)
        def reject(proof, folder):
            self.assertEqual(self.folder / 'raw-attempt-001', folder)
            self.assertEqual('PASS', proof['status'])
            raise ValueError('Missing complete raw evidence')
        with self.assertRaisesRegex(ValueError, 'complete raw evidence'):
            run.stage('raw', self.command, proof_validator=reject)
        self.assertEqual('FAIL', run.report['stages'][0]['status'])

    def test_resume_revalidates_custom_raw_contract_without_reexecuting(self):
        run = StageRunner(self.folder, self.identity)
        run.stage('raw', self.command)
        resumed = StageRunner(self.folder, self.identity, True)
        with patch('run_project_acceptance.subprocess.run', side_effect=AssertionError('Do not run')):
            with self.assertRaisesRegex(ValueError, 'Raw precheck contract'):
                resumed.stage('raw', self.command, proof_validator=lambda proof, folder:
                              (_ for _ in ()).throw(ValueError('Raw precheck contract is incomplete')))

    def test_raw_contract_change_or_removal_refuses_resume(self):
        original = dict(self.identity, executionOptions=dict(rawPrecheck=deepcopy(acceptance.RAW_PRECHECK_CONTRACT)))
        StageRunner(self.folder, original)
        for contract in (None, dict(acceptance.RAW_PRECHECK_CONTRACT, rounds=2),
                         dict(acceptance.RAW_PRECHECK_CONTRACT, performanceSamples=True)):
            changed = deepcopy(original)
            changed['executionOptions']['rawPrecheck'] = contract
            with self.subTest(contract=contract), self.assertRaisesRegex(ValueError, 'Resume refused'):
                StageRunner(self.folder, changed, True)

    def mocked_main(self, *, fail_precheck=None, with_doris=True, environment='PASS', runtime_error=None,
                    resume=False, runtime_observed=None):
        """Exercise orchestration only: no Java, subprocess, WSL or database."""
        commands, calls = [], []
        counts = acceptance.RAW_PRECHECK_CONTRACT['caseCounts']
        portable_counts = dict(zip(('portable-fields', 'portable-combinations', 'portable-rank-combinations'), counts.values()))
        run_identity = dict(self.identity)
        def fake_stage(run, name, factory, **kwargs):
            calls.append(name)
            folder = run.folder / (name + '-attempt-001')
            folder.mkdir()
            command = factory(folder)
            commands.append((name, command))
            if name in portable_counts:
                self.raw_proof(portable_counts[name], folder=folder)
                (folder / 'matrix.json').write_text((folder / 'frozen-matrix.json').read_text())
            if name.startswith('raw-'):
                label = name.removeprefix('raw-').removesuffix('-precheck')
                count = counts[label]
                oracle = command[command.index('--oracle-module') + 1] if '--oracle-module' in command else None
                proof, execution, _ = self.raw_proof(count, oracle, folder)
                copied = json.loads(Path(command[command.index('--matrix') + 1]).read_text())
                (execution / 'matrix.json').write_text(json.dumps(copied))
                proof['certificateSha256'] = 'e' * 64
                if name == fail_precheck:
                    proof['executions'] = proof['executions'][:-1]
                (execution / 'result.json').write_text(json.dumps(proof))
                kwargs['proof_validator'](proof, folder)
            run.report['stages'].append(dict(name=name, status='PASS', directory=folder.name))
            return folder
        argv = ['runner', '--report-dir', str(self.folder), '--reference-database', str(self.root / 'raw.duckdb')]
        if with_doris:
            argv += ['--with-doris', '--restart']
        if resume:
            argv += ['--resume']
        def fake_digest(path):
            return run_identity['compilerJarSha256'] if Path(path).name == 'dsl-doris-compiler.jar' else 'e' * 64
        with patch.object(sys, 'argv', argv), patch.object(acceptance, 'identity', return_value=run_identity), \
             patch.object(acceptance, 'reference_identity', return_value=dict(enabled=with_doris)), \
             patch.object(acceptance, 'preflight', return_value=dict(status=environment, checks=[])), \
             patch.object(acceptance, 'verify_certificate', return_value='e' * 64), \
             patch.object(acceptance, 'capture_doris_environment',
                          return_value=runtime_observed or self.runtime_snapshot(), side_effect=runtime_error), \
             patch.object(acceptance, 'digest', side_effect=fake_digest), \
             patch.object(StageRunner, 'stage', autospec=True, side_effect=fake_stage), \
             patch.object(acceptance.subprocess, 'run', side_effect=AssertionError('No external execution')):
            code = acceptance.main()
        return code, calls, commands, json.loads((self.folder / 'project-summary.json').read_text())

    def test_all_three_raw_prechecks_precede_any_complete_30_round_matrix(self):
        code, calls, commands, summary = self.mocked_main()
        self.assertEqual(0, code)
        prechecks = ['raw-' + name + '-precheck' for name in acceptance.RAW_PRECHECK_CONTRACT['caseCounts']]
        self.assertGreater(calls.index(prechecks[0]), calls.index('native-rank-combinations'))
        self.assertLess(calls.index(prechecks[-1]), calls.index('official-field-matrix'))
        timed_count = 0
        for name, command in commands:
            if name in prechecks:
                self.assertEqual('1', command[command.index('--rounds') + 1])
                self.assertIn('--field-oracle', command)
                self.assertIn('--explain', command)
                self.assertEqual(str((self.root / 'raw.duckdb').resolve()), command[command.index('--reference-database') + 1])
                self.assertIn('sources-attempt-001', command[command.index('--certificate') + 1])
            if name in acceptance.RAW_PRECHECK_CONTRACT['caseCounts']:
                rounds = int(command[command.index('--rounds') + 1])
                self.assertEqual(30, rounds)
                timed_count += rounds * acceptance.RAW_PRECHECK_CONTRACT['caseCounts'][name]
            if name.endswith('-timings'):
                self.assertNotIn('raw-', command[command.index('--execution-dir') + 1])
        self.assertEqual(10350, timed_count)
        self.assertFalse(summary['identity']['executionOptions']['rawPrecheck']['performanceSamples'])
        self.assertEqual('ACTIVE_DURING_RUN',
                         summary['identity']['executionOptions']['automaticSleepPrevention']['status'])

    def test_failed_last_raw_precheck_prevents_all_complete_performance_matrices(self):
        code, calls, _, summary = self.mocked_main(fail_precheck='raw-official-rank-combinations-precheck')
        self.assertEqual(1, code)
        self.assertEqual('FAIL', summary['status'])
        self.assertTrue(all(name not in calls for name in acceptance.RAW_PRECHECK_CONTRACT['caseCounts']))
        self.assertNotIn('resource-stability', calls)

    def test_offline_and_unavailable_environments_explicitly_mark_raw_prechecks_not_run(self):
        code, calls, _, summary = self.mocked_main(with_doris=False)
        self.assertEqual(0, code)
        self.assertFalse(any(name.startswith('raw-') for name in calls))
        marked = {s['name']: s['status'] for s in summary['stages']}
        for name in acceptance.RAW_PRECHECK_CONTRACT['caseCounts']:
            self.assertEqual('NOT_RUN', marked['raw-' + name + '-precheck'])
        self.assertFalse(summary['identity']['executionOptions']['rawPrecheck']['enabled'])
        self.folder = self.root / 'unavailable'
        code, calls, _, summary = self.mocked_main(environment='NOT_RUN')
        self.assertEqual(2, code)
        self.assertEqual([], calls)
        marked = {s['name']: s['status'] for s in summary['stages']}
        for name in acceptance.RAW_PRECHECK_CONTRACT['caseCounts']:
            self.assertEqual('NOT_RUN', marked['raw-' + name + '-precheck'])

    def test_actual_runtime_is_bound_to_identity_and_missing_runtime_is_reported_not_run(self):
        code, _, _, summary = self.mocked_main()
        self.assertEqual(0, code)
        self.assertEqual(self.runtime_snapshot(), summary['identity']['dorisEnvironment'])
        self.folder = self.root / 'missing-runtime'
        code, calls, _, summary = self.mocked_main(runtime_error=OSError('sensitive transport detail'))
        self.assertEqual(2, code)
        self.assertEqual([], calls)
        self.assertEqual('NOT_RUN', summary['status'])
        preflight = json.loads((self.folder / 'environment-preflight.json').read_text())
        self.assertEqual('NOT_RUN', preflight['runtimeFreeze']['status'])
        self.assertNotIn('sensitive transport detail', json.dumps(preflight))

    def test_raw_precheck_environment_is_compared_to_frozen_identity_not_itself(self):
        proof, execution, matrix = self.raw_proof()
        identity = dict(self.identity, dorisEnvironment=self.runtime_snapshot())
        proof['environment']['containerNanoCpus'] = 2000000000
        with self.assertRaisesRegex(ValueError, 'frozen run environment'):
            verify_raw_precheck(proof, execution, matrix, 94, identity, 'e' * 64)

    def test_stage_live_environment_drift_stops_before_external_execution(self):
        frozen = self.runtime_snapshot()
        identity = dict(self.identity, dorisEnvironment=frozen)
        for key in frozen:
            folder = self.root / ('drift-' + key)
            changed = deepcopy(frozen)
            if key == 'beRuntimeSettings':
                changed[key]['num_cores'] = '2'
            elif isinstance(changed[key], int):
                changed[key] += 1
            else:
                changed[key] = 'changed'
            run = StageRunner(folder, identity, environment_probe=lambda: changed)
            with patch('run_project_acceptance.subprocess.run', side_effect=AssertionError('No command')):
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'environment changed'):
                    run.stage('native', self.command)
            self.assertEqual('FAIL', run.report['environmentChecks'][-1]['status'])
            self.assertEqual([], run.report['stages'])

    def test_stage_live_environment_after_drift_cannot_be_recorded_pass(self):
        frozen = self.runtime_snapshot()
        changed = dict(frozen, beMemoryShare='40%')
        run = StageRunner(self.folder, dict(self.identity, dorisEnvironment=frozen),
                          environment_probe=unittest.mock.Mock(side_effect=[frozen, changed]))
        with self.assertRaisesRegex(ValueError, 'environment changed'):
            run.stage('native', self.command)
        self.assertEqual('FAIL', run.report['stages'][0]['status'])
        self.assertEqual(['PASS', 'FAIL'], [c['status'] for c in run.report['environmentChecks']])

    def test_resume_live_environment_is_checked_before_reusing_complete_evidence(self):
        frozen = self.runtime_snapshot()
        identity = dict(self.identity, dorisEnvironment=frozen)
        run = StageRunner(self.folder, identity, environment_probe=lambda: frozen)
        run.stage('first', self.command)
        changed = dict(frozen, containerId='b' * 64)
        resumed = StageRunner(self.folder, identity, True, environment_probe=lambda: changed)
        with patch('run_project_acceptance.subprocess.run', side_effect=AssertionError('Do not run')):
            with self.assertRaisesRegex(ValueError, 'environment changed'):
                resumed.stage('first', self.command)
        self.assertEqual('PASS', resumed.report['stages'][0]['status'])
        self.assertEqual('FAIL', resumed.report['environmentChecks'][-1]['status'])

    def test_report_environment_requires_original_frozen_values_even_when_local_checks_pass(self):
        frozen = self.runtime_snapshot()
        for key in frozen:
            observed = deepcopy(frozen)
            if key == 'beRuntimeSettings':
                observed[key]['num_cores'] = '8'
            elif isinstance(observed[key], int):
                observed[key] += 1
            else:
                observed[key] = 'changed'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'frozen run environment'):
                acceptance.verify_environment_report(dict(environment=observed), frozen)
        # The resource runner has no ID field; outer actual stage boundaries
        # bind that ID independently while all five reported values must match.
        resource = {k: v for k, v in frozen.items() if k != 'containerId'}
        acceptance.verify_environment_report(dict(environment=resource), frozen)
        for key in resource:
            shortened = dict(resource)
            del shortened[key]
            with self.assertRaises(ValueError):
                acceptance.verify_environment_report(dict(environment=shortened), frozen)

    def test_main_resume_environment_change_refuses_without_overwriting_saved_summary(self):
        code, _, _, summary = self.mocked_main()
        self.assertEqual(0, code)
        saved = (self.folder / 'project-summary.json').read_bytes()
        changed = dict(self.runtime_snapshot(), containerNanoCpus=2000000000)
        code, calls, _, after = self.mocked_main(resume=True, runtime_observed=changed)
        self.assertEqual(1, code)
        self.assertEqual([], calls)
        self.assertEqual(saved, (self.folder / 'project-summary.json').read_bytes())
        refusals = list(self.folder.glob('resume-refusal-*.json'))
        self.assertEqual(1, len(refusals))
        proof = json.loads(refusals[0].read_text())
        self.assertEqual('FAIL', proof['status'])
        self.assertEqual(changed, proof['observedRuntime']['environment'])

    def test_main_resume_absent_environment_is_not_run_and_preserves_original_binding(self):
        code, _, _, summary = self.mocked_main()
        self.assertEqual(0, code)
        frozen = deepcopy(summary['identity']['dorisEnvironment'])
        code, calls, _, after = self.mocked_main(resume=True, runtime_error=OSError('not to be logged'))
        self.assertEqual(2, code)
        self.assertEqual([], calls)
        self.assertEqual('NOT_RUN', after['status'])
        self.assertEqual(frozen, after['identity']['dorisEnvironment'])
        self.assertNotIn('not to be logged', (self.folder / 'environment-preflight.json').read_text())

    def rsi_proof(self):
        pairs = [(f'rsi{n}-{op}-50', mode) for n in (5, 5000)
                 for op in ('=', '!=', '>', '>=', '<', '<=') for mode in ('project', 'reference')]
        source = dict(rows=[['basic', '1'], ['ext', '1'], ['code', '1']], formalRegistry=[])
        limits = [dict(case=name, mode=mode, actual=[], declared12PlaceExpected=[],
            exactRationalExpected=[['1', 'RL0001']] if i < 8 else [],
            declaredOutputMatches=True, exactKeysEqual=i >= 8,
            status='PRECISION_LIMIT_OBSERVED' if i < 8 else 'NO_THRESHOLD_DIFFERENCE')
            for i, (name, mode) in enumerate(pairs)]
        return dict(status='PASS_WITH_FINITE_PRECISION_LIMIT', passed=24, total=24,
            fixtureCleanup='DONE', cleanupErrors=[], sourceStateUnchanged=True, artifactsUnchanged=True,
            formalRegistryUnchanged=True, jarSha256=self.identity['compilerJarSha256'],
            declaredOutputType='DECIMAL(38,12)', notInfiniteRationalProof=True,
            notAllSignedBigintStrictComparisonProof=True, sourceStateBefore=source,
            sourceStateAfter=deepcopy(source), precisionLimitComparisons=8,
            checks=[dict(case=name, mode=mode, status='PASS', strictExactActual=[], strictExactExpected=[])
                    for name, mode in pairs], finitePrecisionLimitEvidence=limits,
            projections=[dict(n=n, mode=mode, decimalScale12=True, keysEqual=True, finiteOutputValuesEqual=True)
                         for n in (5, 5000) for mode in ('project', 'reference')])

    def test_rsi_precision_accepts_only_explicitly_limited_complete_native_evidence(self):
        acceptance.verify_rsi_precision(self.rsi_proof(), self.identity)
        with self.assertRaises(ValueError):
            acceptance.verify_rsi_precision(dict(self.rsi_proof(), status='PASS'), self.identity)

    def test_rsi_precision_requires_all_strict_cases_and_both_access_paths(self):
        for mutation in ('missing', 'duplicate', 'wrong-keys'):
            proof = self.rsi_proof()
            if mutation == 'missing':
                proof['checks'].pop()
            elif mutation == 'duplicate':
                proof['checks'][-1] = deepcopy(proof['checks'][0])
            else:
                proof['checks'][0]['strictExactActual'] = [['1', 'unexpected']]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                acceptance.verify_rsi_precision(proof, self.identity)

    def test_rsi_precision_limit_evidence_cannot_be_omitted_or_mislabeled_exact_pass(self):
        for mutation in ('missing', 'count', 'declared', 'exact-flag', 'status'):
            proof = self.rsi_proof()
            if mutation == 'missing':
                proof['finitePrecisionLimitEvidence'].pop()
            elif mutation == 'count':
                proof['precisionLimitComparisons'] = 0
            elif mutation == 'declared':
                proof['finitePrecisionLimitEvidence'][0]['declaredOutputMatches'] = False
            elif mutation == 'exact-flag':
                proof['finitePrecisionLimitEvidence'][0]['exactKeysEqual'] = True
            else:
                proof['finitePrecisionLimitEvidence'][0]['status'] = 'PASS'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                acceptance.verify_rsi_precision(proof, self.identity)

    def test_rsi_precision_native_projection_values_types_and_scope_are_required(self):
        for key in ('decimalScale12', 'keysEqual', 'finiteOutputValuesEqual'):
            proof = self.rsi_proof()
            proof['projections'][0][key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                acceptance.verify_rsi_precision(proof, self.identity)
        for key in ('notInfiniteRationalProof', 'notAllSignedBigintStrictComparisonProof'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                acceptance.verify_rsi_precision(dict(self.rsi_proof(), **{key: False}), self.identity)

    def test_rsi_precision_requires_current_jar_untouched_sources_and_successful_cleanup(self):
        for changes in (dict(jarSha256='f' * 64), dict(fixtureCleanup='FAILED'),
                        dict(sourceStateUnchanged=False), dict(artifactsUnchanged=False),
                        dict(formalRegistryUnchanged=False), dict(cleanupErrors=['failure'])):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                acceptance.verify_rsi_precision(dict(self.rsi_proof(), **changes), self.identity)
        proof = self.rsi_proof()
        proof['sourceStateAfter']['rows'][0][1] = 'changed'
        with self.assertRaises(ValueError):
            acceptance.verify_rsi_precision(proof, self.identity)

    def test_stage_unavailable_runtime_records_failure_and_redacts_transport_error(self):
        run = StageRunner(self.folder, dict(self.identity, dorisEnvironment=self.runtime_snapshot()),
            environment_probe=unittest.mock.Mock(side_effect=OSError('private connection secret')))
        with self.assertRaisesRegex(ValueError, 'runtime unavailable'):
            run.stage('native', self.command)
        self.assertEqual([], run.report['stages'])
        self.assertEqual('FAIL', run.report['environmentChecks'][-1]['status'])
        self.assertNotIn('private connection secret', json.dumps(run.report))


if __name__=='__main__':unittest.main()
