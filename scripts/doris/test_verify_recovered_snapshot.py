"""Offline recovery-verifier contracts; this suite never connects to Doris."""
import copy
import csv
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import verify_recovered_snapshot as recovery


def fixture():
    schemas = recovery.ddl_schema()
    prepared = dict(status='PASS', snapshotId='offline-recovery-fixture', files={})
    manifest = dict(snapshotId=prepared['snapshotId'], contractVersion='fixture-v1', files={})
    for table, schema in schemas.items():
        sample = {}
        for field, item in schema.items():
            family = recovery.type_family(item['type'])
            sample[field] = {'DATE': '2026-04-14', 'DATETIME': '', 'BOOLEAN': 'true', 'VARCHAR': '测试证券'}.get(family, '1')
        sample.update(mktcode='1', tgtcode='000001')
        if table == recovery.TABLES[1]:
            sample.update(lastPx='100000', preClosePx='80000', closePx='100000', openPx='90000',
                          highPx='110000', lowPx='80000', turnover='9999', volume='100',
                          qfqMulti='2', qfqAdd='3', hfqMulti='3', hfqAdd='-2')
        if table == recovery.TABLES[2]:
            sample[recovery.CLEAN_COLUMNS[0]] = '-999999'
            sample[recovery.CLEAN_COLUMNS[1]] = ''
        header = list(schema)
        prepared['files'][table] = dict(rows=1, sourceSha256='a' * 64, header=header, samples=[sample], parts=[])
        nulls = {field: 1 for field, value in sample.items() if value == ''}
        sentinels = {field: 1 for field, value in sample.items() if value == '-999999'}
        manifest['files'][table] = dict(rows=1, sha256='a' * 64, header=header, nullCounts=nulls,
                                       sentinelMinus999999Counts=sentinels,
                                       dateMin=None if table == recovery.TABLES[0] else '2026-04-14',
                                       dateMax=None if table == recovery.TABLES[0] else '2026-04-14')
    return schemas, manifest, prepared


class FakeClient:
    def __init__(self, schemas, manifest, prepared, mutation=None):
        self.schemas, self.manifest, self.prepared = schemas, manifest, prepared
        self.mutation, self.sql = mutation, []
        self.rows = {table: [{field: recovery.typed_value(sample[field], schema[field]['type']) for field in schema}
                             for sample in prepared['files'][table]['samples']] for table, schema in schemas.items()}

    def query(self, sql):
        self.sql.append(sql)
        if self.mutation == 'transport':
            raise RuntimeError('Diagnostic transport unavailable')
        if 'data_snapshot_registry' in sql:
            return [] if self.mutation != 'registry' else [('fixture', '1', 'a' * 64, 'VALIDATED', '2026-04-14 00:00:00')]
        table = next(table for table in recovery.TABLES if table in sql)
        schema, item = self.schemas[table], self.manifest['files'][table]
        rows = self.rows[table]
        interval = re.search(r"`bizdate`>='([^']+)' AND `bizdate`<'([^']+)'", sql)
        if interval:
            rows = [row for row in rows if row['bizdate'] is not None and interval[1] <= row['bizdate'] < interval[2]]
        raw = self.rows[table][0]
        if 'information_schema.columns' in sql:
            result = [(field, kind['type'], 'YES' if kind['nullable'] else 'NO') for field, kind in schema.items()]
            if self.mutation == 'schema' and table == recovery.TABLES[1]:
                result[3] = (result[3][0], 'DOUBLE', result[3][2])
            if self.mutation == 'real-metadata-aliases':
                aliases = {'INT': 'int(11)', 'BIGINT': 'bigint(20)', 'TINYINT': 'tinyint(4)', 'BOOLEAN': 'tinyint(1)'}
                result = [(name, aliases.get(kind, kind.lower()), nullable) for name, kind, nullable in result]
            return result
        if 'duplicate_keys' in sql:
            return [('1', '2')] if self.mutation == 'duplicates' else [('0', '0')]
        if 'LIMIT 2' in sql:
            if self.mutation == 'missing-sample':
                return []
            requested_date = re.search(r"`bizdate`='([^']+)'", sql)
            if requested_date:
                raw = next(row for row in rows if row['bizdate'] == requested_date[1])
            if 'v_hsj_stock' in sql:
                values = recovery.semantic_values(raw) if table == recovery.TABLES[1] else {field + 'Clean': recovery.clean_value(raw[field]) for field in recovery.CLEAN_COLUMNS}
            else:
                values = raw
            columns = sql.split(' FROM ')[0][7:].split(',')
            fields = [column.strip('`') for column in columns[:len(columns) // 2]]
            selected = [values[field] for field in fields]
            if self.mutation == 'sample-raw' and table == recovery.TABLES[1] and 'closePx' in fields:
                selected[fields.index('closePx')] += 1
            if self.mutation == 'sample-semantic' and table == recovery.TABLES[1] and 'closeQfq' in fields:
                selected[fields.index('closeQfq')] += 1
            if self.mutation == 'sample-clean' and table == recovery.TABLES[2]:
                selected[0] = -999999
            return [tuple('NULL' if value is None else str(int(value) if isinstance(value, bool) else value) for value in selected)
                    + tuple('1' if value is None else '0' for value in selected)]
        if 'v_hsj_stock_hq_ext' in sql:
            result = []
            for field in recovery.CLEAN_COLUMNS:
                result += [str(sum(recovery.clean_value(row[field]) is None for row in rows)), '0', '0']
            if self.mutation == 'clean-leak':
                result[1] = '1'
            return [tuple(result)]
        if 'COALESCE(SUM(CASE' not in sql:
            if ' WHERE ' in sql:
                return [('1' if self.mutation == 'nullkey' else str(sum(any(row[key] is None for key in recovery.KEYS[table]) for row in rows)),)]
            result = [str(len(rows) + int(self.mutation == 'rows'))]
            if table != recovery.TABLES[0]:
                dates = [row['bizdate'] for row in rows if row['bizdate'] is not None]
                result += [min(dates) if dates else 'NULL', '2026-04-15' if self.mutation == 'dates' else max(dates) if dates else 'NULL']
            return [tuple(result)]
        result = [str(len(rows))]
        if self.mutation == 'shard-missing-row' and table == recovery.TABLES[1]:
            result[0] = str(max(0, len(rows) - 1))
        nulls = [str(sum(row[field] is None for row in rows)) for field in schema]
        if self.mutation == 'unlisted-null':
            nulls[list(schema).index('mktcode')] = '1'
        result += nulls
        numeric = [field for field in schema if recovery.type_family(schema[field]['type']) in
                   ('TINYINT', 'SMALLINT', 'INT', 'BIGINT', 'LARGEINT', 'FLOAT', 'DOUBLE', 'DECIMAL')]
        sentinels = [str(sum(row[field] == -999999 for row in rows)) for field in numeric]
        if self.mutation == 'unlisted-sentinel':
            sentinels[numeric.index('mktcode')] = '1'
        return [tuple(result + sentinels)]


class RecoveryFormulaTests(unittest.TestCase):
    def setUp(self):
        schemas, _, prepared = fixture()
        self.raw = {field: recovery.typed_value(value, schemas[recovery.TABLES[1]][field]['type'])
                    for field, value in prepared['files'][recovery.TABLES[1]]['samples'][0].items()}

    def test_prices_ratios_and_nonidentity_adjustment(self):
        result = recovery.semantic_values(self.raw)
        self.assertEqual(result['closePrice'], 10)
        self.assertEqual(result['closeQfq'], 23)
        self.assertEqual(result['closeHfq'], 28)
        self.assertEqual(result['openQfq'], 21)
        self.assertEqual(result['highHfq'], 31)
        self.assertEqual(result['marketValue'], 10)
        self.assertEqual(result['listedMarketValue'], 10)
        self.assertEqual(result['risePct'], 25)
        self.assertEqual(result['avgPx'], .9999)
        self.assertEqual(result['quantityRatio'], .0001)

    def test_zero_denominators_return_null(self):
        self.raw.update(volume=0, preClosePx=0)
        result = recovery.semantic_values(self.raw)
        self.assertIsNone(result['avgPx'])
        self.assertIsNone(result['risePct'])

    def test_missing_operand_is_not_zero(self):
        self.raw.update(closePx=None, totalShare=None, turnover=None, hfqMulti=None)
        result = recovery.semantic_values(self.raw)
        for field in ('closePrice', 'closeQfq', 'marketValue', 'avgPx', 'openHfq'):
            self.assertIsNone(result[field])

    def test_sentinel_clean_keeps_regular_negatives(self):
        self.assertIsNone(recovery.clean_value(-999999))
        self.assertIsNone(recovery.clean_value(None))
        self.assertEqual(recovery.clean_value(-3), -3)

    def test_double_casts_precede_price_difference(self):
        self.raw.update(lastPx=9007199254740993, preClosePx=9007199254740992)
        self.assertEqual(recovery.semantic_values(self.raw)['risePct'], 0)

    def test_type_normalization_keeps_codes_and_time(self):
        self.assertEqual(recovery.typed_value('000001', 'VARCHAR(16)'), '000001')
        self.assertEqual(recovery.typed_value('7.0', 'BIGINT'), 7)
        self.assertTrue(recovery.typed_value('TRUE', 'BOOLEAN'))
        self.assertEqual(recovery.typed_value('2026-04-14T09:30:00.000', 'DATETIME'), '2026-04-14 09:30:00')
        self.assertEqual(recovery.typed_value('NULL', 'VARCHAR(16)'), 'NULL')
        for value, kind in [('1.5', 'INT'), ('NaN', 'DOUBLE'), ('2', 'BOOLEAN')]:
            with self.assertRaises(ValueError):
                recovery.typed_value(value, kind)

    def test_formula_tolerance_and_null_equivalence(self):
        self.assertTrue(recovery.equivalent(None, None))
        self.assertFalse(recovery.equivalent(None, 0))
        self.assertTrue(recovery.equivalent(10., 10. + 1e-9))
        self.assertFalse(recovery.equivalent(10., 10. + 1e-6))

    def test_types_do_not_ignore_varchar_capacity(self):
        self.assertTrue(recovery.matching_type('DATETIME', 'datetimev2(0)'))
        self.assertFalse(recovery.matching_type('VARCHAR(16)', 'varchar(8)'))

    def test_real_doris_metadata_display_width_aliases_are_exact(self):
        for expected, actual in (('INT', 'int(11)'), ('BIGINT', 'bigint(20)'),
                                 ('TINYINT', 'tinyint(4)'), ('BOOLEAN', 'tinyint(1)'), ('BOOL', 'tinyint(1)')):
            with self.subTest(expected=expected, actual=actual):
                self.assertTrue(recovery.matching_type(expected, actual))
        for expected, actual in (('BOOLEAN', 'tinyint(4)'), ('BOOLEAN', 'tinyint'),
                                 ('TINYINT', 'tinyint(1)'), ('INT', 'int(10)'), ('BIGINT', 'bigint(19)'),
                                 ('VARCHAR(16)', 'varchar(8)'), ('DECIMAL(24,4)', 'decimal(24,2)'),
                                 ('DECIMAL(24,4)', 'decimal(30,4)'), ('DATETIME', 'datetimev2(6)'),
                                 ('DATETIMEV2(3)', 'datetimev2(6)')):
            with self.subTest(expected=expected, actual=actual):
                self.assertFalse(recovery.matching_type(expected, actual))

    def test_sql_empty_string_is_not_null(self):
        self.assertIsNone(recovery.typed_value('', 'VARCHAR(16)'))
        self.assertEqual(recovery.typed_value('', 'VARCHAR(16)', empty_is_null=False), '')
        self.assertFalse(recovery.equivalent(None, recovery.typed_value('', 'VARCHAR(16)', empty_is_null=False)))
        with self.assertRaises(Exception):
            recovery.typed_value('', 'BIGINT', empty_is_null=False)

    def test_year_ranges_are_adjacent_inclusive_exclusive_and_keep_endpoints(self):
        shards = recovery.year_shards(recovery.TABLES[1], dict(dateMin='2024-12-31', dateMax='2026-01-01'))
        self.assertEqual([item['year'] for item in shards], [2024, 2025, 2026])
        for before, after in zip(shards, shards[1:]):
            self.assertEqual(before['endExclusive'], after['startInclusive'])
        for value in ('2024-01-01', '2024-12-31', '2025-01-01', '2025-12-31', '2026-01-01', '2026-12-31'):
            self.assertEqual(sum(item['startInclusive'] <= value < item['endExclusive'] for item in shards), 1)
        self.assertEqual(sum(item['startInclusive'] <= '2027-01-01' < item['endExclusive'] for item in shards), 0)
        self.assertEqual(recovery.year_shards(recovery.TABLES[0], {})[0]['where'], '')
        for first, last in (('2026-04-14', '2025-04-14'), ('9999-01-01', '9999-12-31')):
            with self.assertRaises(ValueError):
                recovery.year_shards(recovery.TABLES[1], dict(dateMin=first, dateMax=last))


class RecoveryPipelineTests(unittest.TestCase):
    def setUp(self):
        self.schemas, self.manifest, self.prepared = fixture()

    def run_verify(self, mutation=None):
        client = FakeClient(self.schemas, self.manifest, self.prepared, mutation)
        return recovery.verify(client, self.manifest, self.prepared, self.schemas, {'manifestSha256': 'a' * 64}), client

    def calendar_fixture(self, dates):
        for table in recovery.TABLES[1:]:
            source = self.prepared['files'][table]
            original = source['samples'][0]
            samples = []
            for index, value in enumerate(dates):
                sample = copy.deepcopy(original)
                sample['bizdate'] = value
                if table == recovery.TABLES[1]:
                    sample['volume'] = '' if index % 2 == 0 else '100'
                else:
                    sample[recovery.CLEAN_COLUMNS[0]] = '-999999' if index % 2 == 0 else '5'
                    sample[recovery.CLEAN_COLUMNS[1]] = '' if index % 3 == 0 else '0'
                samples.append(sample)
            source.update(rows=len(samples), samples=samples)
            item = self.manifest['files'][table]
            item.update(rows=len(samples), dateMin=min(dates), dateMax=max(dates),
                        nullCounts={field: sum(row[field] == '' for row in samples) for field in self.schemas[table]
                                    if any(row[field] == '' for row in samples)},
                        sentinelMinus999999Counts={field: sum(row[field] == '-999999' for row in samples) for field in self.schemas[table]
                                                  if any(row[field] == '-999999' for row in samples)})

    def test_complete_offline_contract_pass_and_only_reads(self):
        report, client = self.run_verify()
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['passed'], report['total'])
        self.assertTrue(all(sql.startswith('SELECT ') and ';' not in sql for sql in client.sql))
        self.assertEqual(len(report['tables']), 3)
        self.assertEqual(len(report['tables'][recovery.TABLES[2]]['cleanChecks']), 6)
        self.assertEqual(report['officialRegistrationAction'], 'NONE_READ_ONLY')
        self.assertIn('NOT_RUN', report['globalAssociationCheck'])
        self.assertIn('| hsj_stock_hq_basic |', recovery.markdown(report))

    def test_full_checks_continue_with_real_mysql_metadata_aliases(self):
        report, client = self.run_verify('real-metadata-aliases')
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(len(report['tables']), 3)
        self.assertEqual(report['passed'], report['total'])
        self.assertTrue(any('duplicate_keys' in sql for sql in client.sql))
        self.assertTrue(all(item['samples'] for item in report['tables'].values()))

    def test_year_boundary_rows_are_counted_once_with_every_field_checked(self):
        dates = ['2024-12-31', '2025-01-01', '2025-12-31', '2026-01-01']
        self.calendar_fixture(dates)
        report, client = self.run_verify()
        self.assertEqual(report['status'], 'PASS')
        for table in recovery.TABLES[1:]:
            item = report['tables'][table]
            self.assertEqual(item['rows'], item['shardRows'])
            self.assertEqual([part['rows'] for part in item['aggregationShards']], [1, 2, 1])
            self.assertEqual(item['dateRange'], [dates[0], dates[-1]])
            self.assertEqual(item['duplicateKeyGroups'], 0)
            for part in item['aggregationShards']:
                self.assertEqual(set(part['nullCounts']), set(self.schemas[table]))
            full_stat_sql = 'SELECT COUNT(*),MIN(bizdate),MAX(bizdate) FROM ' + recovery.qualified(table)
            self.assertIn(full_stat_sql, client.sql)
            for sql in client.sql:
                if recovery.qualified(table) in sql and ('COALESCE(SUM(CASE' in sql or 'duplicate_keys' in sql):
                    self.assertIn(' WHERE `bizdate`>=', sql)
                    self.assertIn(' AND `bizdate`<', sql)
        basic = report['tables'][recovery.TABLES[1]]
        self.assertEqual(basic['nullCounts']['volume'], 2)
        ext = report['tables'][recovery.TABLES[2]]
        self.assertEqual(ext['sentinelMinus999999Counts'][recovery.CLEAN_COLUMNS[0]], 2)
        self.assertEqual([part['year'] for part in ext['cleanAggregationShards']], [2024, 2025, 2026])
        self.assertTrue(all(sql.startswith('SELECT ') and 'SET ' not in sql and 'exec_mem_limit' not in sql for sql in client.sql))

    def test_empty_year_shards_do_not_drop_source_coverage(self):
        self.calendar_fixture(['2024-12-31', '2028-01-01'])
        report, _ = self.run_verify()
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual([part['rows'] for part in report['tables'][recovery.TABLES[1]]['aggregationShards']], [1, 0, 0, 0, 1])
        self.assertEqual(report['tables'][recovery.TABLES[2]]['nullCounts'][recovery.CLEAN_COLUMNS[1]], 1)

    def test_shard_sum_must_equal_independent_full_count(self):
        self.calendar_fixture(['2024-12-31', '2025-01-01', '2026-01-01'])
        report, _ = self.run_verify('shard-missing-row')
        self.assertEqual(report['status'], 'BLOCKED')
        coverage = next(item for item in report['checks'] if item['name'] == recovery.TABLES[1] + ':year-shard-row-coverage')
        self.assertEqual(coverage['status'], 'BLOCKED')
        self.assertEqual(coverage['expectedFullTableRows'], 3)
        self.assertEqual(coverage['actualShardRows'], 0)

    def test_out_of_manifest_year_is_not_hidden_by_shard_filter(self):
        self.calendar_fixture(['2024-12-31', '2026-01-01'])
        self.manifest['files'][recovery.TABLES[1]]['dateMax'] = '2025-12-31'
        report, _ = self.run_verify()
        self.assertEqual(report['status'], 'BLOCKED')
        failed = {item['name'] for item in report['checks'] if item['status'] == 'BLOCKED'}
        self.assertIn(recovery.TABLES[1] + ':date-range', failed)
        self.assertIn(recovery.TABLES[1] + ':year-shard-row-coverage', failed)

    def test_every_mismatch_blocks_without_unexplained_crash(self):
        for mutation in ('rows', 'dates', 'duplicates', 'nullkey', 'schema', 'unlisted-null', 'unlisted-sentinel',
                         'sample-raw', 'sample-semantic', 'sample-clean', 'clean-leak', 'registry', 'missing-sample', 'transport'):
            with self.subTest(mutation=mutation):
                report, _ = self.run_verify(mutation)
                self.assertEqual(report['status'], 'BLOCKED')
                self.assertTrue(any(item['status'] == 'BLOCKED' for item in report['checks']))

    def test_each_sample_contains_raw_and_independent_view_evidence(self):
        report, _ = self.run_verify()
        sample = report['tables'][recovery.TABLES[1]]['samples'][0]
        self.assertEqual(len(sample['rawFields']), len(self.schemas[recovery.TABLES[1]]))
        self.assertEqual({item['field'] for item in sample['semanticFields']}, set(recovery.semantic_values(
            {field: recovery.typed_value(value, self.schemas[recovery.TABLES[1]][field]['type'])
             for field, value in self.prepared['files'][recovery.TABLES[1]]['samples'][0].items()})))
        self.assertGreater(len(report['sqlEvidence']), 10)

    def test_no_write_or_multi_statement_is_admitted(self):
        class Never:
            def query(self, sql):
                raise AssertionError('unsafe SQL reached client')
        query = recovery.ReadOnlyQueries(Never())
        for sql in ('DROP TABLE newzl.x', 'SET query_timeout=1', 'SELECT 1; DROP TABLE x', "SELECT 1 INTO OUTFILE '/tmp/out'"):
            with self.assertRaises(ValueError):
                query.query(sql)

    def test_identifiers_and_key_escaping_are_controlled(self):
        with self.assertRaises(ValueError):
            recovery.qualified('other_table')
        with self.assertRaises(ValueError):
            recovery.identifier('col) UNION SELECT 1')
        self.assertEqual(recovery.literal("a'\\b"), "'a''\\\\b'")


class PreparedIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.schemas, self.manifest, self.prepared = fixture()
        self.manifest_path = self.base / 'manifest.json'
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.prepared['manifestSha256'] = recovery.digest(self.manifest_path)
        for table, source in self.prepared['files'].items():
            folder = self.base / 'normalized' / table
            folder.mkdir(parents=True)
            path = folder / 'part-00000.csv'
            with path.open('w', encoding='utf-8', newline='') as output:
                writer = csv.writer(output)
                writer.writerow(source['header'])
                writer.writerow([value if value != '' else '\\N' for value in source['samples'][0].values()])
            source['parts'] = [dict(file=path.name, rows=1, sha256=recovery.digest(path))]
        self.save_certificate()

    def save_certificate(self):
        (self.base / 'normalized/prepared-snapshot.json').write_text(json.dumps(self.prepared), encoding='utf-8')

    def test_frozen_manifest_and_all_parts_are_rehashed(self):
        _, _, report = recovery.validate_prepared(self.base / 'normalized', self.manifest_path, self.schemas)
        self.assertEqual(len(report['files']), 3)
        self.assertEqual(report['manifestSha256'], recovery.digest(self.manifest_path))

    def test_changed_part_is_rejected_before_doris(self):
        path = self.base / 'normalized' / recovery.TABLES[1] / 'part-00000.csv'
        path.write_text('tampered', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed or is missing'):
            recovery.validate_prepared(self.base / 'normalized', self.manifest_path, self.schemas)

    def test_unsafe_part_or_sample_is_rejected(self):
        original = copy.deepcopy(self.prepared)
        for mutation in ('part-path', 'missing-samples', 'missing-field', 'duplicate-sample', 'source-hash', 'wrong-manifest'):
            with self.subTest(mutation=mutation):
                self.prepared = copy.deepcopy(original)
                source = self.prepared['files'][recovery.TABLES[1]]
                if mutation == 'part-path':
                    source['parts'][0]['file'] = '../../outside.csv'
                elif mutation == 'missing-samples':
                    source['samples'] = []
                elif mutation == 'missing-field':
                    source['samples'][0].pop('closePx')
                elif mutation == 'duplicate-sample':
                    source['samples'].append(copy.deepcopy(source['samples'][0]))
                elif mutation == 'source-hash':
                    source['sourceSha256'] = 'b' * 64
                else:
                    self.prepared['manifestSha256'] = 'b' * 64
                self.save_certificate()
                with self.assertRaises(ValueError):
                    recovery.validate_prepared(self.base / 'normalized', self.manifest_path, self.schemas)

    def test_cli_blocked_saves_json_and_markdown_without_doris(self):
        folder = self.base / 'new-evidence'
        with patch.object(recovery, 'WslDoris', side_effect=RuntimeError('test environment unavailable')):
            self.assertEqual(recovery.main(['--prepared-dir', str(self.base / 'normalized'), '--manifest', str(self.manifest_path), '--output-dir', str(folder)]), 2)
        report = json.loads((folder / 'recovered-snapshot-verification.json').read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertTrue((folder / 'recovered-snapshot-verification.md').exists())
        with self.assertRaises(FileExistsError):
            recovery.main(['--output-dir', str(folder)])


if __name__ == '__main__':
    unittest.main()
