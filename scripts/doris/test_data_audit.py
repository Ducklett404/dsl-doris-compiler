import csv
import json
from pathlib import Path
import tempfile
import unittest
import duckdb
from audit_official_data import NAMES, ddl_columns, digest, run_audit
from check_local_results import portable_identifiers


class AuditRegressionTest(unittest.TestCase):
    def fixture(self, root, duplicate=False, orphan=False, invalid=False):
        schema=ddl_columns();meta={'snapshotId':'unit-test','files':{}}
        for name in NAMES:
            header=list(schema[name]);row={field:'' for field in header}
            row.update(mktcode='1',tgtcode='000001')
            if name==NAMES[0]:row['name']='测试证券'
            else:row['bizdate']='2026-04-14'
            if name==NAMES[1]:row.update(closePx='invalid' if invalid else '20000',volume='100',turnover='20000',qfqMulti='1',qfqAdd='0',hfqMulti='1',hfqAdd='0')
            rows=[row]
            if name==NAMES[1] and duplicate:rows.append(dict(row))
            if name==NAMES[2] and orphan:rows.append({**row,'bizdate':'2026-04-15'})
            path=root/(name+'.csv')
            with path.open('w',encoding='utf-8',newline='') as fh:
                writer=csv.DictWriter(fh,fieldnames=header);writer.writeheader();writer.writerows(rows)
            meta['files'][name]={'header':header,'rows':len(rows),'sha256':digest(path),'nullCounts':{field:sum(r[field]=='' for r in rows) for field in header},
                'sentinelMinus999999Counts':{},'dateMin':None if name==NAMES[0] else min(r['bizdate'] for r in rows),'dateMax':None if name==NAMES[0] else max(r['bizdate'] for r in rows)}
        manifest=root/'manifest.json';manifest.write_text(json.dumps(meta),encoding='utf-8')
        return manifest

    def audit(self, **options):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=self.fixture(root,**options)
            result=run_audit(root,manifest,root/'audit.duckdb',root/'out')
            con=duckdb.connect(str(root/'audit.duckdb'))
            code=con.execute('SELECT tgtcode,name FROM newzl.hsj_stock_code_info').fetchone();con.close()
            return result,code

    def test_clean_input_preserves_code_and_unicode(self):
        report,code=self.audit()
        self.assertEqual('PASS_WITH_LIMITATIONS',report['status'])
        self.assertEqual(('000001','测试证券'),code)

    def test_global_duplicate_keys_fail_gate(self):
        report,_=self.audit(duplicate=True)
        self.assertEqual('FAIL',report['status'])
        self.assertEqual(1,report['tables'][NAMES[1]]['duplicateExtraRows'])

    def test_orphan_extension_rows_are_not_silently_discarded(self):
        report,_=self.audit(orphan=True)
        self.assertEqual('FAIL',report['status'])
        self.assertEqual(2,report['tables'][NAMES[2]]['rows'])
        self.assertEqual(1,report['relationships']['extensionWithoutBasic']['rows'])

    def test_bad_numeric_source_is_reported_before_casting(self):
        report,_=self.audit(invalid=True)
        self.assertEqual('FAIL',report['status'])
        self.assertEqual(1,report['tables'][NAMES[1]]['invalidTypeCounts']['closePx'])

    def test_dialect_adapter_does_not_modify_literal_backticks(self):
        self.assertEqual('SELECT "value" WHERE "name"=\'a`b\' AND "code"=\'x\'\'`y\'',
            portable_identifiers("SELECT `value` WHERE `name`='a`b' AND `code`='x''`y'"))


if __name__=='__main__':unittest.main(verbosity=2)
