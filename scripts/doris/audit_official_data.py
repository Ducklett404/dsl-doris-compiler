"""Full CSV audit and reusable local database, isolated from the source files.

Requires scripts/doris/requirements-data-audit.txt in a Python virtual environment.
DuckDB is the local audit engine; this does not register a VALIDATED Doris snapshot.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
NAMES = ("hsj_stock_code_info", "hsj_stock_hq_basic", "hsj_stock_hq_ext")
KEYS = {NAMES[0]: ["mktcode", "tgtcode"], NAMES[1]: ["mktcode", "tgtcode", "bizdate"],
        NAMES[2]: ["mktcode", "tgtcode", "bizdate"]}


def qi(value):
    return '"' + value.replace('"', '""') + '"'


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def ddl_columns():
    text = (ROOT / "data/doris/ddl/001_rebuild_tables.sql").read_text(encoding="utf-8")
    output = {}
    for name in NAMES:
        match = re.search(r"CREATE TABLE " + name + r"\s*\((.*?)\n\)", text, re.S)
        output[name] = dict(re.findall(r"(\w+)\s+(VARCHAR\(\d+\)|BIGINT|INT|DOUBLE|BOOLEAN|DATE(?:TIME)?|TINYINT)(?=[\s,])", match[1]))
    return output


def run_audit(data_root, manifest_path, database, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    report = {"startedAt": datetime.now(timezone.utc).isoformat(), "engine": "DuckDB " + duckdb.__version__,
              "snapshotId": manifest["snapshotId"], "database": str(database.resolve()),
              "status": "RUNNING", "tables": {}, "checks": [], "limitations": [
                  "Observed market dates are not an authoritative trading calendar; missing observations do not establish suspension.",
                  "Local audit and SQL evaluation do not validate the Doris dialect or execution environment."]}
    con = duckdb.connect(str(database))
    con.execute("SET memory_limit='4GB'")
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    con.execute("CREATE SCHEMA IF NOT EXISTS newzl")
    schema = ddl_columns()

    def check(name, ok, detail, warning=False):
        report["checks"].append({"name": name, "status": "PASS" if ok else "WARN" if warning else "FAIL", "detail": detail})

    def records(sql):
        cursor = con.execute(sql)
        keys = [x[0] for x in cursor.description]
        return [dict(zip(keys, row)) for row in cursor.fetchall()]

    try:
        for name in NAMES:
            start = time.monotonic()
            expected = manifest["files"][name]
            candidates = list(data_root.rglob(name + ".csv"))
            if len(candidates) != 1:
                raise ValueError(f"Expected one {name}.csv, found {len(candidates)}")
            source = candidates[0]
            print(f"[{name}] hash and schema", flush=True)
            with source.open(encoding="utf-8-sig", newline="") as stream:
                header = next(csv.reader(stream))
            if header != expected["header"] or set(header) != set(schema[name]):
                raise ValueError(f"Unexpected CSV/DDL schema: {name}")
            actual_hash = digest(source)
            check(name + ":sha256", actual_hash == expected["sha256"], actual_hash)
            # Strict CSV parsing: no ignored rows, no automatic type inference of codes.
            source_literal = "'" + source.resolve().as_posix().replace("'", "''") + "'"
            con.execute(f"CREATE OR REPLACE TEMP VIEW audit_input AS SELECT * FROM read_csv({source_literal}, header=true, all_varchar=true, nullstr='', strict_mode=true)")
            expressions = ["COUNT(*)"]
            labels = ["rows"]
            for field in header:
                col = qi(field)
                expressions += [f"COUNT(*) FILTER (WHERE {col} IS NULL)", f"COUNT(*) FILTER (WHERE {col}='-999999')"]
                labels += ["null:" + field, "sentinel:" + field]
                datatype = schema[name][field]
                if datatype.startswith("VARCHAR"):
                    limit = int(re.search(r"\d+", datatype)[0])
                    expression = f"COUNT(*) FILTER (WHERE LENGTH({col})>{limit})"
                else:
                    target = "TIMESTAMP" if datatype == "DATETIME" else datatype
                    expression = f"COUNT(*) FILTER (WHERE {col} IS NOT NULL AND TRY_CAST({col} AS {target}) IS NULL)"
                expressions.append(expression)
                labels.append("invalid:" + field)
            print(f"[{name}] full field scan", flush=True)
            values = dict(zip(labels, con.execute("SELECT " + ",".join(expressions) + " FROM audit_input").fetchone()))
            table = {"path": str(source.resolve()), "bytes": source.stat().st_size, "sha256": actual_hash,
                     "rows": values["rows"], "columns": len(header),
                     "nullCounts": {f: values["null:" + f] for f in header},
                     "sentinelCounts": {f: values["sentinel:" + f] for f in header},
                     "invalidTypeCounts": {f: values["invalid:" + f] for f in header if values["invalid:" + f]}}
            report["tables"][name] = table
            check(name + ":row_count", table["rows"] == expected["rows"], table["rows"])
            check(name + ":types", not table["invalidTypeCounts"], table["invalidTypeCounts"])
            check(name + ":profile_counts", all(table["nullCounts"][f] == expected["nullCounts"].get(f, 0)
                  and table["sentinelCounts"][f] == expected["sentinelMinus999999Counts"].get(f, 0) for f in header), "Full scan vs frozen profile")
            print(f"[{name}] build typed local audit table", flush=True)
            selections = []
            for field in header:
                typ = schema[name][field]
                target = "VARCHAR" if typ.startswith("VARCHAR") else "TIMESTAMP" if typ == "DATETIME" else typ
                selections.append(f"TRY_CAST({qi(field)} AS {target}) AS {qi(field)}")
            con.execute(f"CREATE OR REPLACE TABLE newzl.{name} AS SELECT " + ",".join(selections) + " FROM audit_input")
            keys = ",".join(qi(k) for k in KEYS[name])
            null_key = " OR ".join(qi(k) + " IS NULL" for k in KEYS[name])
            table["nullKeys"] = con.execute(f"SELECT COUNT(*) FROM newzl.{name} WHERE {null_key}").fetchone()[0]
            duplicate_sql = f"SELECT {keys},COUNT(*) n FROM newzl.{name} GROUP BY {keys} HAVING COUNT(*)>1"
            table["duplicateKeyGroups"], table["duplicateExtraRows"] = con.execute(f"SELECT COUNT(*),COALESCE(SUM(n-1),0) FROM ({duplicate_sql})").fetchone()
            table["duplicateExamples"] = records(duplicate_sql + " ORDER BY n DESC LIMIT 10")
            check(name + ":primary_keys", table["nullKeys"] == 0 and table["duplicateExtraRows"] == 0,
                  {k: table[k] for k in ("nullKeys", "duplicateKeyGroups", "duplicateExtraRows")})
            table["marketDistribution"] = records(f'SELECT mktcode,COUNT(*) AS "rows",COUNT(DISTINCT tgtcode) securities FROM newzl.{name} GROUP BY mktcode ORDER BY mktcode')
            if "bizdate" in header:
                table["dateMin"], table["dateMax"] = [str(x) for x in con.execute(f"SELECT MIN(bizdate),MAX(bizdate) FROM newzl.{name}").fetchone()]
                check(name + ":dates", (table["dateMin"], table["dateMax"]) == (expected["dateMin"], expected["dateMax"]), [table["dateMin"], table["dateMax"]])
                coverage = records(f'SELECT bizdate,mktcode,COUNT(*) AS "rows",COUNT(DISTINCT tgtcode) securities FROM newzl.{name} GROUP BY bizdate,mktcode ORDER BY bizdate,mktcode')
                with (output_dir / (name + "-date-coverage.csv")).open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["bizdate", "mktcode", "rows", "securities"])
                    writer.writeheader(); writer.writerows(coverage)
                table["observedDates"] = len({x["bizdate"] for x in coverage})
                table["latestDateCoverage"] = [x for x in coverage if str(x["bizdate"]) == table["dateMax"]]
            table["elapsedSeconds"] = round(time.monotonic() - start, 3)
            print(f"[{name}] done: {table['rows']:,} rows in {table['elapsedSeconds']}s", flush=True)

        print("[relationships] exact full composite-key joins", flush=True)
        basic, ext, code = ("newzl." + x for x in (NAMES[1], NAMES[2], NAMES[0]))
        relationships = {}
        joins = [("extensionWithoutBasic", ext, basic, KEYS[NAMES[1]]),
                 ("basicWithoutExtension", basic, ext, KEYS[NAMES[1]]),
                 ("basicWithoutSecurityInfo", basic, code, KEYS[NAMES[0]]),
                 ("extensionWithoutSecurityInfo", ext, code, KEYS[NAMES[0]])]
        for label, left, right, keys in joins:
            join = " AND ".join(f"a.{qi(k)}=b.{qi(k)}" for k in keys)
            sql = f"SELECT a.* FROM {left} a ANTI JOIN {right} b ON {join}"
            count = con.execute(f"SELECT COUNT(*) FROM ({sql})").fetchone()[0]
            relationships[label] = {"rows": count, "examples": records("SELECT " + ",".join(qi(k) for k in KEYS[NAMES[1]]) + f" FROM ({sql}) LIMIT 10")}
            if label != "basicWithoutExtension":
                check(label, count == 0, count, warning="SecurityInfo" in label)
            print(f"[relationships] {label}: {count:,}", flush=True)
        report["relationships"] = relationships
        numeric = records(f"SELECT COUNT(*) FILTER(WHERE closePx<0) negativeClose, COUNT(*) FILTER(WHERE volume<0) negativeVolume, COUNT(*) FILTER(WHERE turnover<0) negativeTurnover, COUNT(*) FILTER(WHERE highPx<lowPx) highBelowLow, COUNT(*) FILTER(WHERE closePx>highPx OR closePx<lowPx) closeOutsideRange FROM {basic}")[0]
        report["numericChecks"] = numeric
        check("basic_numeric_gate", all(numeric[k] == 0 for k in ("negativeClose", "negativeVolume", "negativeTurnover", "highBelowLow")), numeric)
        check("close_price_range", numeric["closeOutsideRange"] == 0, numeric["closeOutsideRange"], warning=True)
        report["numericExamples"] = records(f"SELECT mktcode,tgtcode,bizdate,openPx,highPx,lowPx,closePx FROM {basic} WHERE closePx<0 OR volume<0 OR turnover<0 OR highPx<lowPx OR closePx>highPx OR closePx<lowPx LIMIT 20")
        scale = records(f"SELECT COUNT(*) sampleRows,AVG(ABS((turnover/100.0/volume)/(closePx/10000.0)-1)) meanAbsoluteRelativeError FROM {basic} WHERE turnover>0 AND volume>0 AND closePx>0")[0]
        report["scaleCrossCheck"] = scale
        check("price_amount_scale_cross_check", scale["sampleRows"] > 0 and scale["meanAbsoluteRelativeError"] < .35, scale)
        report["adjustmentFactorTuples"] = records(f'SELECT qfqMulti,qfqAdd,hfqMulti,hfqAdd,COUNT(*) AS "rows" FROM {basic} GROUP BY ALL ORDER BY "rows" DESC')
        print("[coverage] gaps relative to observed market dates (not suspension classification)", flush=True)
        con.execute(f"CREATE OR REPLACE TEMP TABLE audit_calendar AS SELECT mktcode,bizdate,ROW_NUMBER() OVER(PARTITION BY mktcode ORDER BY bizdate) ordinal FROM (SELECT DISTINCT mktcode,bizdate FROM {basic})")
        gap_sql = f"""WITH spans AS (SELECT mktcode,tgtcode,MIN(bizdate) firstDate,MAX(bizdate) lastDate,COUNT(*) observedRows FROM {basic} GROUP BY mktcode,tgtcode)
            SELECT s.*,c2.ordinal-c1.ordinal+1 expectedMarketDates,c2.ordinal-c1.ordinal+1-s.observedRows missingObservations
            FROM spans s JOIN audit_calendar c1 ON c1.mktcode=s.mktcode AND c1.bizdate=s.firstDate
            JOIN audit_calendar c2 ON c2.mktcode=s.mktcode AND c2.bizdate=s.lastDate"""
        report["observationGaps"] = records(f"SELECT COUNT(*) securities,COUNT(*) FILTER(WHERE missingObservations>0) securitiesWithGaps,SUM(missingObservations) missingObservations FROM ({gap_sql})")[0]
        report["observationGaps"]["examples"] = records(gap_sql + " ORDER BY missingObservations DESC LIMIT 20")
        report["status"] = "FAIL" if any(x["status"] == "FAIL" for x in report["checks"]) else "PASS_WITH_LIMITATIONS"
        con.execute("CREATE OR REPLACE TABLE audit_source_lock(snapshot_id VARCHAR, manifest_sha256 VARCHAR, checked_at TIMESTAMP, status VARCHAR)")
        con.execute("INSERT INTO audit_source_lock VALUES(?,?,CURRENT_TIMESTAMP,?)", [manifest["snapshotId"], digest(manifest_path), report["status"]])
    except Exception as error:
        report["status"] = "ERROR"
        report["error"] = str(error)
        raise
    finally:
        con.close()
        report["completedAt"] = datetime.now(timezone.utc).isoformat()
        (output_dir / "全量数据检查.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"AUDIT_{report['status']}: {output_dir}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=ROOT.parent)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/doris/snapshots/stock-20060104-20260414-v1/manifest.json")
    parser.add_argument("--database", type=Path, default=ROOT / "target/data-audit/official.duckdb")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/data-inspection/2026-10-04")
    args = parser.parse_args()
    report = run_audit(args.data_root, args.manifest, args.database, args.output_dir)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
