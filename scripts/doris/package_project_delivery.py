"""Freeze a small, verifiable project delivery without caches, credentials or raw CSVs.

The archive contains the actual working source tree; an uncommitted tree is labelled
as such rather than presenting HEAD as its complete identity. Only the selected new
acceptance run is included. Verification is independent of Java, Docker and Git.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PREFIXES = ("src/", "executor-doris/", "plugins/", "config/", "examples/",
                   "docs/", "scripts/", ".github/", "benchmarks/", "accuracy/", "data/doris/ddl/", "data/doris/config/",
                   "data/doris/snapshots/")
SOURCE_FILES = {"AGENTS.md", "README.md", "DELIVERY.md", "pom.xml", "Dockerfile",
                "docker-compose.yml", "docker-compose.yaml", ".gitignore", ".gitattributes",
                "data/doris/data-contract.json", "data/doris/README.md"}
EXCLUDED_PARTS = {".git", ".mvn-cache", ".tools", "target", "__pycache__", "node_modules"}
SENSITIVE_FILE = re.compile(r"(^|[._-])(credentials?|secrets?|private[._-]?key)([._-]|$)", re.I)
ACCEPTED_STATUS = {"PASS_OFFLINE_REAL_NOT_RUN", "PROJECT_PASS_FORMAL_BLOCKED"}
OFFLINE_STAGES = ("portable-fields", "portable-combinations", "portable-rank-combinations", "compiler-performance")
REAL_STAGES = ("sources", "native-fields", "native-combinations", "native-rank-combinations",
               "official-field-matrix", "official-field-verification", "official-combinations",
               "official-combination-explanations", "official-rank-combinations", "official-rank-explanations",
               "official-field-matrix-timings", "official-combinations-timings", "official-rank-combinations-timings",
               "resource-stability", "strict-gates", "formal-gate")
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024 * 1024


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(name):
    path = Path(name)
    if path.is_absolute() or not path.parts or any(p in ("..", ".") for p in path.parts) or ":" in str(name) or "\\" in str(name):
        raise ValueError("Unsafe relative package path")
    return path


def source_allowed(name):
    path = safe_relative(name)
    text = path.as_posix()
    if any(p in EXCLUDED_PARTS for p in path.parts) or path.name.startswith(".env") or SENSITIVE_FILE.search(path.name):
        return False
    if path.suffix.lower() in (".log", ".zip", ".7z", ".duckdb", ".jar", ".class", ".pyc"):
        return False
    if path.suffix.lower() in (".csv", ".xlsx", ".xls") and not text.startswith("src/test/resources/"):
        return False
    return text in SOURCE_FILES or text.startswith(SOURCE_PREFIXES)


def git_identity(root):
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True,
                                encoding="utf-8", errors="strict", timeout=30)
        return result.stdout
    revision = git("rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ValueError("Unexpected Git revision")
    candidates = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    names = sorted({n for n in candidates if n and source_allowed(n) and (root / n).is_file()})
    changed = git("diff", "--name-only", "HEAD", "-z").split("\0")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    dirty = sorted({n for n in changed + untracked if n and source_allowed(n)})
    return revision, names, dirty


def check_no_credentials(path):
    """Reject actual credential assignments in evidence without recording their value."""
    if path.suffix.lower() not in (".json", ".md", ".txt", ".log", ".sql", ".dsl"):
        raise ValueError("Unsupported evidence file type: " + path.name)
    text = path.read_text(encoding="utf-8-sig", errors="strict")
    if "-----BEGIN PRIVATE KEY-----" in text or "-----BEGIN RSA PRIVATE KEY-----" in text:
        raise ValueError("Private key in evidence: " + path.name)
    if path.suffix.lower() == ".json":
        def inspect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    sensitive = re.fullmatch(r"(?:password|token|authorization|credential|secret|client_secret|authToken|apiKey|accessToken|access_token|MYSQL_PWD)", key, re.I)
                    if sensitive and item not in (None, "", "[REDACTED]", "<redacted>"):
                        raise ValueError("Credential-bearing evidence field in " + path.name)
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        inspect(json.loads(text))
    if re.search(r"(?:\$env:|export\s+)?(?:DORIS_PASSWORD|DSL_PROJECT_PASSWORD|DSL_PROJECT_TOKEN)\s*=\s*['\"][^'<\"]{4,}['\"]", text):
        raise ValueError("Credential assignment in evidence: " + path.name)
    if re.search(r"Authorization:\s*(?:Basic|Bearer)\s+[A-Za-z0-9+/=_-]{8,}", text, re.I):
        raise ValueError("Credential-bearing authorization header in evidence: " + path.name)


def acceptance_summary(folder):
    path = folder / "project-summary.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("Missing unified project acceptance summary")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("formatVersion") != "project-acceptance-v1" or value.get("status") not in ACCEPTED_STATUS:
        raise ValueError("Only completed unified project/offline acceptance evidence may be packaged")
    if value.get("officialAcceptanceEligible") is not False:
        raise ValueError("Project delivery cannot certify official acceptance")
    verify_acceptance_stages(folder, value)
    return path, value


def verify_acceptance_stages(folder, summary):
    """Recheck the recorded stage evidence, not new hashes of a mutated run."""
    stages = summary.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("Incomplete acceptance stages")
    latest = {}
    directories = set()
    for stage in stages:
        name, status = stage.get("name"), stage.get("status")
        if not isinstance(name, str) or status not in ("PASS", "EXPECTED_BLOCKED", "FAIL", "NOT_RUN"):
            raise ValueError("Incomplete or invalid acceptance stage")
        latest[name] = stage
        if status == "NOT_RUN":
            continue
        directory = stage.get("directory")
        if not isinstance(directory, str) or directory in directories:
            raise ValueError("Invalid or duplicate acceptance attempt directory")
        directories.add(directory)
        relative = safe_relative(directory)
        target = folder / relative
        if target.is_symlink() or not target.is_dir() or not target.resolve().is_relative_to(folder):
            raise ValueError("Missing or unsafe acceptance attempt directory")
        recorded = stage.get("artifactHashes")
        if not isinstance(recorded, dict) or not recorded:
            raise ValueError("Missing completed stage artifact hashes: " + name)
        for entry, checksum in recorded.items():
            safe_relative(entry)
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError("Invalid completed stage artifact hash: " + name)
        paths = list(target.rglob("*"))
        if any(p.is_symlink() or not p.resolve().is_relative_to(target.resolve()) for p in paths):
            raise ValueError("Unsafe completed stage artifact: " + name)
        actual = {p.relative_to(target).as_posix(): digest(p) for p in paths if p.is_file()}
        if actual != recorded:
            raise ValueError("Completed stage artifacts changed: " + name)
    real = summary['status'] == 'PROJECT_PASS_FORMAL_BLOCKED'
    required = OFFLINE_STAGES + (REAL_STAGES if real else ())
    for name in required:
        stage = latest.get(name, {})
        expected = 'EXPECTED_BLOCKED' if name == 'formal-gate' else 'PASS'
        if stage.get('status') != expected or stage.get('exitCode') != (3 if name == 'formal-gate' else 0):
            raise ValueError("Missing or incomplete selected acceptance stage: " + name)
        report_name = ('source-validation-report.json' if name == 'sources' else
            'execution/result.json' if name in ('official-field-matrix', 'official-combinations', 'official-rank-combinations', 'resource-stability') else
            'controlled-execution-gate.json' if name == 'strict-gates' else 'result.json')
        if report_name not in stage['artifactHashes']:
            raise ValueError("Missing selected stage machine report: " + name)
        machine = json.loads((folder / stage['directory'] / report_name).read_text(encoding='utf-8-sig'))
        expected_machine = 'BLOCKED' if name == 'formal-gate' else 'PROJECT_READY_WITH_LIMITATIONS' if name == 'sources' else 'PASS'
        if machine.get('status') != expected_machine or stage.get('machineStatus') != expected_machine:
            raise ValueError("Selected stage machine status mismatch: " + name)
        if name == 'resource-stability' and (
                machine.get('timeoutStatus') != 'PASS_REAL_JDBC_CONTROL'
                or machine.get('restartStatus') != 'PASS_PROCESS_RESTART_HOST_CACHE_RETAINED'):
            raise ValueError('Incomplete real timeout or owned-container restart evidence')
    if not real and any(latest.get(name, {}).get('status') != 'NOT_RUN' for name in REAL_STAGES):
        raise ValueError("Offline delivery must disclose every real-data stage as NOT_RUN")
    if summary.get('formalAcceptanceStatus') != ('BLOCKED' if real else 'NOT_RUN'):
        raise ValueError("Formal status inconsistent with selected acceptance mode")


def report_jar_hash(value):
    if isinstance(value, dict):
        for key in ("jarSha256", "compilerJarSha256"):
            if key in value:
                return value[key]
        for key in ("identity", "artifactHashes", "inputs", "hashes"):
            if key in value:
                found = report_jar_hash(value[key])
                if found:
                    return found
    return None


def acceptance_source_hash(root):
    spec = importlib.util.spec_from_file_location("delivery_acceptance_identity", root / "scripts/doris/run_project_acceptance.py")
    if spec is None or spec.loader is None:
        raise ValueError("Missing unified source identity implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.source_digest(root=root)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_package(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "delivery-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("packageVersion") != "project-delivery-v1" or not manifest.get("files"):
        raise ValueError("Unsupported or empty delivery manifest")
    expected = {}
    for item in manifest["files"]:
        name = item["path"]
        path = folder / safe_relative(name)
        if name in expected or path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(folder) is False:
            raise ValueError("Invalid package entry: " + name)
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError("Delivery checksum mismatch: " + name)
        expected[name] = item
    actual = {p.relative_to(folder).as_posix() for p in (folder / "payload").rglob("*") if p.is_file()}
    if any(p.is_symlink() for p in (folder / "payload").rglob("*")):
        raise ValueError("Symbolic link in delivery payload")
    if actual != set(expected):
        raise ValueError("Unlisted or missing payload file")
    sums = "".join(i["sha256"] + "  " + i["path"] + "\n" for i in manifest["files"])
    if (folder / "SHA256SUMS").read_text(encoding="utf-8") != sums:
        raise ValueError("Checksum index mismatch")
    archive = folder / "project-delivery.zip"
    if archive.exists():
        with zipfile.ZipFile(archive) as zipped:
            expected_archive = set(expected) | {"delivery-manifest.json", "SHA256SUMS", "README.md"}
            if set(zipped.namelist()) != expected_archive or len(zipped.namelist()) != len(expected_archive):
                raise ValueError("Archive inventory mismatch")
            for name in expected_archive:
                if hashlib.sha256(zipped.read(name)).hexdigest() != digest(folder / name):
                    raise ValueError("Archive content mismatch: " + name)
    return {"status": "PASS", "files": len(expected), "jarSha256": manifest["jarSha256"],
            "sourceTreeSha256": manifest["sourceTreeSha256"], "archiveChecked": archive.exists(),
            "restoreExecution": "NOT_RUN"}


def build_package(root, jar, evidence, output, label="project-v1"):
    root, jar, evidence, output = [Path(p).resolve() for p in (root, jar, evidence, output)]
    if output.exists():
        raise ValueError("Use a new output directory; existing delivery is preserved")
    if not evidence.is_dir() or output.is_relative_to(evidence) or evidence.is_relative_to(output):
        raise ValueError("Independent existing evidence directory required")
    if not jar.is_file() or jar.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Missing or oversized final JAR")
    summary_path, summary = acceptance_summary(evidence)
    jar_hash = digest(jar)
    recorded_hash = report_jar_hash(summary)
    if recorded_hash is None or recorded_hash != jar_hash:
        raise ValueError("JAR does not match selected acceptance evidence")
    revision, names, dirty = git_identity(root)
    run_identity = summary.get("identity", {})
    source_hash = acceptance_source_hash(root)
    if run_identity.get("sourceSha256") != source_hash or run_identity.get("gitCommit") != revision:
        raise ValueError("Source tree or Git baseline changed since selected acceptance run")
    if not names:
        raise ValueError("No allowed project source files")
    source_items = []
    for name in names:
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Unsafe or oversized source file: " + name)
        source_items.append({"path": name, "sha256": digest(path), "bytes": path.stat().st_size})
    tree_hash = hashlib.sha256(json.dumps(source_items, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()
    evidence_items = []
    for path in sorted(evidence.rglob("*")):
        if path.is_dir():
            continue
        name = path.relative_to(evidence).as_posix()
        if path.is_symlink() or any(part in EXCLUDED_PARTS for part in path.parts) or SENSITIVE_FILE.search(path.name) or path.name.startswith(".env"):
            raise ValueError("Unsafe evidence file: " + name)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Oversized evidence: " + name)
        check_no_credentials(path)
        evidence_items.append({"path": name, "sha256": digest(path), "bytes": path.stat().st_size})
    if sum(p["bytes"] for p in evidence_items) > MAX_EVIDENCE_BYTES:
        raise ValueError("Evidence exceeds bounded delivery size")
    # No destination writes take place before input validation completes.
    output.mkdir(parents=True)
    entries = []
    def copy(source, destination):
        target = output / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entries.append({"path": destination, "bytes": target.stat().st_size, "sha256": digest(target)})
    copy(jar, "payload/artifacts/dsl-doris-compiler.jar")
    for item in source_items:
        copy(root / item["path"], "payload/source/" + item["path"])
    for item in evidence_items:
        copy(evidence / item["path"], "payload/evidence/" + item["path"])
    identity = {"gitRevision": revision, "gitCommit": revision, "sourceTreeSha256": tree_hash,
                "sourceState": "WORKTREE_WITH_UNCOMMITTED_CHANGES" if dirty else "COMMITTED",
                "changedSourcePaths": dirty, "sourceFiles": source_items}
    identity_path = output / "payload/source-version.json"
    write_json(identity_path, identity)
    entries.append({"path": "payload/source-version.json", "bytes": identity_path.stat().st_size, "sha256": digest(identity_path)})
    restored_identity_path = output / "payload/source/source-version.json"
    write_json(restored_identity_path, identity)
    entries.append({"path": "payload/source/source-version.json", "bytes": restored_identity_path.stat().st_size, "sha256": digest(restored_identity_path)})
    entries.sort(key=lambda item: item["path"])
    manifest = {"packageVersion": "project-delivery-v1", "label": label,
                "createdAtUtc": datetime.now(timezone.utc).isoformat(), **identity,
                "jarSha256": jar_hash, "evidenceSummary": summary_path.name,
                "acceptanceSourceSha256": source_hash,
                "evidenceStatus": summary["status"], "officialAcceptanceEligible": False,
                "formalStatus": "BLOCKED", "restoreExecution": "NOT_RUN",
                "excluded": ["original CSV dataset", "Docker volumes", ".git", ".mvn-cache", ".tools",
                             "environment variables", "all historical report directories"], "files": entries}
    write_json(output / "delivery-manifest.json", manifest)
    (output / "SHA256SUMS").write_text("".join(i["sha256"] + "  " + i["path"] + "\n" for i in entries), encoding="utf-8")
    (output / "README.md").write_text(
        "# 项目交付包\n\n"
        f"标签：{label}。源码基线：`{revision}`；实际源码状态：`{identity['sourceState']}`。\n\n"
        f"本次证据状态：`{summary['status']}`；正式验收：`BLOCKED`。\n\n"
        "`payload/artifacts` 是与本次证据哈希相同的 JAR；`payload/source` 是实际源码和配置；"
        "`payload/evidence` 只保存指定批次。交付包不含原始三份 CSV，数据需单独传递并核对 manifest。\n\n"
        "解压后先执行：`python payload/source/scripts/doris/package_project_delivery.py --verify-dir .`。"
        "恢复和复跑步骤见 `payload/source/docs/project-capabilities-v1.md`。\n\n"
        "哈希和 ZIP 校验会执行；本包不因此宣称全新机器上 Doris 恢复已实测。"
        "复制运行环境证书不能替代恢复后的来源验证。\n", encoding="utf-8")
    verify_package(output)
    with zipfile.ZipFile(output / "project-delivery.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in [e["path"] for e in entries] + ["delivery-manifest.json", "SHA256SUMS", "README.md"]:
            archive.write(output / name, arcname=name)
    return verify_package(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output-dir", type=Path, help="Fresh destination for the bounded delivery and ZIP")
    mode.add_argument("--verify-dir", type=Path, help="Recompute every payload and archive checksum")
    parser.add_argument("--evidence-dir", type=Path, help="One completed unified acceptance run; not all reports")
    parser.add_argument("--jar", type=Path, default=ROOT / "target/dsl-doris-compiler.jar")
    parser.add_argument("--label", default="project-v1")
    args = parser.parse_args()
    if args.verify_dir:
        if args.evidence_dir:
            parser.error("--evidence-dir is only used with --output-dir")
        result = verify_package(args.verify_dir)
    else:
        if args.evidence_dir is None:
            parser.error("--evidence-dir is required with --output-dir")
        result = build_package(ROOT, args.jar, args.evidence_dir, args.output_dir, args.label)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
