#!/usr/bin/env python3
"""Read every checkout file and record loads separately from asset review evidence.

No deletion, application imports, external symlink traversal or secret output.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9), "Asia/Seoul")
FIELDS = ("sequence", "path", "tracked", "category", "load_start_kst", "load_end_kst",
          "elapsed_ms", "expected_bytes", "loaded_bytes", "load_result", "review_method",
          "review_result", "disposition")


def now() -> str:
    return datetime.now(KST).isoformat(timespec="microseconds")


def category(path: Path, tracked: bool) -> str:
    parts = path.parts
    if parts[0] == ".git":
        return "git_metadata"
    if parts[0] == "local-artifacts" or path.name in {".env", "SmartThings_Token"}:
        return "local_credentials"
    if path.name == "build.version.json":
        return "local_build_state"
    if parts[0] == "release":
        return "release_artifact"
    if parts[0] == ".venv" or "node_modules" in parts:
        return "third_party_dependency"
    if any(p in parts for p in (".build", ".swiftpm", "__pycache__", ".pytest_cache")) or parts[0] in {"build", "dist"}:
        return "generated_build_or_cache"
    if parts[0] == "artifacts":
        return "work_artifact"
    if "homework_helper_data" in parts:
        return "local_application_data"
    if path.name == ".DS_Store":
        return "finder_metadata"
    if parts[0] == ".codeboarding":
        return "local_tool_metadata"
    return "project_owned_asset" if tracked else "untracked_asset"


def inventory(root: Path, output: Path) -> list[Path]:
    paths = []
    def fail(error):
        raise error
    for current, directories, files in os.walk(root, followlinks=False, onerror=fail):
        directories[:] = [name for name in directories if Path(current) / name != output]
        for name in directories:
            path = Path(current) / name
            if path.is_symlink():
                paths.append(path)
        paths.extend(Path(current) / name for name in files)
    return sorted(paths, key=lambda path: str(path.relative_to(root)))


def read_file(path: Path) -> tuple[dict, bytes]:
    started, clock = now(), time.perf_counter_ns()
    row = {"load_start_kst": started, "expected_bytes": "", "loaded_bytes": 0}
    data = b""
    try:
        metadata = path.lstat()
        row["expected_bytes"] = metadata.st_size
        if stat.S_ISLNK(metadata.st_mode):
            data = os.readlink(path).encode()
            row["load_result"] = "link_metadata_only"
        elif not stat.S_ISREG(metadata.st_mode):
            row["load_result"] = "special_file_not_opened"
        else:
            data = path.read_bytes()
            row["load_result"] = "loaded" if len(data) == metadata.st_size else "changed_during_load"
        row["loaded_bytes"] = len(data)
    except OSError as error:
        row["load_result"] = type(error).__name__
    row.update(load_end_kst=now(), elapsed_ms=round((time.perf_counter_ns() - clock) / 1e6, 3))
    return row, data


def source_structure(path: Path, data: bytes) -> dict:
    """Extract asset boundaries without executing source or exposing literals."""
    if path.suffix not in {".py", ".pyw", ".spec"}:
        return {"method": "text_or_binary_asset_role_review", "result": "requires_owner_review"}
    try:
        tree = ast.parse(data.decode("utf-8-sig"), filename=str(path))
    except (UnicodeError, SyntaxError) as error:
        return {"method": "python_ast", "result": type(error).__name__}
    imports = set()
    functions, classes, writes = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(item.name for item in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"write_text", "write_bytes", "commit", "unlink", "rmtree", "Popen", "run"}:
                writes.append({"line": node.lineno, "operation": node.func.attr})
    return {"method": "python_ast_asset_boundary_review", "result": "parsed_not_executed",
            "imports": sorted(imports), "functions": functions, "classes": classes,
            "write_or_execution_calls": writes}


def audit(root: Path, output: Path) -> dict:
    root, output = root.absolute(), output.absolute()
    # Freeze the inventory before creating this run's evidence. Never recursively audit its own log.
    git = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    tracked = set(filter(None, git.stdout.decode("utf-8").split("\0")))
    paths = sorted(set(inventory(root, output)) | {root / name for name in tracked},
                   key=lambda path: str(path.relative_to(root)))
    output.mkdir(parents=True, exist_ok=False)
    rows, structures = [], {}
    began = now()
    with (output / "file-load-timetable.csv").open("w", encoding="utf-8-sig", newline="") as events:
        writer = csv.DictWriter(events, fieldnames=FIELDS)
        writer.writeheader()
        for sequence, path in enumerate(paths, 1):
            relative = path.relative_to(root)
            row, data = read_file(path)
            kind = category(relative, str(relative) in tracked)
            row.update(sequence=sequence, path=str(relative), tracked=str(relative) in tracked, category=kind,
                       review_method="byte_load_only", review_result="owner_review_pending", disposition="undetermined")
            if kind == "project_owned_asset" and row["load_result"] == "loaded":
                details = source_structure(relative, data)
                row.update(review_method=details["method"], review_result=details["result"])
                structures[str(relative)] = details
            elif kind in {"third_party_dependency", "generated_build_or_cache", "git_metadata", "release_artifact", "local_credentials", "local_application_data", "local_build_state"}:
                row.update(review_method="storage_role_review", review_result="no_product_logic_review",
                           disposition="preserve")
            writer.writerow(row)
            rows.append(row)
    (output / "source-boundaries.json").write_text(json.dumps(structures, ensure_ascii=False, indent=2), encoding="utf-8")
    unexpected = [r["path"] for r in rows if r["load_result"] not in {"loaded", "link_metadata_only", "special_file_not_opened"}]
    summary = {"started_kst": began, "finished_kst": now(), "root": str(root), "report": str(output),
               "files": len(rows), "loaded_bytes": sum(row["loaded_bytes"] for row in rows),
               "load_result_counts": dict(Counter(row["load_result"] for row in rows)),
               "category_counts": dict(Counter(row["category"] for row in rows)), "read_errors": unexpected,
               "limits": "Loads are not human code review. Symlinks are recorded without following targets; IPC/special files are not opened. Audit outputs are excluded at inventory time. No application imports, deletion or secret contents are recorded."}
    (output / "load-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def summarize_dispositions(table: Path) -> dict[str, int]:
    """Read the current decisions; never persist a second copy of their counts."""
    with table.open(encoding="utf-8-sig", newline="") as stream:
        return dict(Counter(row["disposition"] for row in csv.DictReader(stream)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path, help="New directory for this run's CSV/JSON evidence")
    action.add_argument("--summarize-dispositions", type=Path,
                        help="Print counts from the current file decision CSV without writing a summary")
    args = parser.parse_args(argv)
    if args.summarize_dispositions is not None:
        print(json.dumps(summarize_dispositions(args.summarize_dispositions), ensure_ascii=False, indent=2))
        return 0
    summary = audit(args.root, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["read_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
