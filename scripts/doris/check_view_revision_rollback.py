"""Round-trip full view backups on a disposable empty schema, never official data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

from apply_numeric_view_revision import ROOT, WslDoris, view_definition

BASE = 'a0f7260c3dfd1b825a7c6af5f02b859645654a80'
DDL = 'data/doris/ddl/002_semantic_view.sql'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    old = subprocess.run(['git', 'show', BASE + ':' + DDL], cwd=ROOT,
                         capture_output=True, check=True).stdout.decode('utf-8')
    freeze = json.loads((ROOT / 'config/acceptance/history/stock-slot-phase1-scope-v1.0.1.json').read_text())
    canonical = old.replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')
    assert hashlib.sha256(canonical).hexdigest() == freeze['ddlHashes'][DDL]
    rollback = args.output_dir / 'rollback-v1.0.1.sql'
    rollback.write_bytes(canonical)
    report = {'purpose': 'SYNTHETIC_VIEW_BACKUP_ROUNDTRIP', 'checks': [],
              'rollbackProvenance': 'RECONSTRUCTED_FROM_PREVIOUS_FROZEN_GIT_DDL',
              'rollbackGitCommit': BASE, 'rollbackSha256': hashlib.sha256(canonical).hexdigest()}
    client = WslDoris(args.distribution, 'dsl-doris-official')
    database = 'dsl_view_revision_' + uuid.uuid4().hex[:12]
    registry = client.query('SELECT * FROM newzl.data_snapshot_registry')
    created = False

    def check(name, condition):
        report['checks'].append({'name': name, 'status': 'PASS' if condition else 'FAIL'})
        if not condition:
            raise AssertionError(name)

    def apply(sql):
        client.query(sql.replace('USE newzl;', 'USE ' + database + ';'))

    try:
        client.query('CREATE DATABASE ' + database)
        created = True
        apply((ROOT / 'data/doris/ddl/001_rebuild_tables.sql').read_text())
        apply(old)
        client.query('INSERT INTO ' + database + ".hsj_stock_hq_basic(mktcode,tgtcode,bizdate,lastPx,preClosePx,closePx) VALUES (0,'000001','2026-04-14',12400,12300,12400)")
        client.query('INSERT INTO ' + database + ".hsj_stock_hq_ext(mktcode,tgtcode,bizdate,ZJLXMainNetTur) VALUES (0,'000001','2026-04-14',-999999)")
        names = ['v_hsj_stock_hq_basic', 'v_hsj_stock_hq_ext']
        before = {name: view_definition(client, name, database) for name in names}
        schemas = {name: client.query('DESC ' + database + '.' + name) for name in names}
        values = {name: client.query('SELECT * FROM ' + database + '.' + name) for name in names}
        check('multiline-definition-preserved', all('\n' in s and 'SELECT' in s for s in before.values()))
        old_type = [row[1] for row in client.query('DESC ' + database + '.v_hsj_stock_hq_basic') if row[0] == 'risePct']
        check('old-decimal-rise-type', old_type == ['decimal(28,5)'])
        apply((ROOT / DDL).read_text())
        new_type = [row[1] for row in client.query('DESC ' + database + '.v_hsj_stock_hq_basic') if row[0] == 'risePct']
        check('new-double-rise-type', new_type == ['double'])
        for name in names:
            client.query('USE ' + database + '; DROP VIEW ' + name + '; ' + before[name])
        after = {name: view_definition(client, name, database) for name in names}
        report['definitionsBefore'] = before
        report['definitionsAfter'] = after
        report['showCreateTextStable'] = before == after
        # Doris regenerates expression formatting during CREATE VIEW. Compare
        # every typed column and actual fixture value rather than display text.
        check('full-backup-restores-schema-and-values', all(
            schemas[name] == client.query('DESC ' + database + '.' + name)
            and values[name] == client.query('SELECT * FROM ' + database + '.' + name) for name in names))
        check('official-registry-preserved', registry == client.query('SELECT * FROM newzl.data_snapshot_registry'))
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        raise
    finally:
        if created:
            client.query('DROP DATABASE ' + database)
            report['fixtureCleanup'] = 'DONE'
        (args.output_dir / 'backup-roundtrip.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('VIEW_BACKUP_ROUNDTRIP_PASS: 5 checks; rollback source verified against the previous freeze')


if __name__ == '__main__':
    main()
