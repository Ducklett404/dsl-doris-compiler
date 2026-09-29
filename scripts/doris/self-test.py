#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors = []
ddl = (ROOT / 'data/doris/ddl/001_rebuild_tables.sql').read_text(encoding='utf-8')
view = (ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8')
loader = (ROOT / 'scripts/doris/load-csv.ps1').read_text(encoding='utf-8')
normalizer = (ROOT / 'scripts/doris/normalize_csv.py').read_text(encoding='utf-8')
contract = json.loads((ROOT / 'data/doris/config/data-contract-v1.json').read_text(encoding='utf-8'))
manifest_path = ROOT / 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else None

for table in ('hsj_stock_code_info', 'hsj_stock_hq_basic', 'hsj_stock_hq_ext'):
    if f'CREATE TABLE {table}' not in ddl:
        errors.append(f'missing table {table}')
for required in ('quantRatio INT', 'firstLimitUpTime DATETIME', 'lastFDownTime DATETIME'):
    if required not in ddl:
        errors.append(f'missing corrected DDL fragment: {required}')
for forbidden in ('open_qfq', 'close_qfq', 'quanRatio INT'):
    if forbidden in ddl:
        errors.append(f'forbidden physical field: {forbidden}')
for formula in ('marketValue', 'listedMarketValue', 'risePct', 'avgPx', 'openQfq', 'closeHfq'):
    if not re.search(rf'\b{formula}\b', view):
        errors.append(f'missing semantic formula: {formula}')
if contract['scales']['price']['divisor'] != 10000 or contract['scales']['amount']['divisor'] != 100:
    errors.append('scale contract changed unexpectedly')
if 'normalize_csv.py' not in loader or 'converted.append(r"\\N")' not in normalizer or "strict_mode:true" not in loader or "max_filter_ratio:0" not in loader:
    errors.append('CSV empty-to-NULL strict load contract is missing')

def ddl_columns(table: str) -> list[str]:
    match = re.search(rf'CREATE TABLE {table}\s*\((.*?)\)\s*UNIQUE KEY', ddl, re.S)
    if not match:
        return []
    return [part.strip().split()[0] for part in match.group(1).split(',')]

if manifest:
    for table, info in manifest['files'].items():
        actual = ddl_columns(table)
        if actual != info['header']:
            errors.append(f'CSV/DDL columns differ for {table}: {actual} != {info["header"]}')
    expected = {'hsj_stock_code_info': 5686, 'hsj_stock_hq_basic': 13650347, 'hsj_stock_hq_ext': 6170822}
    for table, rows in expected.items():
        if manifest['files'][table]['rows'] != rows:
            errors.append(f'unexpected snapshot row count for {table}')
    scale_error = manifest['files']['hsj_stock_hq_basic']['avgPriceVsCloseMeanAbsoluteRelativeError']
    if scale_error is None or scale_error >= 0.02:
        errors.append(f'price/amount scale evidence failed: {scale_error}')

if errors:
    print('\n'.join('FAIL: ' + x for x in errors))
    sys.exit(1)
print('PASS: CSV headers, DDL, naming, DATETIME, snapshot counts, scaling and derived formulas are consistent.')
