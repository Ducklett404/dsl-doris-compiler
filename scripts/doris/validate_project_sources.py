"""Publish project-only source capabilities without modifying source data or official registration."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris, sql_literal


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def metadata(java, registry=None):
    command = [java, '-Dfile.encoding=UTF-8', '-cp', str(ROOT / 'target/dsl-doris-compiler.jar'), str(ROOT / 'scripts/doris/ProjectSourceRegistry.java')]
    if registry:
        command.append(str(registry))
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    return json.loads(completed.stdout)


def definition(client, qualified, kind):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*', qualified) or kind not in ('VIEW', 'TABLE'):
        raise ValueError('Unsafe source identifier')
    result = subprocess.run(client.prefix + ['exec', '-i', 'dsl-doris-official', 'mysql',
        '--defaults-extra-file=/run/dsl-client.cnf', '--batch', '--skip-column-names'],
        input='SHOW CREATE ' + kind + ' ' + qualified + ';\n', capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr)
    rows = result.stdout.splitlines()
    if len(rows) != 1:
        raise ValueError('Expected one escaped source definition')
    cells = rows[0].split('\t')
    if len(cells) < 2 or cells[0] != qualified.split('.')[1]:
        raise ValueError('Unexpected source definition')
    escapes = {'0': '\0', 'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', '\\': '\\'}
    text = re.sub(r'\\([0nrtb\\])', lambda m: escapes[m[1]], cells[1])
    if len(text) < 80 or not text.startswith('CREATE '):
        raise ValueError('Incomplete source definition')
    return text


def capture_sources(client, meta, expected):
    sources, details = {}, {}
    for key, table in meta['tables'].items():
        qualified = table['qualifiedName']
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*', qualified):
            raise ValueError('Unsafe compiler registry source')
        database, name = qualified.split('.')
        try:
            result = client.query('SELECT TABLE_TYPE FROM information_schema.tables WHERE TABLE_SCHEMA=' + sql_literal(database) + ' AND TABLE_NAME=' + sql_literal(name))
            if len(result) != 1:
                raise ValueError('Missing source')
            kind = 'VIEW' if result[0][0] == 'VIEW' else 'TABLE'
            # Same read-only metadata available to the runtime reader; SHOW CREATE requires write privileges in Doris.
            view_hash = ''
            if kind == 'VIEW':
                view = client.query('SELECT SHA2(VIEW_DEFINITION,256) FROM information_schema.views WHERE TABLE_SCHEMA=' + sql_literal(database) + ' AND TABLE_NAME=' + sql_literal(name))
                if len(view) != 1 or not re.fullmatch('[0-9a-f]{64}', view[0][0]): raise ValueError('Missing view definition')
                view_hash = view[0][0]
            schema = client.query('SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION FROM information_schema.columns WHERE TABLE_SCHEMA=' + sql_literal(database) + ' AND TABLE_NAME=' + sql_literal(name) + ' ORDER BY ORDINAL_POSITION')
            if not schema or any(len(row)!=4 or any(v=='NULL' or '\t' in v or '\n' in v or '\r' in v for v in row) for row in schema):
                raise ValueError('Unexpected source schema metadata')
            text = 'project-source-definition-v1\n' + kind + '\n' + view_hash + '\n' + ''.join('\t'.join(row)+'\n' for row in schema)
            count = int(client.query('SELECT COUNT(*) FROM ' + qualified)[0][0])
            keys = [table['fields'][k] for k in table['joinKeys']]
            columns = {row[0] for row in client.query('DESC ' + qualified)}
            missing = set(table['fields'].values()) - columns
            duplicate = int(client.query('SELECT COUNT(*) FROM (SELECT ' + ','.join(keys) + ' FROM ' + qualified + ' GROUP BY ' + ','.join(keys) + ' HAVING COUNT(*)>1 LIMIT 1) duplicate_keys')[0][0])
            null_keys = int(client.query('SELECT COUNT(*) FROM ' + qualified + ' WHERE ' + ' OR '.join(k + ' IS NULL' for k in keys))[0][0])
            ready = count == expected[key] and not missing and not duplicate and not null_keys
            sources[key] = dict(qualifiedName=qualified, kind=kind, status='PROJECT_READY' if ready else 'BLOCKED', rows=count,
                                definitionSha256=hashlib.sha256(text.encode()).hexdigest())
            details[key] = dict(expectedRows=expected[key], rows=count, missingColumns=sorted(missing), duplicateKeyGroups=duplicate, nullKeys=null_keys)
        except Exception as error:
            sources[key] = dict(qualifiedName=qualified, kind='TABLE', status='BLOCKED', rows=0, definitionSha256='0'*64)
            details[key] = dict(error=str(error))
    return sources, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json')
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='D:/Java/jdk-21/bin/java.exe')
    args = parser.parse_args()
    folder = args.output_dir.resolve()
    if (folder / 'project-validation.json').exists() or (folder / 'source-validation-report.json').exists():
        raise ValueError('Use a fresh output directory')
    folder.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    integrity = []
    for name, item in manifest['files'].items():
        path = ROOT.parent / item['relativePath']
        actual = digest(path)
        if actual != item['sha256'] or path.stat().st_size != item['bytes']:
            raise ValueError('Immutable source CSV mismatch: ' + name)
        integrity.append(dict(table=name, sha256=actual, status='PASS'))
    client = WslDoris(args.distribution, 'dsl-doris-official')
    registry_before = client.query('SELECT * FROM newzl.data_snapshot_registry')
    meta = metadata(args.java)
    expected = {k: manifest['files'][v]['rows'] for k, v in [('basic','hsj_stock_hq_basic'),('extension','hsj_stock_hq_ext'),('code','hsj_stock_code_info')]}
    raw_counts = {key:int(client.query('SELECT COUNT(*) FROM newzl.'+name)[0][0]) for key,name in
        [('basic','hsj_stock_hq_basic'),('extension','hsj_stock_hq_ext'),('code','hsj_stock_code_info')]}
    sources, details = capture_sources(client, meta, expected)
    basic = sources['basic']['qualifiedName']
    extension = sources['extension']['qualifiedName']
    numeric = client.query('SELECT SUM(CASE WHEN closePrice<0 OR volume<0 OR turnoverAmount<0 OR highPrice<lowPrice THEN 1 ELSE 0 END),'
        'SUM(CASE WHEN closePrice<lowPrice OR closePrice>highPrice THEN 1 ELSE 0 END),MIN(bizdate),MAX(bizdate) FROM ' + basic)[0]
    if int(numeric[0]) or list(numeric[2:]) != [manifest['files']['hsj_stock_hq_basic']['dateMin'], manifest['files']['hsj_stock_hq_basic']['dateMax']]:
        sources['basic']['status'] = 'BLOCKED'
    extension_dates = list(client.query('SELECT MIN(bizdate),MAX(bizdate) FROM ' + extension)[0])
    if extension_dates != [manifest['files']['hsj_stock_hq_ext']['dateMin'], manifest['files']['hsj_stock_hq_ext']['dateMax']]:
        sources['extension']['status'] = 'BLOCKED'
    yearly = []
    # Global orphan warnings come from untouched raw tables even if an optional semantic source is blocked.
    for year in range(int(manifest['files']['hsj_stock_hq_ext']['dateMin'][:4]), int(manifest['files']['hsj_stock_hq_ext']['dateMax'][:4]) + 1):
        start, end = f'{year}-01-01', f'{year+1}-01-01'
        rows = int(client.query(f"SELECT COUNT(*) FROM newzl.hsj_stock_hq_ext e LEFT ANTI JOIN newzl.hsj_stock_hq_basic b ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate AND b.bizdate>='{start}' AND b.bizdate<'{end}' WHERE e.bizdate>='{start}' AND e.bizdate<'{end}'")[0][0])
        yearly.append(dict(year=year, rows=rows))
    orphan = sum(row['rows'] for row in yearly)
    certificate = dict(formatVersion='project-data-validation-v1', status='PROJECT_READY_WITH_LIMITATIONS',
        snapshotId=manifest['snapshotId'], contractVersion=manifest['contractVersion'], manifestSha256=digest(args.manifest),
        registryFingerprint=meta['registryFingerprint'], definitionAuthority='PROJECT_INTERNAL', sources=sources,
        extensionWithoutBasic=orphan, closeOutsideRange=int(numeric[1]), limitations=[
            '本次使用项目已冻结的字段单位、公式与缺值约定，官方口径未获额外确认。',
            '证券范围以基础行情为准。无法关联基础行情的衍生记录完整保留，不用于补造基础行情。',
            '缺失字段、-999999 资金哨兵、零分母、历史不足及平坦 position 区间按原契约返回 NULL。',
            '行业字段在现有数据中不可用；项目入口拒绝行业查询。财务等缺少来源的功能仍拒绝。',
            '这是项目内部按依赖验证的运行证据，不登记 VALIDATED 快照，不代表官方验收。',
            '原始数据按不可变快照管理。运行账户只读；外部装载修改数据后必须重新验证，行数和表/视图定义在每次查询时复核。'])
    report = dict(purpose='PROJECT_SOURCE_CAPABILITY_VALIDATION', sources=details, numericChecks=numeric, extensionDateRange=extension_dates, rawSourceRows=raw_counts,
        yearlyExtensionWithoutBasic=yearly, sourceIntegrity=integrity, definitionAuthority='PROJECT_INTERNAL',
        officialRegistryUnchanged=registry_before == client.query('SELECT * FROM newzl.data_snapshot_registry'),
        jarSha256=digest(ROOT / 'target/dsl-doris-compiler.jar'), manifestSha256=certificate['manifestSha256'],
        completedAtUtc=datetime.now(timezone.utc).isoformat())
    if not report['officialRegistryUnchanged'] or raw_counts != expected or sources['basic']['status'] != 'PROJECT_READY':
        report['status'] = 'BLOCKED'
    else:
        temporary = folder / 'project-validation.pending.json'
        temporary.write_text(json.dumps(certificate, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(folder / 'project-validation.json')
        report.update(status='PROJECT_READY_WITH_LIMITATIONS', certificateSha256=digest(folder / 'project-validation.json'))
    (folder / 'source-validation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'sources': {k:v['status'] for k,v in sources.items()}, 'extensionWithoutBasic': orphan}))
    return 0 if report['status'] == 'PROJECT_READY_WITH_LIMITATIONS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
