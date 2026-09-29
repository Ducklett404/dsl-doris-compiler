#!/usr/bin/env python3
"""Profile and lock the three supplied CSVs without third-party dependencies."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

FILES = {
    "hsj_stock_code_info": Path("股票代码表/hsj_stock_code_info.csv"),
    "hsj_stock_hq_basic": Path("行情基本数据宽表/hsj_stock_hq_basic.csv"),
    "hsj_stock_hq_ext": Path("行情衍生数据/hsj_stock_hq_ext.csv"),
}
KEYS = {
    "hsj_stock_code_info": ("mktcode", "tgtcode"),
    "hsj_stock_hq_basic": ("mktcode", "tgtcode", "bizdate"),
    "hsj_stock_hq_ext": ("mktcode", "tgtcode", "bizdate"),
}
TIME_FIELDS = ("firstLimitUpTime", "lastLimitUpTime", "firstLimitDownTime", "lastLimitDownTime", "lastFUpTime", "lastFDownTime")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_file(name: str, path: Path) -> dict:
    rows = 0
    date_min = date_max = None
    adjacent_duplicates = 0
    monotonic = True
    previous = None
    nulls: dict[str, int] = {}
    sentinels: dict[str, int] = {}
    time_samples: dict[str, list[str]] = {}
    factor_tuples: set[tuple[str, ...]] = set()
    scale_n = 0
    scale_abs_error = 0.0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"missing header: {path}")
        nulls = {field: 0 for field in reader.fieldnames}
        sentinels = {field: 0 for field in reader.fieldnames}
        for row in reader:
            rows += 1
            key = tuple(row[k] for k in KEYS[name])
            if previous is not None:
                adjacent_duplicates += key == previous
                monotonic = monotonic and key >= previous
            previous = key
            for field, value in row.items():
                if value == "": nulls[field] += 1
                if value == "-999999": sentinels[field] += 1
            if "bizdate" in row:
                value = row["bizdate"]
                date_min = value if date_min is None or value < date_min else date_min
                date_max = value if date_max is None or value > date_max else date_max
            if name == "hsj_stock_hq_basic":
                for field in TIME_FIELDS:
                    value = row[field]
                    if value and len(time_samples.setdefault(field, [])) < 5:
                        time_samples[field].append(value)
                factors = tuple(row[x] for x in ("qfqMulti", "qfqAdd", "hfqMulti", "hfqAdd"))
                factor_tuples.add(factors)
                try:
                    close, volume, amount = int(row["closePx"]), int(row["volume"]), int(row["turnover"])
                    if close > 0 and volume > 0 and amount > 0:
                        ratio = (amount / 100.0 / volume) / (close / 10000.0)
                        scale_abs_error += abs(ratio - 1.0)
                        scale_n += 1
                except (TypeError, ValueError):
                    pass
    return {
        "relativePath": str(FILES[name]).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "rows": rows,
        "header": reader.fieldnames,
        "dateMin": date_min,
        "dateMax": date_max,
        "nullCounts": {k: v for k, v in nulls.items() if v},
        "sentinelMinus999999Counts": {k: v for k, v in sentinels.items() if v},
        "keyOrderMonotonic": monotonic,
        "adjacentDuplicateKeys": adjacent_duplicates,
        "timeSamples": time_samples,
        "factorTuples": sorted(factor_tuples),
        "avgPriceVsCloseMeanAbsoluteRelativeError": scale_abs_error / scale_n if scale_n else None,
        "avgPriceScaleSampleCount": scale_n,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("profile")
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--snapshot-id", default="stock-20060104-20260414-v1")
    args = parser.parse_args()
    files = {}
    for name, relative in FILES.items():
        path = args.data_root / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        files[name] = profile_file(name, path)
    manifest = {
        "snapshotId": args.snapshot_id,
        "contractVersion": "1.0.0",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshotId": args.snapshot_id, "output": str(args.output), "rows": {k: v["rows"] for k, v in files.items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
