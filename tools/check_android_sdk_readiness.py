#!/usr/bin/env python3
"""Report Android SDK readiness without accepting licenses or installing packages.

Exit codes:
- 0: required tools, packages, and license files appear ready.
- 2: expected setup blocker, such as missing SDK package/license/adb.
- 1: unexpected error or invalid repository contract.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ANDROID_SDK_ROOT = Path("/opt/homebrew/share/android-commandlinetools")
REQUIRED_PACKAGES = {
    "platform-tools": ("platform-tools",),
    "platforms;android-36": ("platforms", "android-36"),
    "build-tools;35.0.0": ("build-tools", "35.0.0"),
}
KNOWN_LICENSE_FILENAMES = (
    "android-sdk-license",
    "android-sdk-preview-license",
)


@dataclass(frozen=True)
class ReadinessResult:
    sdk_root: Path
    java_home: str | None
    sdkmanager: str | None
    adb: Path
    missing_packages: list[str]
    present_license_files: list[str]

    @property
    def ready(self) -> bool:
        return bool(self.sdkmanager) and self.adb.exists() and not self.missing_packages and bool(self.present_license_files)


def _find_sdkmanager(sdk_root: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    found = shutil.which("sdkmanager")
    if found:
        return found
    candidates = [
        sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager",
        sdk_root / "cmdline-tools" / "bin" / "sdkmanager",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _package_exists(sdk_root: Path, package_id: str) -> bool:
    parts = REQUIRED_PACKAGES[package_id]
    return (sdk_root.joinpath(*parts)).exists()


def check_readiness(*, sdk_root: Path, sdkmanager: str | None = None) -> ReadinessResult:
    resolved_sdkmanager = _find_sdkmanager(sdk_root, sdkmanager)
    missing = [package_id for package_id in REQUIRED_PACKAGES if not _package_exists(sdk_root, package_id)]
    licenses_dir = sdk_root / "licenses"
    present_licenses = [name for name in KNOWN_LICENSE_FILENAMES if (licenses_dir / name).exists()]
    return ReadinessResult(
        sdk_root=sdk_root,
        java_home=os.environ.get("JAVA_HOME"),
        sdkmanager=resolved_sdkmanager,
        adb=sdk_root / "platform-tools" / "adb",
        missing_packages=missing,
        present_license_files=present_licenses,
    )


def _print_report(result: ReadinessResult) -> None:
    print("Android SDK readiness")
    print(f"- sdk_root: {result.sdk_root}")
    print(f"- JAVA_HOME: {result.java_home or '(not set)'}")
    print(f"- sdkmanager: {result.sdkmanager or '(not found)'}")
    print(f"- adb: {result.adb} ({'present' if result.adb.exists() else 'missing'})")
    print("- required packages:")
    for package_id in REQUIRED_PACKAGES:
        print(f"  - {package_id}: {'missing' if package_id in result.missing_packages else 'present'}")
    print(f"- license files: {', '.join(result.present_license_files) if result.present_license_files else '(none found)'}")


_USAGE = """
Next setup steps after user approval:
  sdkmanager --licenses
  sdkmanager --install "platform-tools" "platforms;android-36" "build-tools;35.0.0"
  ./.venv/bin/python tools/verify_remote_controller.py
  ./.venv/bin/python tools/smoke_android_remote_controller.py
""".strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Android SDK package/license readiness without changing local SDK state.")
    parser.add_argument("--sdk-root", type=Path, default=Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or DEFAULT_ANDROID_SDK_ROOT))
    parser.add_argument("--sdkmanager", default=None)
    parser.add_argument("--allow-blocker", action="store_true", help="Exit 0 for expected missing SDK/license blockers after printing the report.")
    args = parser.parse_args(argv)

    try:
        result = check_readiness(sdk_root=args.sdk_root, sdkmanager=args.sdkmanager)
        _print_report(result)
        if result.ready:
            print("Android SDK readiness passed.")
            return 0
        print("Android SDK readiness blocked.")
        print(_USAGE)
        return 0 if args.allow_blocker else 2
    except Exception as exc:
        print(f"Android SDK readiness failed unexpectedly: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
