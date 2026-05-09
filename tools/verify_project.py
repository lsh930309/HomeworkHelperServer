#!/usr/bin/env python3
"""Project verification gate for migration-safe development.

Runs the automated checks that can be executed on a normal development machine.
Windows-only manual smoke items remain in docs/migration-smoke-checklist.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _python() -> str:
    if os.name == "nt":
        candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate if candidate.exists() else sys.executable)


def run(label: str, command: list[str]) -> None:
    print(f"\n==> {label}")
    print("$ " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def run_with_env(label: str, command: list[str], env: dict[str, str]) -> None:
    print(f"\n==> {label}")
    print("$ " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT, env={**os.environ, **env})
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def audit_migration_matrix() -> None:
    matrix_path = ROOT / "tests" / "migration" / "feature_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    features = matrix["features"]
    missing_high = [feature for feature in features if feature["data_risk"] == "high" and feature["new_gui_status"] == "missing"]
    partial = [feature for feature in features if feature["new_gui_status"] == "partial"]

    print("\n==> migration feature audit")
    print(f"features={len(features)} partial={len(partial)} high-risk-missing={len(missing_high)}")
    for feature in partial:
        smoke_note = "manual smoke required" if feature["manual_smoke"] else "automated only"
        print(f"- {feature['id']} {feature['data_risk']} partial: {feature['name']} ({smoke_note})")
    if missing_high:
        for feature in missing_high:
            print(f"! {feature['id']} high-risk missing: {feature['name']}")
        raise SystemExit("High-risk missing migration features remain.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run HomeworkHelper migration-safe verification checks.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also build the Tauri release shell with npm run tauri:build -- --no-bundle.",
    )
    parser.add_argument(
        "--require-real-data",
        action="store_true",
        help="Fail if HomeworkHelper.zip is missing instead of skipping real AppData fixture checks.",
    )
    args = parser.parse_args()

    py = _python()
    run("pytest full suite", [py, "-m", "pytest", "-q"])
    real_data_zip = ROOT / "HomeworkHelper.zip"
    if real_data_zip.exists() or args.require_real_data:
        run_with_env(
            "real AppData ZIP fixture checks",
            [py, "-m", "pytest", "-q", "tests/test_real_appdata_fixture.py"],
            {
                "HOMEWORKHELPER_REAL_DATA_ZIP": str(real_data_zip),
                "HOMEWORKHELPER_RUN_REAL_DATA": "1",
                "HOMEWORKHELPER_REQUIRE_REAL_DATA": "1" if args.require_real_data else "0",
            },
        )
    else:
        print("\n==> real AppData ZIP fixture checks")
        print("skipped: HomeworkHelper.zip not found (use --require-real-data to fail on absence)")
    run(
        "compile Python sources",
        [py, "-m", "compileall", "-q", "tests", "src/data", "src/api", "src/gui", "homework_helper.pyw", "build.py"],
    )
    run("main GUI frontend build", ["npm", "run", "build:main-gui"])
    run("dashboard frontend build", ["npm", "run", "build:dashboard"])
    run("Tauri Rust check", ["cargo", "check", "--manifest-path", "src-tauri/Cargo.toml"])
    if args.full:
        run("Tauri shell release build", ["npm", "run", "tauri:build", "--", "--no-bundle"])
    audit_migration_matrix()

    print("\nVerification complete. For Windows-only behavior, run docs/migration-smoke-checklist.md.")


if __name__ == "__main__":
    main()
