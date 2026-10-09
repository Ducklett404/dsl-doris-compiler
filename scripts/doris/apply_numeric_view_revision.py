"""Back up and upgrade only semantic views in the owned diagnostic instance."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import re
import subprocess
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/accuracy'))
from run_correctness import WslDoris

def view_definition(client, name, database='newzl'):
    if database != 'newzl' and re.fullmatch(r'dsl_view_revision_[0-9a-f]{12}', database) is None:
        raise ValueError('Unexpected view database')
    if name not in ('v_hsj_stock_hq_basic', 'v_hsj_stock_hq_ext'):
        raise ValueError('Unexpected semantic view')
    # Batch escaping keeps multiline definitions inside a single result cell.
    command = client.prefix + ['exec', '-i', 'dsl-doris-official', 'mysql',
        '--defaults-extra-file=/run/dsl-client.cnf', '--port=' + str(client.query_port), '--batch', '--skip-column-names']
    completed = subprocess.run(command, input='SHOW CREATE VIEW ' + database + '.' + name + ';\n',
        text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=30)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip())
    rows = completed.stdout.splitlines()
    if len(rows) != 1:
        raise ValueError('Expected one escaped view definition')
    cells = rows[0].split('\t')
    if len(cells) < 2 or cells[0] != name:
        raise ValueError('Unexpected SHOW CREATE VIEW result')
    escapes = {'0': '\0', 'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', '\\': '\\'}
    definition = re.sub(r'\\([0ntrb\\])', lambda match: escapes[match[1]], cells[1])
    if (not definition.startswith('CREATE VIEW `' + name + '`')
            or re.search(r'\bAS\s+SELECT\b', definition, re.IGNORECASE) is None):
        raise ValueError('Incomplete rollback definition')
    return definition


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--distribution',default='dsl-doris-official-01a104f9')
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    if (args.output_dir/'views-before.json').exists() or (args.output_dir/'view-upgrade.json').exists():
        raise ValueError('Use a fresh output directory to preserve rollback evidence')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    client=WslDoris(args.distribution,'dsl-doris-official')
    names=['v_hsj_stock_hq_basic','v_hsj_stock_hq_ext']
    originals={name:view_definition(client,name) for name in names}
    counts_sql="SELECT 'basic',COUNT(*) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',COUNT(*) FROM newzl.hsj_stock_hq_ext UNION ALL SELECT 'code',COUNT(*) FROM newzl.hsj_stock_code_info"
    counts=dict(client.query(counts_sql));registry=client.query('SELECT * FROM newzl.data_snapshot_registry')
    dates_sql="SELECT 'basic',MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_basic UNION ALL SELECT 'ext',MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_ext"
    dates=sorted(client.query(dates_sql))
    if registry:raise ValueError('Expected an unregistered official diagnostic snapshot')
    backup={'purpose':'SEMANTIC_VIEW_ROLLBACK_BACKUP','capturedAtUtc':datetime.now(timezone.utc).isoformat(),
            'originalViews':originals,'sourceCounts':counts,'sourceDates':dates,'registryRows':registry}
    (args.output_dir/'views-before.json').write_text(json.dumps(backup,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    source=ROOT/'data/doris/ddl/002_semantic_view.sql'
    report={'purpose':'OWNED_DIAGNOSTIC_VIEW_UPGRADE_NO_SOURCE_REWRITE','ddlSha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    try:
        client.query(source.read_text(encoding='utf-8'))
        after=dict(client.query(counts_sql));registered=client.query('SELECT * FROM newzl.data_snapshot_registry')
        dates_after=sorted(client.query(dates_sql))
        if counts!=after or registered!=registry or dates_after!=dates:raise ValueError('Source counts, dates or snapshot registry changed')
        numeric_types={r[0]:r[1].lower().replace(' ','') for r in client.query('DESCRIBE newzl.v_hsj_stock_hq_basic')
                       if r[0] in ('lastPrice','preClosePrice','openPrice','highPrice','lowPrice','closePrice','avgPx')}
        expected_types={name:'decimal(19,4)' for name in ('lastPrice','preClosePrice','openPrice','highPrice','lowPrice','closePrice')}
        expected_types['avgPx']='decimal(38,21)'
        if numeric_types!=expected_types:raise ValueError('Unexpected normalized price precision')
        report.update(status='PASS',sourceCountsAfter=after,sourceDatesAfter=dates_after,
                      normalizedNumericTypes=numeric_types,registeredSnapshotCount=len(registered),
                      viewRisePctType=[r for r in client.query('DESCRIBE newzl.v_hsj_stock_hq_basic') if r[0]=='risePct'],
                      upgradedViews={name:view_definition(client,name) for name in names})
    except Exception as error:
        report.update(status='FAIL',error=str(error))
        for name in names:
            client.query('DROP VIEW IF EXISTS newzl.'+name)
            client.query('USE newzl;\n'+originals[name])
        report['rollback']='DONE'
        raise
    finally:
        (args.output_dir/'view-upgrade.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('VIEW_UPGRADE_PASS: source counts unchanged; official registry remains empty')

if __name__=='__main__':main()
