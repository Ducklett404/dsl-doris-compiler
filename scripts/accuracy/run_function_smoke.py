#!/usr/bin/env python3
"""Compile and execute one representative SQL query for every function family."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from run_correctness import Doris, bind_sql, compile_case


ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "indicator-ma": "indicator('京', '', '5日均线', '2026-04-14', '', '', '') > 1",
    "rank-row-number": "rank('京', '', '收盘价', 'desc:row_number', '2026-04-14', '', '', '') <= 3",
    "queryData": "indicator('京', '', '收盘价', '2026-04-14', '', '', '') > queryData('京', '920690', '收盘价', '2026-04-14', '')",
    "record-high": "record_high('京', '', '最高价', '5日', '2026-04-14', '', '', '') = True",
    "record-low": "record_low('京', '', '最低价', '5日', '2026-04-14', '', '', '') = True",
    "cross-above": "cross_above('京', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
    "position": "position('京', '', '收盘价', '5日', '2026-04-14', '', '', '') = '高'",
    "belong-industry": "indicator('京', '', '收盘价', '2026-04-14', '', '', '') > belong_industry('京', '', '收盘价', '2026-04-14', 'AVG')",
    "close-together": "close_together('京', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
    "reset": "reset('京', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
    "golden-cross": "golden_cross('京', '', '收盘价', '开盘价', '2026-04-14', '', '') = True",
    "CONS": "indicator('京', '', '收盘价', '2026-04-14', '', '', 'CONS>=3日') > 1",
    "CONS-exact": "indicator('京', '', '收盘价', '2026-04-14', '', '', 'CONS=2日') > 1",
    "EXIST": "indicator('京', '', '成交量', '2026-04-14', '', '', 'EXIST>=3日') > 0",
    "EXIST-exact": "indicator('京', '', '成交量', '2026-04-14', '', '', 'EXIST=3日') > 0",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--jar", type=Path, default=Path("target/dsl-doris-compiler.jar"))
    parser.add_argument("--docker", default=r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    parser.add_argument("--container", default="doris")
    parser.add_argument("--user", default="dsl_loader")
    parser.add_argument("--mysql-port", type=int, default=9030)
    parser.add_argument("--java", default="java")
    parser.add_argument("--output", type=Path, default=Path("reports/accuracy/stock-slot-functions-v1-smoke.json"))
    args = parser.parse_args()
    root = args.repo.resolve()
    password = os.environ.get("DORIS_PASSWORD")
    if not password:
        raise SystemExit("DORIS_PASSWORD is required")
    jar = (root / args.jar).resolve() if not args.jar.is_absolute() else args.jar
    output = (root / args.output).resolve() if not args.output.is_absolute() else args.output
    doris = Doris(args.docker, args.container, args.user, args.mysql_port, password)
    results = []
    with tempfile.TemporaryDirectory(prefix="stock-slot-functions-") as directory:
        source = Path(directory) / "case.dsl"
        for name, dsl in CASES.items():
            row = {"name": name, "dsl": dsl}
            try:
                artifact = compile_case(args.java, jar, dsl, source)
                rows = doris.query(bind_sql(artifact["sql"], artifact["bindings"]))
                row.update(status="PASS", rowCount=len(rows), windowContracts=artifact["windowContracts"])
            except Exception as error:
                row.update(status="FAIL", error=str(error))
            results.append(row)
    report = {
        "executedAtUtc": datetime.now(timezone.utc).isoformat(),
        "snapshotId": "stock-20060104-20260414-v1",
        "total": len(results),
        "passed": sum(row["status"] == "PASS" for row in results),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"total": report["total"], "passed": report["passed"]}, ensure_ascii=False))
    return 0 if report["passed"] == report["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
