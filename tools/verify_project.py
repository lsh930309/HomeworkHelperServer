#!/usr/bin/env python3
"""Project verification gate for migration-safe development.

Runs the automated checks that can be executed on a normal development machine.
Windows-only manual smoke items remain in docs/migration-smoke-checklist.md.
"""

from __future__ import annotations

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run HomeworkHelper migration-safe verification checks.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also build the Tauri release shell with npm run tauri:build -- --no-bundle.",
    )
    args = parser.parse_args()

    py = _python()
    run("pytest full suite", [py, "-m", "pytest", "-q"])
    run(
        "compile Python sources",
        [py, "-m", "compileall", "-q", "tests", "src/data", "src/api", "src/gui", "homework_helper.pyw", "build.py"],
    )
    run("main GUI frontend build", ["npm", "run", "build:main-gui"])
    run("Tauri Rust check", ["cargo", "check", "--manifest-path", "src-tauri/Cargo.toml"])
    if args.full:
        run("Tauri shell release build", ["npm", "run", "tauri:build", "--", "--no-bundle"])

    print("\nVerification complete. For Windows-only behavior, run docs/migration-smoke-checklist.md.")


if __name__ == "__main__":
    main()
