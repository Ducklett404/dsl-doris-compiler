#!/usr/bin/env python3
"""Three-layer golden-set evaluator for the stock-slot-v1 executable subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def run(command: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=stdin, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)


def functions(expression: dict[str, Any]) -> list[str]:
    kind = expression.get("kind")
    if kind == "FunctionCall":
        result = [expression["name"]]
        for argument in expression.get("arguments", []):
            result.extend(functions(argument))
        return result
    if kind == "Binary":
        return functions(expression["left"]) + functions(expression["right"])
    if kind == "Unary":
        return functions(expression["operand"])
    return []


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def bind_sql(sql: str, bindings: list[Any]) -> str:
    result = sql
    for value in bindings:
        if "?" not in result:
            raise ValueError("more bindings than placeholders")
        result = result.replace("?", sql_literal(value), 1)
    if "?" in result:
        raise ValueError("fewer bindings than placeholders")
    return result


def reference_sql(reference: dict[str, Any]) -> str:
    if "rawSql" in reference:
        return reference["rawSql"]
    joins = ""
    if reference["dataset"] == "basic_ext":
        joins = (" LEFT JOIN newzl.v_hsj_stock_hq_ext e"
                 " ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate")
    clauses = [f"b.bizdate='{reference['date']}'"]
    if reference.get("market"):
        clauses.append(reference["market"])
    clauses.append(reference["predicate"])
    sql = ("SELECT b.mktcode,b.tgtcode FROM newzl.v_hsj_stock_hq_basic b" + joins
           + " WHERE " + " AND ".join(f"({item})" for item in clauses)
           + " ORDER BY b.mktcode,b.tgtcode")
    if reference.get("limit") is not None:
        sql += f" LIMIT {int(reference['limit'])}"
    return sql


class Doris:
    def __init__(self, docker: str, container: str, user: str, port: int, password: str):
        self.docker = docker
        self.container = container
        self.user = user
        self.port = port
        self.password = password
        inspected = run([docker, "inspect", "-f",
                         "{{.State.Status}} {{.State.Health.Status}} {{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                         container])
        if inspected.returncode:
            raise RuntimeError(inspected.stderr.strip())
        state = inspected.stdout.strip().split()
        if len(state) != 3 or state[:2] != ["running", "healthy"]:
            raise RuntimeError("Doris container is not running and healthy: " + inspected.stdout.strip())
        self.host = state[2]

    def query(self, sql: str) -> list[tuple[str, ...]]:
        command = [self.docker, "exec", "-i", "-e", f"MYSQL_PWD={self.password}", self.container,
                   "mysql", "-h", self.host, "-P", str(self.port), "-u", self.user,
                   "--batch", "--skip-column-names", "--raw"]
        completed = run(command, stdin=sql.rstrip(";\n") + ";\n")
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        return [tuple(line.split("\t")) for line in completed.stdout.splitlines() if line]


class WslDoris:
    """Use the private client configuration of the owned diagnostic instance."""
    @staticmethod
    def _port(value: str, name: str) -> int:
        text = value.strip()
        if re.fullmatch(r'[0-9]{1,5}', text) is None or not 1 <= int(text) <= 65535:
            # Do not echo untrusted configuration, which may contain secrets.
            raise ValueError('Invalid diagnostic ' + name + ' port')
        return int(text)

    def __init__(self, distribution: str, container: str):
        self.prefix = ["wsl.exe", "-d", distribution, "--exec", "docker"]
        inspected = run(self.prefix + ["inspect", "-f",
            '{{.State.Running}} {{index .Config.Labels "com.acme.dorisdsl.purpose"}}', container])
        if inspected.returncode or inspected.stdout.strip() != "true official-data-diagnostic":
            raise RuntimeError("Expected the running, owned official-data diagnostic container")
        # Select only the non-secret [client] port. Never cat or print the
        # private client configuration (which also contains the password).
        selected = run(self.prefix + ['exec', container, 'awk',
            r'/^[[:space:]]*\[/ {client=($0 ~ /^[[:space:]]*\[client\][[:space:]]*$/); next} '
            r'client && /^[[:space:]]*port[[:space:]]*=/ {sub(/^[^=]*=/, ""); print}',
            '/run/dsl-client.cnf'])
        if selected.returncode:
            raise RuntimeError('Cannot read the diagnostic client port')
        ports = selected.stdout.splitlines()
        if len(ports) > 1:
            raise ValueError('Ambiguous diagnostic query port')
        self.query_port = self._port(ports[0], 'query') if ports else 9030
        # Filter inside Docker's formatter, so unrelated environment variables
        # (including any credentials) never reach this subprocess's stdout.
        http_ports = run(self.prefix + ['inspect', '-f',
            '{{range .Config.Env}}{{if or (eq (index (split . "=") 0) "DSL_DORIS_BE_HTTP_PORT") '
            '(eq (index (split . "=") 0) "DSL_DORIS_FE_HTTP_PORT")}}{{println .}}{{end}}{{end}}', container])
        if http_ports.returncode:
            raise RuntimeError('Cannot read the diagnostic HTTP ports')
        values = {}
        for line in http_ports.stdout.splitlines():
            if not line.strip():
                continue
            name, separator, value = line.partition('=')
            if not separator or name not in ('DSL_DORIS_BE_HTTP_PORT', 'DSL_DORIS_FE_HTTP_PORT') or name in values:
                raise ValueError('Unexpected or ambiguous diagnostic HTTP port')
            values[name] = self._port(value, 'HTTP')
        self.be_http_port = values.get('DSL_DORIS_BE_HTTP_PORT', 8040)
        self.fe_http_port = values.get('DSL_DORIS_FE_HTTP_PORT', 8030)
        self.command = self.prefix + ["exec", "-i", container, "mysql",
            "--defaults-extra-file=/run/dsl-client.cnf", "--port=" + str(self.query_port),
            "--batch", "--skip-column-names", "--raw"]

    def query(self, sql: str) -> list[tuple[str, ...]]:
        completed = subprocess.run(self.command, input=sql.rstrip(";\n") + ";\n",
            text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=300)
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        return [tuple(line.split("\t")) for line in completed.stdout.splitlines() if line]


def registered_snapshot(doris: Any, manifest: dict[str, Any], manifest_hash: str) -> bool:
    rows = doris.query("SELECT snapshot_id,contract_version,manifest_sha256 FROM newzl.data_snapshot_registry "
        "WHERE snapshot_id=" + sql_literal(manifest["snapshotId"]) + " AND status='VALIDATED'")
    return rows == [(manifest["snapshotId"], manifest["contractVersion"], manifest_hash)]


def compile_case(java: str, jar: Path, dsl: str, temp: Path, snapshot_id: str | None = None,
                 access_path: str | None = None, historical_features: Path | None = None,
                 manifest_sha256: str | None = None, rolling_features: Path | None = None) -> dict[str, Any]:
    temp.write_text(dsl, encoding="utf-8")
    command = [java, "-Dfile.encoding=UTF-8", "-Dsun.stdout.encoding=UTF-8",
                     "-Dsun.stderr.encoding=UTF-8", "-jar", str(jar),
                     "compile-stock-slot-sql", str(temp), "--format", "json"]
    if snapshot_id is not None:
        command.extend(["--snapshot-id", snapshot_id])
    if historical_features is not None:
        command.extend(["--historical-features", str(historical_features)])
    if rolling_features is not None:
        command.extend(["--rolling-features", str(rolling_features)])
    if manifest_sha256 is not None:
        command.extend(["--manifest-sha256", manifest_sha256])
    if access_path is not None:
        command.extend(["--access-path", access_path])
    completed = run(command)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return json.loads(completed.stdout)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    manifest_path = args.repo / "data" / "doris" / "snapshots" / golden["snapshotId"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doris = (WslDoris(args.wsl_distribution, args.container) if args.wsl_distribution else
             Doris(str(args.docker), args.container, args.user, args.mysql_port, os.environ["DORIS_PASSWORD"]))

    snapshot_checks = {
        "codeRows": int(doris.query("SELECT COUNT(*) FROM newzl.hsj_stock_code_info")[0][0]),
        "basicRows": int(doris.query("SELECT COUNT(*) FROM newzl.hsj_stock_hq_basic")[0][0]),
        "extRows": int(doris.query("SELECT COUNT(*) FROM newzl.hsj_stock_hq_ext")[0][0]),
        "basicDateRange": list(doris.query("SELECT MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_basic")[0]),
        "extDateRange": list(doris.query("SELECT MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_ext")[0]),
    }
    snapshot_ok = (
        snapshot_checks["codeRows"] == manifest["files"]["hsj_stock_code_info"]["rows"]
        and snapshot_checks["basicRows"] == manifest["files"]["hsj_stock_hq_basic"]["rows"]
        and snapshot_checks["extRows"] == manifest["files"]["hsj_stock_hq_ext"]["rows"]
        and snapshot_checks["basicDateRange"] == [manifest["files"]["hsj_stock_hq_basic"]["dateMin"], manifest["files"]["hsj_stock_hq_basic"]["dateMax"]]
        and snapshot_checks["extDateRange"] == [manifest["files"]["hsj_stock_hq_ext"]["dateMin"], manifest["files"]["hsj_stock_hq_ext"]["dateMax"]]
    )
    if not snapshot_ok:
        raise RuntimeError("Doris snapshot does not match the frozen manifest")

    provenance = {
        "purpose": "PROJECT_ACCEPTANCE", "goldenVersion": golden["goldenVersion"],
        "dslVersion": golden["dslVersion"], "snapshotId": golden["snapshotId"],
        "executedAtUtc": datetime.now(timezone.utc).isoformat(),
        "artifactHashes": {"goldenSha256": _sha256(args.golden),
            "snapshotManifestSha256": _sha256(manifest_path), "compilerJarSha256": _sha256(args.jar)},
        "physicalSnapshotMatchesManifest": snapshot_ok, "snapshotChecks": snapshot_checks,
    }
    validated = registered_snapshot(doris, manifest, provenance["artifactHashes"]["snapshotManifestSha256"])
    if not validated:
        return {**provenance, "status": "BLOCKED", "snapshotVerified": False,
            "blockedReason": "Exact VALIDATED snapshot/contract/manifest registration is required before acceptance queries",
            "cases": [], "overall": {"total": 0, "correct": 0, "accuracy": None},
            "splits": {}, "failureCategories": {"SNAPSHOT_NOT_VALIDATED": 1}}

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="stock-slot-accuracy-") as directory:
        temp = Path(directory) / "case.dsl"
        for case in golden["cases"]:
            if not case.get("executable", False):
                continue
            record: dict[str, Any] = {"id": case["id"], "split": case["split"], "badcase": bool(case.get("badcase")),
                                      "dsl": case["dsl"],
                                      "strata": case["strata"], "layers": {}, "failures": []}
            try:
                artifact = compile_case(args.java, args.jar, case["dsl"], temp, golden["snapshotId"])
                expression = artifact["semanticModel"]["document"]["expression"]
                ast_failures = []
                if expression.get("operator") != case["expect"]["rootOperator"]:
                    ast_failures.append("root operator mismatch")
                if functions(expression) != case["expect"]["functions"]:
                    ast_failures.append("function traversal mismatch")
                record["layers"]["astSemantic"] = not ast_failures
                record["failures"].extend({"category": "AST_SEMANTIC", "message": item} for item in ast_failures)

                structure_failures = []
                plan_kinds = [node["kind"] for node in artifact["logicalPlan"]]
                if plan_kinds != case["expect"]["planKinds"]:
                    structure_failures.append(f"plan mismatch: {plan_kinds}")
                for fragment in case["expect"]["requiredSql"]:
                    if fragment not in artifact["sql"]:
                        structure_failures.append("missing SQL fragment: " + fragment)
                for fragment in case["expect"]["forbiddenSql"]:
                    if fragment in artifact["sql"]:
                        structure_failures.append("forbidden SQL fragment: " + fragment)
                if len(artifact["bindings"]) != case["expect"]["bindingCount"]:
                    structure_failures.append("binding count mismatch")
                if artifact["ordered"] != case["expect"]["ordered"]:
                    structure_failures.append("ordered flag mismatch")
                record["layers"]["sqlStructure"] = not structure_failures
                record["failures"].extend({"category": "SQL_STRUCTURE", "message": item} for item in structure_failures)

                generated_sql = bind_sql(artifact["sql"], artifact["bindings"])
                expected_sql = reference_sql(case["reference"])
                record["reproduction"] = {
                    "parameterizedSql": artifact["sql"],
                    "bindings": artifact["bindings"],
                    "generatedSql": generated_sql,
                    "referenceSql": expected_sql,
                }
                generated_rows = doris.query(generated_sql)
                expected_rows = doris.query(expected_sql)
                if artifact["ordered"]:
                    result_ok = generated_rows == expected_rows
                    category = "RESULT_ORDER"
                else:
                    result_ok = set(generated_rows) == set(expected_rows)
                    category = "RESULT_SET"
                record["layers"]["result"] = result_ok
                record["generatedRowCount"] = len(generated_rows)
                record["referenceRowCount"] = len(expected_rows)
                if not result_ok:
                    record["failures"].append({"category": category, "message": "generated and reference results differ"})
                    record["reproduction"]["generatedOnlySample"] = [list(row) for row in generated_rows if row not in set(expected_rows)][:20]
                    record["reproduction"]["referenceOnlySample"] = [list(row) for row in expected_rows if row not in set(generated_rows)][:20]
            except Exception as error:
                record["layers"].setdefault("astSemantic", False)
                record["layers"].setdefault("sqlStructure", False)
                record["layers"].setdefault("result", False)
                record["failures"].append({"category": "EXECUTION", "message": str(error)})
            record["correct"] = all(record["layers"].get(layer, False) for layer in ("astSemantic", "sqlStructure", "result"))
            results.append(record)

    splits: dict[str, dict[str, Any]] = {}
    for split, members in _groups(results, "split").items():
        correct = sum(item["correct"] for item in members)
        splits[split] = {"total": len(members), "correct": correct, "accuracy": correct / len(members) if members else None}
    total_correct = sum(item["correct"] for item in results)
    failures = Counter(failure["category"] for item in results for failure in item["failures"])
    return {
        **provenance,
        "status": "PASS" if not failures else "FAIL",
        "goldenVersion": golden["goldenVersion"],
        "dslVersion": golden["dslVersion"],
        "snapshotId": golden["snapshotId"],
        "executedAtUtc": datetime.now(timezone.utc).isoformat(),
        "artifactHashes": {
            "goldenSha256": _sha256(args.golden),
            "snapshotManifestSha256": _sha256(manifest_path),
            "compilerJarSha256": _sha256(args.jar),
        },
        "snapshotVerified": validated,
        "snapshotChecks": snapshot_checks,
        "denominatorPolicy": golden["denominatorPolicy"],
        "excludedCapabilities": golden["excludedCapabilities"],
        "tolerance": golden["resultContract"],
        "overall": {"total": len(results), "correct": total_correct, "accuracy": total_correct / len(results)},
        "splits": splits,
        "failureCategories": dict(failures),
        "cases": results,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _groups(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row[key]].append(row)
    return result


def write_markdown(report: dict[str, Any], path: Path) -> None:
    if report["status"] == "BLOCKED":
        path.write_text("# 项目正确性验收：BLOCKED\n\n"
            f"快照：`{report['snapshotId']}`；黄金集：`{report['goldenVersion']}`。\n\n"
            "物理行数、日期范围与 manifest 一致，但没有与快照、契约、manifest 哈希完全匹配的 VALIDATED 登记。"
            "验收查询未执行，正确率没有计算。诊断查询成功不能替代快照验证。\n\n"
            f"原因：{report['blockedReason']}\n", encoding="utf-8")
        return
    lines = [
        "# stock-slot-v1 正确性报告", "",
        f"黄金集：`{report['goldenVersion']}`  ",
        f"数据快照：`{report['snapshotId']}`  ",
        f"执行时间（UTC）：`{report['executedAtUtc']}`", "",
        "## 可复现工件", "",
        f"- 黄金集 SHA-256：`{report['artifactHashes']['goldenSha256']}`",
        f"- 快照清单 SHA-256：`{report['artifactHashes']['snapshotManifestSha256']}`",
        f"- 编译器 JAR SHA-256：`{report['artifactHashes']['compilerJarSha256']}`", "",
        "## 正确率", "", "| 数据集 | 正确数 | 分母 | 正确率 |", "|---|---:|---:|---:|",
    ]
    for name in ("development", "regression", "blind"):
        item = report["splits"].get(name, {"correct": 0, "total": 0, "accuracy": 0})
        lines.append(f"| {name} | {item['correct']} | {item['total']} | {item['accuracy']:.2%} |")
    overall = report["overall"]
    lines.extend([f"| **整体** | **{overall['correct']}** | **{overall['total']}** | **{overall['accuracy']:.2%}** |", "",
                  "正确样例必须同时通过 Typed AST/语义、SQL 结构和 Doris 结果三层检查。", "",
                  "## 失败分类", ""])
    if report["failureCategories"]:
        for category, count in report["failureCategories"].items():
            lines.append(f"- `{category}`：{count}")
    else:
        lines.append("- 无失败样例。")
    lines.extend(["", "## 分母与排除范围", "", report["denominatorPolicy"], ""])
    lines.extend(f"- {item}" for item in report["excludedCapabilities"])
    lines.extend(["", "## 快照检查", "", f"固定快照核验：`{report['snapshotVerified']}`。",
                  "执行前核对行数、日期范围以及 VALIDATED 登记中的快照、契约和 manifest 哈希。", "",
                  "## 样例明细", "", "| ID | 集合 | 三层结果 | 返回行数 |", "|---|---|---|---:|"])
    for case in report["cases"]:
        layer = "/".join("PASS" if case["layers"].get(name) else "FAIL" for name in ("astSemantic", "sqlStructure", "result"))
        lines.append(f"| {case['id']} | {case['split']} | {layer} | {case.get('generatedRowCount', 0)} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--golden", type=Path, default=Path("accuracy/golden/stock-slot-executable-v1.0.1.json"))
    parser.add_argument("--jar", type=Path, default=Path("target/dsl-doris-compiler.jar"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--docker", type=Path, default=Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"))
    parser.add_argument("--container", default="doris")
    parser.add_argument("--wsl-distribution", help="Use the owned WSL diagnostic instance and private root client configuration")
    parser.add_argument("--user", default="dsl_loader")
    parser.add_argument("--mysql-port", type=int, default=9030)
    parser.add_argument("--java", default="java")
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    args.golden = (args.repo / args.golden).resolve() if not args.golden.is_absolute() else args.golden
    args.jar = (args.repo / args.jar).resolve() if not args.jar.is_absolute() else args.jar
    if args.output_dir is None:
        version = json.loads(args.golden.read_text(encoding="utf-8"))["goldenVersion"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", version):
            raise ValueError("Invalid golden version for output directory")
        args.output_dir = args.repo / "reports/accuracy" / version
    else:
        args.output_dir = (args.repo / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir
    if not args.wsl_distribution and not os.environ.get("DORIS_PASSWORD"):
        raise SystemExit("DORIS_PASSWORD is required")
    report = evaluate(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, args.output_dir / "REPORT.md")
    print(json.dumps({"overall": report["overall"], "splits": report["splits"],
                      "failures": report["failureCategories"]}, ensure_ascii=False))
    if report["status"] == "BLOCKED":
        return 3
    blind = report["splits"].get("blind", {"accuracy": 0})["accuracy"]
    return 0 if blind >= 0.95 and not report["failureCategories"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
