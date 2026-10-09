"""Preserve originals, verify the frozen manifest and create bounded load parts."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(source_root, output, manifest_path, chunk_rows=250000):
    if not 1 <= chunk_rows <= 1000000:
        raise ValueError('chunk_rows must be between 1 and 1000000')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Use an empty output directory; recovery never deletes or overwrites files')
    for table, item in manifest['files'].items():
        source = source_root / item['relativePath']
        if source.stat().st_size != item['bytes'] or digest(source) != item['sha256']:
            raise ValueError('Frozen source mismatch: ' + table)
    report = {'snapshotId': manifest['snapshotId'], 'manifestSha256': digest(manifest_path), 'files': {}}
    for table, item in manifest['files'].items():
        folder = output / table
        folder.mkdir()
        parts, samples = [], []
        target = None
        try:
            with (source_root / item['relativePath']).open('r', encoding='utf-8-sig', newline='') as stream:
                reader = csv.reader(stream)
                header = next(reader)
                if header != item['header']:
                    raise ValueError('Header mismatch: ' + table)
                stride = max(1, item['rows'] // 32)
                rows, nulls = 0, 0
                for row in reader:
                    if len(row) != len(header):
                        raise ValueError(f'{table}: wrong field count at row {rows + 2}')
                    if rows % chunk_rows == 0:
                        if target:
                            target.close()
                            parts[-1]['sha256'] = digest(folder / parts[-1]['file'])
                        name = f'part-{len(parts):05}.csv'
                        target = (folder / name).open('x', encoding='utf-8', newline='')
                        writer = csv.writer(target, lineterminator='\n')
                        writer.writerow(header)
                        parts.append({'file': name, 'rows': 0})
                    if rows % stride == 0 or rows == item['rows'] - 1:
                        samples.append(dict(zip(header, row)))
                    converted = [r'\N' if value == '' else value for value in row]
                    nulls += sum(value == '' for value in row)
                    writer.writerow(converted)
                    rows += 1
                    parts[-1]['rows'] += 1
                    if rows % 1000000 == 0:
                        print(f'{table}: prepared {rows:,} rows', flush=True)
                if rows != item['rows']:
                    raise ValueError(f'{table}: expected {item["rows"]} rows, read {rows}')
            if target:
                target.close()
                target = None
                parts[-1]['sha256'] = digest(folder / parts[-1]['file'])
            original = source_root / item['relativePath']
            if original.stat().st_size != item['bytes'] or digest(original) != item['sha256']:
                raise ValueError('Source changed during preparation: ' + table)
            result = {'rows': rows, 'nullFields': nulls, 'header': header,
                      'sourceSha256': item['sha256'], 'parts': parts, 'samples': samples}
            (folder / 'parts.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            report['files'][table] = result
            print(f'{table}: PASS ({rows:,} rows, {len(parts)} parts)', flush=True)
        finally:
            if target:
                target.close()
    report['status'] = 'PASS'
    (output / 'prepared-snapshot.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json')
    parser.add_argument('--chunk-rows', type=int, default=250000)
    args = parser.parse_args()
    prepare(args.data_root, args.output_dir, args.manifest, args.chunk_rows)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
