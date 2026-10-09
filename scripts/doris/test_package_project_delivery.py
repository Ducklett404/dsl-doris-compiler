"""Portable integrity, freshness, secret and version binding tests for delivery packages."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import package_project_delivery as delivery


class PackageDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.source = self.root / "src/main/java/Main.java"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("class Main {}\n", encoding="utf-8")
        (self.root / "README.md").write_text("Project\n", encoding="utf-8")
        self.jar = self.root / "final.jar"
        self.jar.write_bytes(b"fixture jar bytes")
        self.evidence = self.base / "run"
        self.evidence.mkdir()
        self.summary = {"formatVersion": "project-acceptance-v1", "status": "PASS_OFFLINE_REAL_NOT_RUN", "officialAcceptanceEligible": False,
                        "identity": {"gitCommit": "a" * 40, "sourceSha256": "b" * 64,
                                     "compilerJarSha256": delivery.digest(self.jar)},
                        "formalAcceptanceStatus": "NOT_RUN", "stages": []}
        for name in delivery.OFFLINE_STAGES:
            self.summary['stages'].append(self.make_stage(name))
        self.summary['stages'].extend(dict(name=name, status='NOT_RUN') for name in delivery.REAL_STAGES)
        self.write_summary()
        self.output = self.base / "delivery"
        self.git = patch.object(delivery, "git_identity", return_value=("a" * 40, ["README.md", "src/main/java/Main.java"], ["src/main/java/Main.java"]))
        self.hash = patch.object(delivery, "acceptance_source_hash", return_value="b" * 64)
        self.git.start()
        self.hash.start()
        self.addCleanup(self.git.stop)
        self.addCleanup(self.hash.stop)

    def write_summary(self):
        (self.evidence / "project-summary.json").write_text(json.dumps(self.summary), encoding="utf-8")

    def make_stage(self, name, status='PASS', attempt=1):
        directory = f'{name}-attempt-{attempt:03}'
        target = self.evidence / directory; target.mkdir()
        report_name = ('source-validation-report.json' if name == 'sources' else
            'execution/result.json' if name in ('official-field-matrix', 'official-combinations', 'official-rank-combinations', 'resource-stability') else
            'controlled-execution-gate.json' if name == 'strict-gates' else 'result.json')
        report = target / report_name; report.parent.mkdir(parents=True, exist_ok=True)
        machine = 'BLOCKED' if status == 'EXPECTED_BLOCKED' else 'PROJECT_READY_WITH_LIMITATIONS' if name == 'sources' else status
        payload = dict(status=machine)
        if name == 'resource-stability':
            payload.update(timeoutStatus='PASS_REAL_JDBC_CONTROL', restartStatus='PASS_PROCESS_RESTART_HOST_CACHE_RETAINED')
        report.write_text(json.dumps(payload), encoding='utf-8')
        return dict(name=name, status=status, directory=directory, exitCode=3 if status == 'EXPECTED_BLOCKED' else 1 if status == 'FAIL' else 0,
                    machineStatus=machine, artifactHashes={report_name: delivery.digest(report)})

    def build(self):
        return delivery.build_package(self.root, self.jar, self.evidence, self.output)

    def test_complete_archive_preserves_real_not_run_and_dirty_source(self):
        result = self.build()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["archiveChecked"])
        self.assertEqual(result["restoreExecution"], "NOT_RUN")
        manifest = json.loads((self.output / "delivery-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["evidenceStatus"], "PASS_OFFLINE_REAL_NOT_RUN")
        self.assertEqual(manifest["sourceState"], "WORKTREE_WITH_UNCOMMITTED_CHANGES")
        self.assertEqual(manifest["formalStatus"], "BLOCKED")
        with zipfile.ZipFile(self.output / "project-delivery.zip") as archive:
            restored = self.base / "restored"
            archive.extractall(restored)
        self.assertEqual(delivery.verify_package(restored)["status"], "PASS")

    def test_source_policy_excludes_caches_credentials_and_original_data(self):
        for name in [".env", "src/.env.local", "config/credentials.json", "src/target/huge.jar",
                     "scripts/__pycache__/test.pyc", "data/doris/runs/raw.csv", "src/main/resources/prices.csv",
                     ".tools/runtime.py", ".mvn-cache/plugin.jar", "reports/old/result.json"]:
            self.assertFalse(delivery.source_allowed(name), name)
        for name in ["scripts/doris/test.py", "config/acceptance/cases.json", "docs/runtime.md",
                     "data/doris/config/data-contract-v1.json", "data/doris/snapshots/version/manifest.json", "src/test/resources/fixture.csv"]:
            self.assertTrue(delivery.source_allowed(name), name)

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "do-not-overwrite"
        sentinel.write_text("retained", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "new output"):
            self.build()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "retained")

    def test_jar_identity_mismatch_rejected_before_output(self):
        self.jar.write_bytes(b"different jar")
        with self.assertRaisesRegex(ValueError, "JAR does not match"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_source_identity_mismatch_rejected_before_output(self):
        self.summary["identity"]["sourceSha256"] = "c" * 64
        self.write_summary()
        with self.assertRaisesRegex(ValueError, "Source tree"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_failed_or_missing_environment_run_not_packaged_as_pass(self):
        for status in ["FAIL", "NOT_RUN", "PASS"]:
            self.summary["status"] = status
            self.write_summary()
            with self.assertRaisesRegex(ValueError, "completed"):
                self.build()
        self.assertFalse(self.output.exists())

    def test_evidence_credential_rejected_without_value_in_error(self):
        secret = "not-a-real-password-but-must-be-rejected"
        (self.evidence / "leak.json").write_text(json.dumps({"password": secret}), encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            self.build()
        self.assertNotIn(secret, str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_evidence_rejects_environment_assignment_and_private_key(self):
        path = self.evidence / "leak.txt"
        for text in ["$env:DORIS_PASSWORD = 'secret-value'", "-----BEGIN PRIVATE KEY-----\nabc"]:
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.build()
        self.assertFalse(self.output.exists())

    def test_payload_mutation_is_detected(self):
        self.build()
        path = self.output / "payload/source/README.md"
        path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            delivery.verify_package(self.output)

    def test_unlisted_payload_is_detected(self):
        self.build()
        (self.output / "payload/extra.txt").write_text("not inventoried", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unlisted"):
            delivery.verify_package(self.output)

    def test_manifest_traversal_is_rejected(self):
        self.build()
        path = self.output / "delivery-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][0]["path"] = "../outside.txt"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsafe relative"):
            delivery.verify_package(self.output)
        with self.assertRaisesRegex(ValueError, "Unsafe relative"):
            delivery.safe_relative("..\\outside.txt")

    def test_archive_inventory_and_bytes_are_checked(self):
        self.build()
        archive = self.output / "project-delivery.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("payload/artifacts/dsl-doris-compiler.jar", b"corrupted")
        with self.assertRaisesRegex(ValueError, "Archive inventory"):
            delivery.verify_package(self.output)

    def test_completed_stage_result_tampering_is_rejected_before_output(self):
        stage = self.summary['stages'][0]
        path = self.evidence / stage['directory'] / 'result.json'
        path.write_text('{"status":"PASS","changed":true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'artifacts changed'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_recorded_stage_file_is_rejected(self):
        stage = self.summary['stages'][0]
        (self.evidence / stage['directory'] / 'result.json').unlink()
        with self.assertRaisesRegex(ValueError, 'artifacts changed'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_unlisted_stage_file_cannot_be_laundered_into_package_hashes(self):
        stage = self.summary['stages'][0]
        (self.evidence / stage['directory'] / 'new.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'artifacts changed'):
            self.build()

    def test_missing_or_incomplete_selected_stage_is_rejected(self):
        self.summary['stages'] = self.summary['stages'][1:]
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'incomplete selected'):
            self.build()

    def test_terminal_running_stage_is_rejected(self):
        self.summary['stages'][0]['status'] = 'RUNNING'
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'invalid acceptance stage'):
            self.build()

    def test_failed_attempt_before_latest_pass_is_retained_and_verified(self):
        old = self.summary['stages'][0]
        failed = self.make_stage(old['name'], 'FAIL', attempt=2)
        self.summary['stages'].insert(0, failed)
        self.write_summary()
        self.assertEqual(self.build()['status'], 'PASS')

    def test_latest_failure_invalidates_previous_pass(self):
        old = self.summary['stages'][0]
        self.summary['stages'].append(self.make_stage(old['name'], 'FAIL', attempt=2))
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'incomplete selected'):
            self.build()

    def test_only_exact_unified_format_and_terminal_states_accepted(self):
        for version, status in [('wrong', 'PASS_OFFLINE_REAL_NOT_RUN'), ('project-acceptance-v1', 'DIAGNOSTIC_PASS_FORMAL_BLOCKED'),
                                ('project-acceptance-v1', 'PASS_PROJECT_FORMAL_BLOCKED')]:
            self.summary.update(formatVersion=version, status=status)
            self.write_summary()
            with self.assertRaisesRegex(ValueError, 'completed unified'):
                self.build()

    def test_offline_summary_cannot_present_real_data_stages_as_passed(self):
        self.summary['stages'] = [s for s in self.summary['stages'] if s['name'] != 'native-fields']
        self.summary['stages'].append(self.make_stage('native-fields'))
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'NOT_RUN'):
            self.build()

    def test_real_delivery_requires_every_selected_stage_and_expected_formal_block(self):
        self.summary.update(status='PROJECT_PASS_FORMAL_BLOCKED', formalAcceptanceStatus='BLOCKED')
        self.summary['stages'] = self.summary['stages'][:len(delivery.OFFLINE_STAGES)]
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'incomplete selected'):
            self.build()
        for name in delivery.REAL_STAGES:
            self.summary['stages'].append(self.make_stage(name, 'EXPECTED_BLOCKED' if name == 'formal-gate' else 'PASS'))
        self.write_summary()
        self.assertEqual(self.build()['status'], 'PASS')

    def test_stage_paths_and_hashes_must_be_safe(self):
        stage = self.summary['stages'][0]
        stage['artifactHashes'] = {'../escape.json': 'a' * 64}
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'Unsafe relative'):
            self.build()
        stage['artifactHashes'] = {'result.json': 'not-a-sha256'}
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'Invalid completed'):
            self.build()

    def test_real_delivery_requires_executed_timeout_and_restart_proofs(self):
        self.summary.update(status='PROJECT_PASS_FORMAL_BLOCKED', formalAcceptanceStatus='BLOCKED')
        self.summary['stages'] = self.summary['stages'][:len(delivery.OFFLINE_STAGES)]
        for name in delivery.REAL_STAGES:
            self.summary['stages'].append(self.make_stage(name, 'EXPECTED_BLOCKED' if name == 'formal-gate' else 'PASS'))
        stage = next(s for s in self.summary['stages'] if s['name'] == 'resource-stability')
        path = self.evidence / stage['directory'] / 'execution/result.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for field in ['timeoutStatus', 'restartStatus']:
            payload = dict(original); payload[field] = 'NOT_RUN'
            path.write_text(json.dumps(payload), encoding='utf-8')
            stage['artifactHashes']['execution/result.json'] = delivery.digest(path)
            self.write_summary()
            with self.assertRaisesRegex(ValueError, 'Incomplete real timeout'):
                self.build()
            self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
