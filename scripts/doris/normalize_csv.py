#!/usr/bin/env python3
"""Rewrite empty CSV fields as Doris' explicit NULL token (\\N)."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    nulls = 0
    with args.input.open("r", encoding="utf-8-sig", newline="") as source, args.output.open(
        "x", encoding="utf-8", newline=""
    ) as target:
        reader = csv.reader(source)
        writer = csv.writer(target, lineterminator="\n")
        header = next(reader)
        writer.writerow(header)
        width = len(header)
        for row in reader:
            rows += 1
            if len(row) != width:
                raise ValueError(f"row {rows + 1}: expected {width} fields, got {len(row)}")
            converted = []
            for value in row:
                if value == "":
                    converted.append(r"\N")
                    nulls += 1
                else:
                    converted.append(value)
            writer.writerow(converted)
            if rows % 1_000_000 == 0:
                print(f"normalized {rows:,} rows from {args.input.name}", file=sys.stderr, flush=True)
    print(json.dumps({"file": args.input.name, "rows": rows, "nullFields": nulls}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
