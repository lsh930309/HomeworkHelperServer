#!/usr/bin/env python3
"""Project verification gate for migration-safe development.

Runs the automated checks that can be executed on a normal development machine.
Windows-only manual smoke items remain in docs/migration-smoke-checklist.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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


def audit_v2_completion_documents() -> None:
    """Verify that v2 completion/parity audit artifacts still trace the matrix."""

    matrix_path = ROOT / "tests" / "migration" / "feature_matrix.json"
    parity_path = ROOT / "docs" / "v2-gui-feature-parity.md"
    completion_path = ROOT / "docs" / "v2-gui-completion-audit.md"
    windows_logic_path = ROOT / "docs" / "v2-gui-windows-logic-review.md"

    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    parity_doc = parity_path.read_text(encoding="utf-8")
    completion_doc = completion_path.read_text(encoding="utf-8")
    windows_logic_doc = windows_logic_path.read_text(encoding="utf-8")
    parity_rows = set()
    for line in parity_doc.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and re.match(r"^[A-Z]+-\d{3}$", cells[0]):
            parity_rows.add(cells[0])

    missing_feature_ids = [
        feature["id"]
        for feature in matrix["features"]
        if feature["id"] not in parity_rows
    ]
    missing_requirements = [
        f"Requirement {number}"
        for number in range(1, 6)
        if f"Requirement {number}" not in completion_doc
    ]
    required_references = [
        "Current-device status: **Achieved**",
        "Not achieved yet",
        "Windows-only smoke",
        "new-gui-design-philosophy-pyqt-portability-report.md",
        "docs/v2-gui-feature-parity.md",
        "docs/v2-gui-windows-logic-review.md",
        "tests/migration/feature_matrix.json",
        "docs/migration-smoke-checklist.md",
        "python tools/verify_project.py --full",
        "update_goal(status=\"complete\")",
    ]
    missing_references = [
        reference
        for reference in required_references
        if reference not in completion_doc
    ]
    windows_logic_rows = set()
    for line in windows_logic_doc.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and re.match(r"^[A-Z]+-\d{3}$", cells[0]):
            windows_logic_rows.add(cells[0])
    smoke_feature_ids = {
        feature["id"]
        for feature in matrix["features"]
        if feature["manual_smoke"]
    }
    missing_windows_logic_ids = sorted(smoke_feature_ids - windows_logic_rows)

    print("\n==> v2 completion audit trace")
    print(
        "feature_ids_traced="
        f"{len(matrix['features']) - len(missing_feature_ids)}/{len(matrix['features'])} "
        f"objective_requirements_traced={5 - len(missing_requirements)}/5 "
        f"windows_logic_ids_traced={len(smoke_feature_ids) - len(missing_windows_logic_ids)}/{len(smoke_feature_ids)}"
    )
    print("current_device_completion=achieved")
    print("completion_status=not-achieved windows-smoke-required")

    problems = missing_feature_ids + missing_requirements + missing_references + missing_windows_logic_ids
    if problems:
        for problem in problems:
            print(f"! missing completion trace: {problem}")
        raise SystemExit("v2 completion audit trace is incomplete.")


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
        [py, "-m", "compileall", "-q", "tests", "src", "tools", "homework_helper.pyw", "build.py"],
    )
    run("main GUI frontend build", ["npm", "run", "build:main-gui"])
    run("dashboard frontend build", ["npm", "run", "build:dashboard"])
    run("Tauri Rust check", ["cargo", "check", "--manifest-path", "src-tauri/Cargo.toml"])
    if args.full:
        run("Tauri shell release build", ["npm", "run", "tauri:build", "--", "--no-bundle"])
    audit_migration_matrix()
    audit_v2_completion_documents()

    print("\nVerification complete. For Windows-only behavior, run docs/migration-smoke-checklist.md.")


if __name__ == "__main__":
    main()
