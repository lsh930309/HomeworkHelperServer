#!/usr/bin/env python3
"""Run the Remote Controller verification lane.

The Android APK build currently requires an explicit Google Android SDK License
acceptance.  Use --allow-android-license-blocker to treat that known blocker as
an expected terminal state while still failing on all other verification errors.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MACOS_CLIENT_DIR = PROJECT_ROOT / "remote_clients" / "macos" / "HomeworkHelperRemote"
ANDROID_CLIENT_DIR = PROJECT_ROOT / "remote_clients" / "android" / "HomeworkHelperRemote"
DEFAULT_JAVA_HOME = Path("/opt/homebrew/opt/openjdk@17")
DEFAULT_ANDROID_SDK_ROOT = Path("/opt/homebrew/share/android-commandlinetools")
ANDROID_LICENSE_MARKERS = (
    "licenses have not been accepted",
    "License for package Android SDK",
    "Android SDK License",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: tuple[str, ...]
    returncode: int
    status: str
    output: str


def _env_for_android() -> dict[str, str]:
    env = os.environ.copy()
    if DEFAULT_JAVA_HOME.exists():
        env.setdefault("JAVA_HOME", str(DEFAULT_JAVA_HOME))
    if DEFAULT_ANDROID_SDK_ROOT.exists():
        env.setdefault("ANDROID_HOME", str(DEFAULT_ANDROID_SDK_ROOT))
        env.setdefault("ANDROID_SDK_ROOT", str(DEFAULT_ANDROID_SDK_ROOT))
    return env


def _run(name: str, command: Iterable[str], *, cwd: Path = PROJECT_ROOT, env: dict[str, str] | None = None) -> CheckResult:
    cmd = tuple(command)
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
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


def _is_android_license_blocker(result: CheckResult) -> bool:
    return result.returncode != 0 and any(marker in result.output for marker in ANDROID_LICENSE_MARKERS)


def _print_result(result: CheckResult) -> None:
    print(f"\n== {result.name}: {result.status} ({result.returncode}) ==")
    print("$ " + " ".join(result.command))
    if result.output.strip():
        print(result.output.rstrip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify HomeworkHelper Remote Controller implementation.")
    parser.add_argument(
        "--allow-android-license-blocker",
        action="store_true",
        help="Exit 0 when the only failure is the known Android SDK License blocker.",
    )
    parser.add_argument(
        "--skip-full-pytest",
        action="store_true",
        help="Run targeted Python tests but skip the full pytest suite.",
    )
    args = parser.parse_args(argv)

    checks: list[CheckResult] = []
    checks.append(_run("remote routes", [sys.executable, "-m", "pytest", "tests/test_remote_routes.py"]))
    checks.append(_run("android static contract", [sys.executable, "-m", "pytest", "tests/test_remote_android_client_static.py"]))
    checks.append(_run("macOS static contract", [sys.executable, "-m", "pytest", "tests/test_remote_macos_client_static.py"]))
    checks.append(_run("remote runtime smoke", [sys.executable, "tools/smoke_remote_controller_runtime.py"]))
    checks.append(_run("macOS RemoteAPIClient smoke", [sys.executable, "tools/smoke_macos_remote_api_client.py"]))
    checks.append(_run("remote power readiness", [sys.executable, "tools/check_remote_power_readiness.py", "--allow-blocker"]))
    checks.append(_run("Android SDK readiness", [sys.executable, "tools/check_android_sdk_readiness.py", "--allow-blocker"]))
    checks.append(_run("Android APK smoke readiness", [sys.executable, "tools/smoke_android_remote_controller.py", "--allow-missing-apk"]))
    if not args.skip_full_pytest:
        checks.append(_run("full pytest", [sys.executable, "-m", "pytest"]))
    checks.append(_run("macOS Swift build", ["swift", "build"], cwd=MACOS_CLIENT_DIR))
    checks.append(
        _run(
            "Android assembleDebug",
            ["./gradlew", ":app:assembleDebug", "--stacktrace"],
            cwd=ANDROID_CLIENT_DIR,
            env=_env_for_android(),
        )
    )

    failures: list[CheckResult] = []
    android_license_blockers: list[CheckResult] = []
    for result in checks:
        if result.returncode == 0:
            _print_result(result)
            continue
        if result.name == "Android assembleDebug" and _is_android_license_blocker(result):
            object.__setattr__(result, "status", "blocked: android-sdk-license")
            android_license_blockers.append(result)
            _print_result(result)
            continue
        failures.append(result)
        _print_result(result)

    if failures:
        print("\nVerification failed.")
        return 1
    if android_license_blockers and not args.allow_android_license_blocker:
        print("\nVerification blocked by Android SDK License acceptance.")
        return 2

    if android_license_blockers:
        print("\nVerification passed except for the acknowledged Android SDK License blocker.")
    else:
        print("\nVerification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
