"""Safe reference rebuild regressions using synthetic, self-cleaning CSV fixtures."""
from __future__ import annotations

import argparse
import contextlib
import copy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch

import duckdb

from audit_official_data import NAMES, ddl_columns, digest, run_audit
import build_reference_duckdb


class ReferenceRebuildContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reference-rebuild-selftest-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'synthetic-source'
        self.source.mkdir()
        self.database = self.root / 'reference.duckdb'
        self.output = self.root / 'new-report'
        self.manifest_path = self.root / 'manifest.json'
        self.schema = ddl_columns()
        self.rows = {}
        for name in NAMES:
            table_rows = []
            for market, code, security_name in ((1, '000001', '中文证券,甲'),
                                                (103, '009999', '名称"乙')):
                row = {field: '' for field in self.schema[name]}
                row.update(mktcode=str(market), tgtcode=code)
                if name == NAMES[0]:
                    row.update(name=security_name, stFlag='false')
                else:
                    row['bizdate'] = '2026-04-14'
                if name == NAMES[1]:
                    row.update(openPx='20000', highPx='22000', lowPx='18000', closePx='20000',
                               volume='100', turnover='20000', qfqMulti='1', qfqAdd='0',
                               hfqMulti='1', hfqAdd='0', firstLimitUpTime='2026-04-14 09:30:01')
                if name == NAMES[2]:
                    row.update(ZJLXMainNetTur='-10000', ZJLXMainNetTurInDays='-999999')
                table_rows.append(row)
            self.rows[name] = table_rows
        self.write_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def write_fixture(self):
        self.manifest = {'snapshotId': 'synthetic-reference-v1', 'contractVersion': 'test-only', 'files': {}}
        for name in NAMES:
            folder = self.source / ('合成-' + name)
            folder.mkdir(exist_ok=True)
            path = folder / (name + '.csv')
            header = list(self.schema[name])
            rows = self.rows[name]
            with path.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=header)
                writer.writeheader()
                writer.writerows(rows)
            self.manifest['files'][name] = {
                'relativePath': path.relative_to(self.source).as_posix(),
                'header': header, 'rows': len(rows), 'bytes': path.stat().st_size,
                'sha256': digest(path),
                'nullCounts': {field: sum(row[field] == '' for row in rows) for field in header},
                'sentinelMinus999999Counts': {
                    field: sum(row[field] == '-999999' for row in rows)
                    for field in header if any(row[field] == '-999999' for row in rows)},
                'dateMin': None if name == NAMES[0] else min(row['bizdate'] for row in rows),
                'dateMax': None if name == NAMES[0] else max(row['bizdate'] for row in rows),
            }
        self.save_manifest()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def source_file(self, name=NAMES[0]):
        return self.source / self.manifest['files'][name]['relativePath']

    def source_bytes(self):
        return {str(path.relative_to(self.source)): path.read_bytes()
                for path in self.source.rglob('*') if path.is_file()}

    def build(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return build_reference_duckdb.build_reference(
                self.source, self.manifest_path, self.database, self.output, **kwargs)

    def assert_blocked(self, **kwargs):
        result = None
        try:
            result = self.build(**kwargs)
        except (ValueError, FileExistsError, RuntimeError, FileNotFoundError):
            # Existing-target protection may raise before owning an output folder.
            pass
        if result is not None:
            self.assertIsInstance(result, dict)
            self.assertEqual('BLOCKED', result['status'], result)
            self.assertNotEqual('PASS', result.get('buildStatus'), result)
        report_path = self.output / 'reference-build.json'
        if report_path.exists():
            report = json.loads(report_path.read_text('utf-8'))
            self.assertEqual('BLOCKED', report['status'], report)
            self.assertNotEqual('PASS', report.get('buildStatus'), report)
            return report
        self.assertIsNone(result, 'A BLOCKED return must leave its diagnostic report')
        return None

    def known_audit(self):
        with contextlib.redirect_stdout(io.StringIO()):
            report = run_audit(self.source, self.manifest_path,
                               self.root / 'historical.duckdb', self.root / 'historical-report')
        path = self.root / 'frozen-known-audit.json'
        path.write_text(json.dumps(report, ensure_ascii=False, default=str), encoding='utf-8')
        return path, report

    def query(self, sql):
        with duckdb.connect(str(self.database), read_only=True) as connection:
            return connection.execute(sql).fetchall()

    def assert_no_database(self):
        self.assertFalse(self.database.exists())
        self.assertFalse(Path(str(self.database) + '.wal').exists())

    def test_clean_reference_is_ready_without_claiming_official_acceptance(self):
        report = self.build()
        self.assertEqual('REFERENCE_READY', report['status'])
        self.assertEqual('PASS', report['buildStatus'])
        self.assertEqual('PASS_WITH_LIMITATIONS', report['auditStatus'])
        self.assertIs(False, report['officialAcceptanceEligible'])
        for name in NAMES:
            self.assertEqual([(2,)], self.query(f'SELECT COUNT(*) FROM newzl.{name}'))

    def test_preserves_codes_unicode_nulls_and_datetime(self):
        self.build()
        self.assertEqual([('000001', '中文证券,甲', None), ('009999', '名称"乙', None)],
                         self.query('SELECT tgtcode,name,marketNo FROM newzl.hsj_stock_code_info ORDER BY mktcode'))
        value = self.query('SELECT firstLimitUpTime FROM newzl.hsj_stock_hq_basic WHERE mktcode=1')[0][0]
        self.assertEqual('2026-04-14 09:30:01', str(value))

    def test_preserves_legitimate_negative_and_sentinel_values(self):
        self.build()
        self.assertEqual([(-10000, -999999), (-10000, -999999)],
                         self.query('SELECT ZJLXMainNetTur,ZJLXMainNetTurInDays FROM newzl.hsj_stock_hq_ext ORDER BY mktcode'))

    def test_source_and_manifest_bytes_remain_unchanged(self):
        before = self.source_bytes()
        manifest_bytes = self.manifest_path.read_bytes()
        self.build()
        self.assertEqual(before, self.source_bytes())
        self.assertEqual(manifest_bytes, self.manifest_path.read_bytes())

    def test_lock_retains_truthful_snapshot_manifest_and_audit_status(self):
        report = self.build()
        lock = self.query('SELECT snapshot_id,manifest_sha256,status FROM audit_source_lock')
        self.assertEqual([(self.manifest['snapshotId'], digest(self.manifest_path), report['auditStatus'])], lock)

    def test_checkpoint_readonly_reopen_and_final_database_identity(self):
        report = self.build()
        identity = report['databaseIdentity']
        self.assertEqual(str(self.database.resolve()), identity['path'])
        self.assertEqual(digest(self.database), identity['sha256'])
        self.assertEqual(self.database.stat().st_size, identity['bytes'])
        self.assertFalse(identity['pendingWal'])
        self.assertEqual('PASS', report['checkpoint'])
        self.assertEqual('PASS', report['readOnlyReopen'])
        self.assertEqual(report['sourcesBefore'], report['sourcesAfter'])
        wal = Path(str(self.database) + '.wal')
        self.assertTrue(not wal.exists() or wal.stat().st_size == 0)
        self.assertEqual([(2,)], self.query('SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic'))

    def test_stored_primary_keys_have_explicit_zero_null_and_duplicate_checks(self):
        report = self.build()
        checks = {item['name']: item for item in report['checks']}
        for name in NAMES:
            for suffix in ('stored-null-keys', 'stored-duplicate-key-groups'):
                check = checks[name + ':' + suffix]
                self.assertEqual(('PASS', 0, 0), (check['status'], check['actual'], check['expected']))
            self.assertEqual(0, report['tables'][name]['nullKeys'])
            self.assertEqual(0, report['tables'][name]['duplicateKeyGroups'])

    def test_double_sentinel_is_preserved_and_counted_numerically(self):
        self.rows[NAMES[1]][0]['qfqAdd'] = '-999999'
        self.write_fixture()
        report = self.build()
        self.assertEqual('REFERENCE_READY', report['status'])
        self.assertEqual(1, report['tables'][NAMES[1]]['sentinelCounts']['qfqAdd'])
        self.assertEqual([(-999999.0,)], self.query('SELECT qfqAdd FROM newzl.hsj_stock_hq_basic WHERE mktcode=1'))

    def test_existing_database_is_not_opened_or_overwritten(self):
        self.database.write_bytes(b'keep existing database bytes')
        before = self.database.read_bytes()
        self.assert_blocked()
        self.assertEqual(before, self.database.read_bytes())

    def test_existing_nonempty_wal_is_not_deleted_or_overwritten(self):
        wal = Path(str(self.database) + '.wal')
        wal.write_bytes(b'keep WAL')
        self.assert_blocked()
        self.assertEqual(b'keep WAL', wal.read_bytes())
        self.assertFalse(self.database.exists())

    def test_existing_empty_wal_also_blocks_rebuild(self):
        wal = Path(str(self.database) + '.wal')
        wal.touch()
        self.assert_blocked()
        self.assertEqual(b'', wal.read_bytes())
        self.assertFalse(self.database.exists())

    def test_existing_temporary_database_path_blocks_rebuild(self):
        temporary = Path(str(self.database) + '.tmp')
        temporary.write_bytes(b'preserve temporary database')
        self.assert_blocked()
        self.assertEqual(b'preserve temporary database', temporary.read_bytes())
        self.assertFalse(self.database.exists())

    def test_existing_exclusive_build_claim_is_preserved(self):
        claim = Path(str(self.database) + '.build-lock.json')
        claim.write_bytes(b'preserve previous build claim')
        self.assert_blocked()
        self.assertEqual(b'preserve previous build claim', claim.read_bytes())
        self.assertFalse(self.database.exists())

    def test_existing_empty_report_directory_is_not_reused(self):
        self.output.mkdir()
        self.assert_blocked()
        self.assertEqual([], list(self.output.iterdir()))
        self.assert_no_database()

    def test_existing_report_is_not_overwritten(self):
        self.output.mkdir()
        existing = self.output / 'reference-build.json'
        existing.write_bytes(b'previous report must survive')
        with self.assertRaises((ValueError, FileExistsError, RuntimeError)):
            self.build()
        self.assertEqual(b'previous report must survive', existing.read_bytes())
        self.assert_no_database()

    def test_second_build_cannot_overwrite_ready_database_or_report(self):
        self.build()
        database_bytes = self.database.read_bytes()
        report_bytes = (self.output / 'reference-build.json').read_bytes()
        with self.assertRaises((ValueError, FileExistsError, RuntimeError)):
            self.build()
        self.assertEqual(database_bytes, self.database.read_bytes())
        self.assertEqual(report_bytes, (self.output / 'reference-build.json').read_bytes())

    def test_source_sha_mismatch_blocks_before_audit_or_database(self):
        self.manifest['files'][NAMES[0]]['sha256'] = '0' * 64
        self.save_manifest()
        with patch('build_reference_duckdb.run_audit', side_effect=AssertionError('audit must not run')) as audit:
            self.assert_blocked()
            audit.assert_not_called()
        self.assert_no_database()

    def test_source_byte_size_mismatch_blocks_before_database(self):
        self.manifest['files'][NAMES[1]]['bytes'] += 1
        self.save_manifest()
        self.assert_blocked()
        self.assert_no_database()

    def test_header_mismatch_blocks_before_database(self):
        self.manifest['files'][NAMES[0]]['header'][2] = 'wrong_header'
        self.save_manifest()
        self.assert_blocked()
        self.assert_no_database()

    def test_missing_manifest_table_blocks_before_database(self):
        del self.manifest['files'][NAMES[2]]
        self.save_manifest()
        self.assert_blocked()
        self.assert_no_database()

    def test_missing_exact_relative_path_does_not_fall_back_to_basename(self):
        self.manifest['files'][NAMES[0]]['relativePath'] = 'wrong-folder/' + NAMES[0] + '.csv'
        self.save_manifest()
        self.assert_blocked()
        self.assert_no_database()

    def test_duplicate_basename_sources_are_ambiguous_and_blocked(self):
        duplicate = self.source / 'another-folder'
        duplicate.mkdir()
        (duplicate / (NAMES[0] + '.csv')).write_bytes(self.source_file().read_bytes())
        self.assert_blocked()
        self.assert_no_database()

    def test_relative_path_traversal_is_rejected_even_with_matching_file_identity(self):
        outside = self.root / 'outside.csv'
        outside.write_bytes(self.source_file().read_bytes())
        self.manifest['files'][NAMES[0]]['relativePath'] = '../outside.csv'
        self.save_manifest()
        self.assert_blocked()
        self.assert_no_database()

    def test_absolute_relative_path_is_rejected(self):
        self.manifest['files'][NAMES[0]]['relativePath'] = str(self.source_file().resolve())
        self.save_manifest()
        self.assert_blocked()
        self.assert_no_database()

    def test_row_count_mismatch_blocks_and_preserves_imported_rows(self):
        self.manifest['files'][NAMES[1]]['rows'] += 1
        self.save_manifest()
        self.assertIsNotNone(self.assert_blocked())
        self.assertEqual([(2,)], self.query('SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic'))

    def test_date_range_mismatch_cannot_produce_reference_ready(self):
        self.manifest['files'][NAMES[1]]['dateMin'] = '2006-01-04'
        self.save_manifest()
        self.assertIsNotNone(self.assert_blocked())

    def test_profile_count_mismatch_cannot_produce_reference_ready(self):
        self.manifest['files'][NAMES[0]]['nullCounts']['marketNo'] = 0
        self.save_manifest()
        self.assertIsNotNone(self.assert_blocked())

    def test_unknown_duplicate_failure_is_blocked_but_rows_are_retained(self):
        self.rows[NAMES[1]].append(copy.deepcopy(self.rows[NAMES[1]][0]))
        self.write_fixture()
        self.assertIsNotNone(self.assert_blocked())
        self.assertEqual([(3,)], self.query('SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic'))
        self.assertEqual([('FAIL',)], self.query('SELECT status FROM audit_source_lock'))

    def test_unknown_orphan_failure_is_blocked_without_discarding_extension(self):
        self.rows[NAMES[2]][1]['bizdate'] = '2026-04-15'
        self.write_fixture()
        self.assertIsNotNone(self.assert_blocked())
        self.assertEqual([(2,)], self.query('SELECT COUNT(*) FROM newzl.hsj_stock_hq_ext'))
        self.assertEqual([('2026-04-15',)], self.query("SELECT CAST(bizdate AS VARCHAR) FROM newzl.hsj_stock_hq_ext WHERE mktcode=103"))

    def test_known_identical_orphan_failure_is_ready_with_source_limitations(self):
        self.rows[NAMES[2]][1]['bizdate'] = '2026-04-15'
        self.write_fixture()
        known_path, known = self.known_audit()
        self.assertEqual('FAIL', known['status'])
        report = self.build(known_audit=known_path)
        self.assertEqual('REFERENCE_READY_WITH_SOURCE_LIMITATIONS', report['status'])
        self.assertEqual('PASS', report['buildStatus'])
        self.assertEqual('FAIL', report['auditStatus'])
        self.assertIs(False, report['officialAcceptanceEligible'])
        self.assertEqual([('FAIL',)], self.query('SELECT status FROM audit_source_lock'))
        self.assertEqual([(2,)], self.query('SELECT COUNT(*) FROM newzl.hsj_stock_hq_ext'))

    def test_known_audit_wrong_source_identity_cannot_allow_failure(self):
        self.rows[NAMES[2]][1]['bizdate'] = '2026-04-15'
        self.write_fixture()
        known_path, known = self.known_audit()
        known['tables'][NAMES[2]]['sha256'] = 'f' * 64
        known_path.write_text(json.dumps(known, default=str), encoding='utf-8')
        self.assertIsNotNone(self.assert_blocked(known_audit=known_path))

    def test_known_audit_wrong_failure_detail_cannot_allow_failure(self):
        self.rows[NAMES[2]][1]['bizdate'] = '2026-04-15'
        self.write_fixture()
        known_path, known = self.known_audit()
        next(item for item in known['checks'] if item['name'] == 'extensionWithoutBasic')['detail'] = 999
        known_path.write_text(json.dumps(known, default=str), encoding='utf-8')
        self.assertIsNotNone(self.assert_blocked(known_audit=known_path))

    def test_unknown_price_range_warning_is_blocked(self):
        self.rows[NAMES[1]][0].update(closePx='25000', turnover='25000')
        self.write_fixture()
        report = self.assert_blocked()
        self.assertIsNotNone(report)
        self.assertEqual('PASS_WITH_LIMITATIONS', report['auditStatus'])

    def test_known_identical_price_range_warning_keeps_truthful_audit_status(self):
        self.rows[NAMES[1]][0].update(closePx='25000', turnover='25000')
        self.write_fixture()
        known_path, known = self.known_audit()
        self.assertEqual('PASS_WITH_LIMITATIONS', known['status'])
        report = self.build(known_audit=known_path)
        self.assertEqual('REFERENCE_READY_WITH_SOURCE_LIMITATIONS', report['status'])
        self.assertEqual('PASS_WITH_LIMITATIONS', report['auditStatus'])
        self.assertEqual([('PASS_WITH_LIMITATIONS',)], self.query('SELECT status FROM audit_source_lock'))

    def test_unknown_invalid_numeric_type_is_not_mislabeled_build_success(self):
        self.rows[NAMES[1]][0]['closePx'] = 'not-a-number'
        self.write_fixture()
        report = self.assert_blocked()
        self.assertIsNotNone(report)
        self.assertEqual([('FAIL',)], self.query('SELECT status FROM audit_source_lock'))

    def test_incomplete_audit_check_set_cannot_publish_reference_ready(self):
        def omit_check(*args, **kwargs):
            result = run_audit(*args, **kwargs)
            result['checks'] = [item for item in result['checks'] if item['name'] != NAMES[1] + ':types']
            return result

        with patch('build_reference_duckdb.run_audit', side_effect=omit_check):
            self.assertIsNotNone(self.assert_blocked())

    def test_historical_failure_cannot_disappear_as_fake_audit_pass(self):
        self.rows[NAMES[2]][1]['bizdate'] = '2026-04-15'
        self.write_fixture()
        known_path, _ = self.known_audit()

        def hide_known_failure(*args, **kwargs):
            result = run_audit(*args, **kwargs)
            check = next(item for item in result['checks'] if item['name'] == 'extensionWithoutBasic')
            check.update(status='PASS', detail=0)
            result['status'] = 'PASS_WITH_LIMITATIONS'
            return result

        with patch('build_reference_duckdb.run_audit', side_effect=hide_known_failure):
            self.assertIsNotNone(self.assert_blocked(known_audit=known_path))

    def test_stored_duplicate_is_detected_even_if_count_profiles_and_audit_are_unchanged(self):
        def corrupt_stored_key(*args, **kwargs):
            result = run_audit(*args, **kwargs)
            with duckdb.connect(str(self.database)) as connection:
                connection.execute('DELETE FROM newzl.hsj_stock_hq_basic WHERE mktcode=103')
                connection.execute('INSERT INTO newzl.hsj_stock_hq_basic SELECT * FROM newzl.hsj_stock_hq_basic WHERE mktcode=1')
            return result

        with patch('build_reference_duckdb.run_audit', side_effect=corrupt_stored_key):
            report = self.assert_blocked()
        self.assertIsNotNone(report)
        self.assertIn('stored-duplicate-key-groups', report['error']['message'])
        self.assertEqual([(2,)], self.query('SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic'))

    def test_unknown_negative_price_is_blocked_but_original_negative_is_retained(self):
        self.rows[NAMES[1]][0]['closePx'] = '-5'
        self.write_fixture()
        self.assertIsNotNone(self.assert_blocked())
        self.assertEqual([(-5,)], self.query('SELECT closePx FROM newzl.hsj_stock_hq_basic WHERE mktcode=1'))

    def test_historical_negative_price_failure_is_not_approved_as_known_exception(self):
        self.rows[NAMES[1]][0]['closePx'] = '-5'
        self.write_fixture()
        known_path, known = self.known_audit()
        self.assertEqual('FAIL', known['status'])
        self.assertIsNotNone(self.assert_blocked(known_audit=known_path))
        self.assertEqual([(-5,)], self.query('SELECT closePx FROM newzl.hsj_stock_hq_basic WHERE mktcode=1'))

    def test_resource_sql_fragment_is_rejected_before_database_creation(self):
        self.assertIsNotNone(self.assert_blocked(memory_limit="2GB'; DROP SCHEMA newzl CASCADE;--"))
        self.assert_no_database()

    def test_boolean_threads_are_rejected_before_database_creation(self):
        self.assertIsNotNone(self.assert_blocked(threads=True))
        self.assert_no_database()

    def test_source_modified_during_audit_is_detected_after_build(self):
        source_file = self.source_file()

        def mutate_source(*args, **kwargs):
            result = run_audit(*args, **kwargs)
            with source_file.open('ab') as stream:
                stream.write(b'\n')
            return result

        with patch('build_reference_duckdb.run_audit', side_effect=mutate_source):
            self.assertIsNotNone(self.assert_blocked())
        self.assertTrue(self.database.exists(), 'Partial build evidence must not be deleted')

    def test_manifest_modified_during_audit_is_detected_after_build(self):
        def mutate_manifest(*args, **kwargs):
            result = run_audit(*args, **kwargs)
            with self.manifest_path.open('ab') as stream:
                stream.write(b'\n')
            return result

        with patch('build_reference_duckdb.run_audit', side_effect=mutate_manifest):
            self.assertIsNotNone(self.assert_blocked())

    def test_audit_exception_preserves_partial_database_and_blocked_evidence(self):
        def fail_during_audit(data_root, manifest_path, database, output_dir, **kwargs):
            with duckdb.connect(str(database)) as connection:
                connection.execute('CREATE TABLE partial_build(value INTEGER)')
                connection.execute('INSERT INTO partial_build VALUES (7)')
            raise RuntimeError('injected build interruption')

        with patch('build_reference_duckdb.run_audit', side_effect=fail_during_audit):
            self.assertIsNotNone(self.assert_blocked())
        self.assertTrue(self.database.exists())
        self.assertEqual([(7,)], self.query('SELECT value FROM partial_build'))

    def test_checkpoint_failure_cannot_publish_a_ready_reference(self):
        real_connect = duckdb.connect

        class InterruptedCheckpoint:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def __enter__(self):
                self.connection.__enter__()
                return self

            def __exit__(self, *args):
                return self.connection.__exit__(*args)

            def execute(self, sql, *args, **kwargs):
                if sql.strip().upper() == 'CHECKPOINT':
                    raise RuntimeError('injected checkpoint failure')
                return self.connection.execute(sql, *args, **kwargs)

        def connect(*args, **kwargs):
            return InterruptedCheckpoint(real_connect(*args, **kwargs))

        with patch('build_reference_duckdb.duckdb.connect', side_effect=connect):
            report = self.assert_blocked()
        self.assertIsNotNone(report)
        self.assertNotEqual('PASS', report.get('checkpoint'))
        self.assertTrue(self.database.exists())

    def test_readonly_reopen_failure_cannot_publish_a_ready_reference(self):
        with patch('build_reference_duckdb.reopen_and_verify',
                   side_effect=RuntimeError('injected read-only verification failure')):
            report = self.assert_blocked()
        self.assertIsNotNone(report)
        self.assertEqual('PASS', report['checkpoint'])
        self.assertNotEqual('PASS', report.get('readOnlyReopen'))
        self.assertTrue(self.database.exists())

    def test_historical_audit_changed_during_build_is_detected(self):
        known_path, _ = self.known_audit()

        def mutate_history(*args, **kwargs):
            result = run_audit(*args, **kwargs)
            with known_path.open('ab') as stream:
                stream.write(b'\n')
            return result

        with patch('build_reference_duckdb.run_audit', side_effect=mutate_history):
            self.assertIsNotNone(self.assert_blocked(known_audit=known_path))

    def test_database_appearing_after_preflight_is_not_overwritten(self):
        real_known_anomalies = build_reference_duckdb.known_anomalies

        def claim_database(*args, **kwargs):
            result = real_known_anomalies(*args, **kwargs)
            self.database.write_bytes(b'another builder owns this database')
            return result

        with patch('build_reference_duckdb.known_anomalies', side_effect=claim_database):
            self.assertIsNotNone(self.assert_blocked())
        self.assertEqual(b'another builder owns this database', self.database.read_bytes())

    def test_cli_existing_report_returns_nonzero_without_overwriting(self):
        self.output.mkdir()
        report_path = self.output / 'reference-build.json'
        report_path.write_bytes(b'existing report')
        with contextlib.redirect_stdout(io.StringIO()):
            code = build_reference_duckdb.main([
                '--data-root', str(self.source), '--manifest', str(self.manifest_path),
                '--database', str(self.database), '--output-dir', str(self.output),
                '--known-audit', str(self.root / 'unused-known-audit.json'),
            ])
        self.assertNotEqual(0, code)
        self.assertEqual(b'existing report', report_path.read_bytes())
        self.assert_no_database()


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
    parser.add_argument('--output', type=Path, help='New JSON report; never overwrites existing evidence')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('--output must be a new file')
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {
        'status': 'PASS' if result.wasSuccessful() else 'FAIL',
        'purpose': 'OFFLINE_INDEPENDENT_RAW_REFERENCE_REBUILD_CONTRACTS',
        'officialAcceptance': False, 'realCsvAccessed': False,
        'realDatabaseAccessed': False, 'dorisExecuted': False,
        'timestampUtc': datetime.now(timezone.utc).isoformat(),
        'total': result.testsRun,
        'passed': sum(item['status'] == 'PASS' for item in result.records),
        'failed': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'elapsedMs': round((time.perf_counter() - started) * 1000, 3),
        'implementationSha256': {
            'build_reference_duckdb.py': digest(Path(build_reference_duckdb.__file__)),
            'audit_official_data.py': digest(Path(run_audit.__code__.co_filename)),
        },
        'checks': result.records,
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
