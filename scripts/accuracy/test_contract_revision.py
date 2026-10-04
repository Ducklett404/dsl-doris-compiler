import copy
import hashlib
import json
from pathlib import Path
import unittest
import sqlite3
from run_correctness import registered_snapshot,bind_sql

ROOT=Path(__file__).resolve().parents[2]


class ContractRevisionTest(unittest.TestCase):
    def test_bound_security_codes_keep_text_identity_and_leading_zeroes(self):
        with sqlite3.connect(':memory:') as con:
            con.execute('CREATE TABLE codes(tgtcode VARCHAR(64))')
            con.executemany('INSERT INTO codes VALUES(?)',[('000001',),('1',)])
            actual=con.execute(bind_sql('SELECT tgtcode FROM codes WHERE tgtcode=?',['000001'])).fetchall()
            self.assertEqual([('000001',)],actual)

    def test_matching_counts_cannot_replace_exact_validated_registration(self):
        manifest={'snapshotId':'snapshot-v2','contractVersion':'contract-v2'}
        class Database:
            def __init__(self,rows):self.rows=rows
            def query(self,sql):
                self.sql=sql
                return self.rows
        for rows in ([], [('snapshot-v2','contract-v1','abc')],
                     [('snapshot-v2','contract-v2','wrong-hash')],
                     [('snapshot-v2','contract-v2','abc')]*2):
            with self.subTest(rows=rows):
                self.assertFalse(registered_snapshot(Database(rows),manifest,'abc'))
        db=Database([('snapshot-v2','contract-v2','abc')])
        self.assertTrue(registered_snapshot(db,manifest,'abc'))
        self.assertIn("status='VALIDATED'",db.sql)

    def test_versioned_revision_retains_cases_and_has_only_documented_changes(self):
        path=ROOT/'accuracy/golden/stock-slot-executable-v1.json'
        old=json.loads(path.read_text(encoding='utf-8'))
        new=json.loads((ROOT/'accuracy/golden/stock-slot-executable-v1.0.1.json').read_text(encoding='utf-8'))
        digest=hashlib.sha256(path.read_text(encoding='utf-8').replace('\r\n','\n').encode('utf-8')).hexdigest()
        self.assertEqual(digest,new['revision']['legacySha256'])
        self.assertEqual(old['snapshotId'],new['snapshotId'])
        self.assertEqual(old['resultContract'],new['resultContract'])
        expected=copy.deepcopy(old['cases'])
        for case in expected:
            if case['id'] in ('REG-002','BLIND-004'):
                case['expect']['requiredSql']=[s.replace('e.ZJLXMainNetTur AS `m1`','NULLIF(e.ZJLXMainNetTur,-999999) AS `m1`') for s in case['expect']['requiredSql']]
                case['reference']['predicate']=case['reference']['predicate'].replace('e.ZJLXMainNetTur','NULLIF(e.ZJLXMainNetTur,-999999)')
        self.assertEqual(expected,new['cases'])

    def test_field_rule_is_the_existing_project_rule_and_does_not_claim_official_approval(self):
        registry=json.loads((ROOT/'src/main/resources/stock-slot-registry-v1.json').read_text(encoding='utf-8'))
        metric=next(m for m in registry['indicators'] if m['name']=='主力净流入')
        rule=json.loads((ROOT/'data/doris/config/main-net-turnover-rule-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(metric['sentinelValues'],rule['missingValues']['sentinelValues'])
        self.assertEqual(metric['scale']['divide'],rule['scale']['divide'])
        self.assertEqual('PENDING',rule['officialSentinelConfirmation'])


if __name__=='__main__':unittest.main(verbosity=2)
