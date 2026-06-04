#!/usr/bin/env python3
"""Run the active Remote Controller verification lane.

Android client development is suspended, so this verifier intentionally covers
the host Remote Agent and macOS reference client only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MACOS_CLIENT_DIR = PROJECT_ROOT / "remote_clients" / "macos" / "HomeworkHelperRemote"


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: tuple[str, ...]
    returncode: int
    status: str
    output: str


def _run(name: str, command: Iterable[str], *, cwd: Path = PROJECT_ROOT) -> CheckResult:
    cmd = tuple(command)
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return CheckResult(
        name=name,
        command=cmd,
        returncode=completed.returncode,
        status="passed" if completed.returncode == 0 else "failed",
        output=completed.stdout,
    )


def _git(args: Iterable[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *tuple(args)),
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _verify_branch_discipline(required_branch: str | None, expected_main_hash: str | None) -> CheckResult:
    """Report git branch state and optionally fail on branch-discipline drift."""

    output_lines: list[str] = []
    failures: list[str] = []

    branch = _git(["branch", "--show-current"])
    current_branch = branch.stdout.strip()
    output_lines.append(f"current_branch: {current_branch or '(detached)'}")
    if branch.returncode != 0:
        failures.append("failed to read current branch")
    elif required_branch and current_branch != required_branch:
        failures.append(f"expected branch {required_branch!r}, found {current_branch or '(detached)'}")

    status = _git(["status", "--short", "--branch"])
    if status.returncode == 0:
        output_lines.append(status.stdout.rstrip())
    else:
        failures.append("failed to read git status")
        output_lines.append(status.stdout.rstrip())

    if expected_main_hash:
        for ref in ("main", "origin/main"):
            revision = _git(["rev-parse", "--short", ref])
            actual = revision.stdout.strip()
            output_lines.append(f"{ref}: {actual or '(unavailable)'}")
            if revision.returncode != 0:
                failures.append(f"failed to read {ref}")
            elif actual != expected_main_hash:
                failures.append(f"expected {ref} at {expected_main_hash}, found {actual}")

    if failures:
        output_lines.append("branch discipline failures:")
        output_lines.extend(f"- {failure}" for failure in failures)

    return CheckResult(
        name="branch discipline",
        command=("git", "branch/status/rev-parse"),
        returncode=1 if failures else 0,
        status="failed" if failures else "passed",
        output="\n".join(line for line in output_lines if line),
    )


def _print_result(result: CheckResult) -> None:
    print(f"\n== {result.name}: {result.status} ({result.returncode}) ==")
    print("$ " + " ".join(result.command))
    if result.output.strip():
        print(result.output.rstrip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify HomeworkHelper Remote Controller implementation.")
    parser.add_argument(
        "--skip-full-pytest",
        action="store_true",
        help="Run targeted Python tests but skip the full pytest suite.",
    )
    parser.add_argument(
        "--require-branch",
        help="Fail when the current git branch is not the expected work branch, e.g. dev-remote.",
    )
    parser.add_argument(
        "--expect-main-hash",
        help="Fail when local main or origin/main no longer points at this short commit hash.",
    )
    args = parser.parse_args(argv)

    checks: list[CheckResult] = []
    checks.append(_verify_branch_discipline(args.require_branch, args.expect_main_hash))
    checks.append(_run("remote routes", [sys.executable, "-m", "pytest", "tests/test_remote_routes.py"]))
    checks.append(_run("macOS static contract", [sys.executable, "-m", "pytest", "tests/test_remote_macos_client_static.py"]))
    checks.append(_run("remote runtime smoke", [sys.executable, "tools/smoke_remote_controller_runtime.py"]))
    checks.append(_run("macOS RemoteAPIClient smoke", [sys.executable, "tools/smoke_macos_remote_api_client.py"]))
    checks.append(_run("macOS RemoteConnectionSupervisor smoke", [sys.executable, "tools/smoke_macos_connection_supervisor.py"]))
    checks.append(_run("macOS RemoteDashboardViewModel smoke", [sys.executable, "tools/smoke_macos_remote_viewmodel.py"]))
    if not args.skip_full_pytest:
        checks.append(_run("full pytest", [sys.executable, "-m", "pytest"]))
    checks.append(_run("macOS Swift build", ["swift", "build"], cwd=MACOS_CLIENT_DIR))

    failures: list[CheckResult] = []
    for result in checks:
        if result.returncode != 0:
            failures.append(result)
        _print_result(result)

    if failures:
        print("\nVerification failed.")
        return 1

    print("\nVerification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
