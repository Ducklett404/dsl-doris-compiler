"""Offline recovery contracts; all CSV fixtures live in self-cleaning temp dirs."""
from __future__ import annotations

import argparse
import contextlib
import copy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
import unittest

import prepare_recovery_csv
import verify_recovery_load_response


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class PreparationContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='recovery-workflow-selftest-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.output = self.root / 'prepared'
        self.manifest_path = self.root / 'manifest.json'
        # Synthetic values only: never read or modify the user's frozen CSV files.
        self.fixtures = {
            'hsj_stock_code_info': (
                ['mktcode', 'tgtcode', 'name', 'optional'],
                [['1', '000001', '名称,含逗号', ''],
                 ['2', '000001', '名字"含双引号', ' '],
                 ['103', '009999', '名称\n含换行', r'\N']]),
            'hsj_stock_hq_basic': (
                ['mktcode', 'tgtcode', 'bizdate', 'closePx', 'remark'],
                [['1', '000001', '2026-04-10', '1250', ''],
                 ['1', '000001', '2026-04-11', '', '含,逗号'],
                 ['1', '000001', '2026-04-12', '-999999', '含"引号'],
                 ['2', '000001', '2026-04-13', '0', '含\n换行'],
                 ['103', '009999', '2026-04-14', '-5', '空格 保留']]),
            'hsj_stock_hq_extend': (
                ['mktcode', 'tgtcode', 'bizdate', 'qfqMulti', 'qfqAdd'],
                [['1', '000001', '2026-04-10', '1.25', '0'],
                 ['2', '000001', '2026-04-13', '', '-1.5'],
                 ['103', '009999', '2026-04-14', '1', '']]),
        }
        self.manifest = {'snapshotId': 'synthetic-recovery-v1', 'files': {}}
        for table, (header, rows) in self.fixtures.items():
            source_file = self.source / (table + '.csv')
            with source_file.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\r\n')
                writer.writerow(header)
                writer.writerows(rows)
            self.manifest['files'][table] = {
                'relativePath': source_file.name, 'header': header[:],
                'rows': len(rows), 'sha256': sha256(source_file),
                'bytes': source_file.stat().st_size,
            }
        self.save_manifest()
        self.originals = self.source_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def save_manifest(self):
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def source_bytes(self):
        return {p.name: p.read_bytes() for p in self.source.iterdir()}

    def run_prepare(self, chunk_rows=2):
        with contextlib.redirect_stdout(io.StringIO()):
            return prepare_recovery_csv.prepare(
                self.source, self.output, self.manifest_path, chunk_rows)

    def read_parts(self, table, report):
        rows = []
        for part in report['files'][table]['parts']:
            with (self.output / table / part['file']).open(
                    encoding='utf-8', newline='') as stream:
                reader = csv.reader(stream)
                self.assertEqual(self.fixtures[table][0], next(reader))
                rows.extend(reader)
        return rows

    def test_three_tables_row_and_null_counts(self):
        report = self.run_prepare()
        self.assertEqual('PASS', report['status'])
        self.assertEqual(set(self.fixtures), set(report['files']))
        for table, (_, rows) in self.fixtures.items():
            actual = report['files'][table]
            self.assertEqual(len(rows), actual['rows'], table)
            self.assertEqual(sum(value == '' for row in rows for value in row),
                             actual['nullFields'], table)

    def test_only_empty_fields_become_literal_null_marker(self):
        report = self.run_prepare()
        for table, (_, source_rows) in self.fixtures.items():
            expected = [[r'\N' if v == '' else v for v in row] for row in source_rows]
            self.assertEqual(expected, self.read_parts(table, report), table)
        self.assertEqual(' ', self.read_parts('hsj_stock_code_info', report)[1][3])

    def test_csv_quoted_commas_quotes_and_newlines_round_trip(self):
        report = self.run_prepare()
        code_rows = self.read_parts('hsj_stock_code_info', report)
        self.assertEqual('名称,含逗号', code_rows[0][2])
        self.assertEqual('名字"含双引号', code_rows[1][2])
        self.assertEqual('名称\n含换行', code_rows[2][2])
        self.assertEqual('000001', code_rows[0][1])
        self.assertEqual('009999', code_rows[2][1])

    def test_requested_chunk_size_exact_counts_and_part_names(self):
        report = self.run_prepare(chunk_rows=2)
        for table, (_, rows) in self.fixtures.items():
            parts = report['files'][table]['parts']
            expected_counts = [min(2, len(rows) - offset) for offset in range(0, len(rows), 2)]
            self.assertEqual(expected_counts, [part['rows'] for part in parts], table)
            self.assertEqual([f'part-{i:05}.csv' for i in range(len(parts))],
                             [part['file'] for part in parts], table)
            self.assertEqual(len(rows), sum(part['rows'] for part in parts), table)

    def test_part_hashes_and_actual_csv_record_counts(self):
        report = self.run_prepare()
        for table, entry in report['files'].items():
            for part in entry['parts']:
                path = self.output / table / part['file']
                self.assertEqual(sha256(path), part['sha256'])
                with path.open(encoding='utf-8', newline='') as stream:
                    self.assertEqual(part['rows'] + 1, len(list(csv.reader(stream))))

    def test_samples_preserve_original_values_including_empty_strings(self):
        report = self.run_prepare()
        for table, (header, rows) in self.fixtures.items():
            self.assertEqual([dict(zip(header, row)) for row in rows],
                             report['files'][table]['samples'], table)
        self.assertEqual('', report['files']['hsj_stock_hq_basic']['samples'][1]['closePx'])

    def test_original_csv_and_manifest_bytes_are_unchanged(self):
        original_manifest = self.manifest_path.read_bytes()
        self.run_prepare()
        self.assertEqual(self.originals, self.source_bytes())
        self.assertEqual(original_manifest, self.manifest_path.read_bytes())

    def test_snapshot_identity_and_persisted_reports_match(self):
        report = self.run_prepare()
        self.assertEqual(self.manifest['snapshotId'], report['snapshotId'])
        self.assertEqual(sha256(self.manifest_path), report['manifestSha256'])
        self.assertEqual(report, json.loads((self.output / 'prepared-snapshot.json').read_text('utf-8')))
        for table, entry in report['files'].items():
            self.assertEqual(self.manifest['files'][table]['sha256'], entry['sourceSha256'])
            self.assertEqual(entry, json.loads((self.output / table / 'parts.json').read_text('utf-8')))

    def test_source_sha_mismatch_is_rejected_before_any_parts(self):
        self.manifest['files']['hsj_stock_code_info']['sha256'] = '0' * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Frozen source mismatch'):
            self.run_prepare()
        self.assertEqual([], list(self.output.iterdir()))
        self.assertEqual(self.originals, self.source_bytes())

    def test_source_byte_size_mismatch_is_rejected(self):
        self.manifest['files']['hsj_stock_hq_basic']['bytes'] += 1
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Frozen source mismatch'):
            self.run_prepare()
        self.assertEqual([], list(self.output.iterdir()))

    def test_header_mismatch_is_rejected_without_completed_snapshot(self):
        self.manifest['files']['hsj_stock_code_info']['header'][2] = 'wrong_name'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Header mismatch'):
            self.run_prepare()
        self.assertFalse((self.output / 'prepared-snapshot.json').exists())
        self.assertEqual(self.originals, self.source_bytes())

    def test_expected_source_row_count_mismatch_is_rejected(self):
        self.manifest['files']['hsj_stock_hq_basic']['rows'] += 1
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'expected 6 rows, read 5'):
            self.run_prepare()
        self.assertFalse((self.output / 'prepared-snapshot.json').exists())
        self.assertEqual(self.originals, self.source_bytes())

    def test_wrong_csv_field_count_is_rejected(self):
        table = 'hsj_stock_code_info'
        path = self.source / self.manifest['files'][table]['relativePath']
        with path.open('a', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerow(['only', 'two'])
        self.manifest['files'][table].update(sha256=sha256(path), bytes=path.stat().st_size, rows=4)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'wrong field count'):
            self.run_prepare()
        self.assertFalse((self.output / 'prepared-snapshot.json').exists())

    def test_nonempty_destination_is_rejected_without_overwriting(self):
        self.output.mkdir()
        keep = self.output / 'keep.txt'
        keep.write_bytes(b'preserve existing content')
        with self.assertRaisesRegex(ValueError, 'empty output directory'):
            self.run_prepare()
        self.assertEqual(b'preserve existing content', keep.read_bytes())
        self.assertEqual(['keep.txt'], [p.name for p in self.output.iterdir()])
        self.assertEqual(self.originals, self.source_bytes())

    def test_repeat_preparation_refuses_to_overwrite_previous_parts(self):
        self.run_prepare()
        before = {str(p.relative_to(self.output)): p.read_bytes()
                  for p in self.output.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'empty output directory'):
            self.run_prepare()
        after = {str(p.relative_to(self.output)): p.read_bytes()
                 for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_chunk_size_bounds_are_rejected_before_output(self):
        for chunk_rows in (0, -1, 1000001):
            with self.assertRaisesRegex(ValueError, 'chunk_rows'):
                self.run_prepare(chunk_rows=chunk_rows)
            self.assertFalse(self.output.exists())

    def test_missing_source_is_rejected(self):
        self.manifest['files']['hsj_stock_code_info']['relativePath'] = 'does-not-exist.csv'
        self.save_manifest()
        with self.assertRaises(FileNotFoundError):
            self.run_prepare()
        self.assertFalse((self.output / 'prepared-snapshot.json').exists())

    def test_all_source_hashes_are_checked_before_any_table_is_written(self):
        self.manifest['files']['hsj_stock_hq_extend']['sha256'] = 'f' * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Frozen source mismatch: hsj_stock_hq_extend'):
            self.run_prepare()
        self.assertEqual([], list(self.output.iterdir()))


class StreamLoadContracts(unittest.TestCase):
    def response(self, status='Success'):
        return {'Status': status, 'NumberTotalRows': 5, 'NumberLoadedRows': 5,
                'NumberFilteredRows': 0, 'NumberUnselectedRows': 0}

    def test_exact_success_counts_are_accepted(self):
        self.assertEqual('Success', verify_recovery_load_response.verify(self.response(), 5))

    def test_publish_timeout_with_exact_counts_is_accepted_not_retry_failure(self):
        # This pure classifier returns a committed-state status; it never performs
        # network I/O or a retry. Caller-level visibility waiting is not tested here.
        response = self.response('Publish Timeout')
        original = copy.deepcopy(response)
        self.assertEqual('Publish Timeout', verify_recovery_load_response.verify(response, 5))
        self.assertEqual(original, response)

    def test_filtered_rows_are_rejected(self):
        response = self.response()
        response['NumberFilteredRows'] = 1
        with self.assertRaisesRegex(ValueError, 'NumberFilteredRows'):
            verify_recovery_load_response.verify(response, 5)

    def test_partial_total_rows_are_rejected(self):
        response = self.response()
        response['NumberTotalRows'] = 4
        with self.assertRaisesRegex(ValueError, 'NumberTotalRows'):
            verify_recovery_load_response.verify(response, 5)

    def test_partial_loaded_rows_are_rejected(self):
        response = self.response()
        response['NumberLoadedRows'] = 4
        with self.assertRaisesRegex(ValueError, 'NumberLoadedRows'):
            verify_recovery_load_response.verify(response, 5)

    def test_unselected_rows_are_rejected(self):
        response = self.response()
        response['NumberUnselectedRows'] = 1
        with self.assertRaisesRegex(ValueError, 'NumberUnselectedRows'):
            verify_recovery_load_response.verify(response, 5)

    def test_failure_and_missing_status_are_rejected(self):
        for status in ('Fail', 'Cancelled', 'Label Already Exists', 'success', None):
            with self.assertRaisesRegex(ValueError, 'Stream Load rejected'):
                verify_recovery_load_response.verify(self.response(status), 5)
        response = self.response()
        del response['Status']
        with self.assertRaisesRegex(ValueError, 'Stream Load rejected'):
            verify_recovery_load_response.verify(response, 5)

    def test_each_missing_counter_is_rejected(self):
        for key in self.response().keys() - {'Status'}:
            response = self.response()
            del response[key]
            with self.assertRaisesRegex(ValueError, key):
                verify_recovery_load_response.verify(response, 5)

    def test_boolean_counters_are_rejected_even_when_numeric_values_match(self):
        for key in self.response().keys() - {'Status'}:
            response = self.response()
            response['NumberTotalRows'] = 1
            response['NumberLoadedRows'] = 1
            response[key] = True if key in ('NumberTotalRows', 'NumberLoadedRows') else False
            with self.assertRaisesRegex(ValueError, key):
                verify_recovery_load_response.verify(response, 1)

    def test_noninteger_counters_are_rejected(self):
        for key in self.response().keys() - {'Status'}:
            for invalid in (None, str(self.response()[key]), float(self.response()[key])):
                response = self.response()
                response[key] = invalid
                with self.assertRaisesRegex(ValueError, key):
                    verify_recovery_load_response.verify(response, 5)

    def test_publish_timeout_partial_or_filtered_counts_are_rejected(self):
        for key, value in (('NumberLoadedRows', 4), ('NumberFilteredRows', 1),
                           ('NumberUnselectedRows', 1), ('NumberTotalRows', 6)):
            response = self.response('Publish Timeout')
            response[key] = value
            with self.assertRaisesRegex(ValueError, key):
                verify_recovery_load_response.verify(response, 5)

    def test_verification_does_not_mutate_response(self):
        response = self.response()
        original = copy.deepcopy(response)
        verify_recovery_load_response.verify(response, 5)
        self.assertEqual(original, response)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.started = {}

    def startTest(self, test):
        self.started[test.id()] = time.perf_counter()
        super().startTest(test)

    def record(self, test, status, error=None):
        record = {'name': test.id(), 'status': status,
                  'elapsedMs': round((time.perf_counter() - self.started[test.id()]) * 1000, 3)}
        if error is not None:
            record['error'] = ''.join(traceback.format_exception(*error))
        self.records.append(record)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, 'PASS')

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.record(test, 'FAIL', error)

    def addError(self, test, error):
        super().addError(test, error)
        self.record(test, 'ERROR', error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        help='New JSON report path; existing reports are never overwritten')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('--output must be a new file')
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=RecordingResult).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {
        'status': 'PASS' if result.wasSuccessful() else 'FAIL',
        'purpose': 'PURE_OFFLINE_RECOVERY_WORKFLOW_CONTRACTS',
        'officialAcceptance': False, 'dorisExecuted': False,
        'networkExecuted': False, 'realSourceFilesAccessed': False,
        'timestampUtc': datetime.now(timezone.utc).isoformat(),
        'total': result.testsRun,
        'passed': sum(record['status'] == 'PASS' for record in result.records),
        'failed': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'elapsedMs': round((time.perf_counter() - started) * 1000, 3),
        'implementationSha256': {
            'prepare_recovery_csv.py': sha256(Path(prepare_recovery_csv.__file__)),
            'verify_recovery_load_response.py': sha256(Path(verify_recovery_load_response.__file__)),
        },
        'checks': result.records,
        'limitations': ['Stream Load classification is tested; real Doris visibility and caller retry flow are not executed.'],
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(serialized)
        print(str(args.output.resolve()))
    else:
        print(serialized, end='')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
