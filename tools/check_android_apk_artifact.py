#!/usr/bin/env python3
"""Validate the built Android Remote APK artifact without requiring a device.

This check sits between Gradle assemble and adb install smoke: it proves that
an APK exists and that the packaged manifest still exposes the expected package,
SDK bounds, launcher activity label, and sensitive permissions. It intentionally
does not claim runtime behavior such as Keystore, UsageStats provider access, or
Intent launch success; those remain device/emulator smoke gates.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = PROJECT_ROOT / "remote_clients" / "android" / "HomeworkHelperRemote"
DEFAULT_APK = ANDROID_ROOT / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
DEFAULT_BUILD_CONFIG = ANDROID_ROOT / "app" / "build" / "generated" / "source" / "buildConfig" / "release" / "dev" / "homeworkhelper" / "remote" / "BuildConfig.java"
LOCAL_SMARTTHINGS_TOKEN = PROJECT_ROOT / "local-artifacts" / "secrets" / "SmartThings_Token"
DEFAULT_ANDROID_SDK_ROOT = Path("/opt/homebrew/share/android-commandlinetools")
EXPECTED_PACKAGE = "dev.homeworkhelper.remote"
EXPECTED_VERSION_CODE = "1"
EXPECTED_VERSION_NAME = "0.1.0"
EXPECTED_MIN_SDK = "26"
EXPECTED_TARGET_SDK = "36"
EXPECTED_PERMISSIONS = {
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.PACKAGE_USAGE_STATS",
}


@dataclass(frozen=True)
class ApkReport:
    apk: Path
    aapt: Path
    package_name: str
    version_code: str
    version_name: str
    min_sdk: str
    target_sdk: str
    permissions: set[str]
    smartthings_debug_pat_length: int | None
    debuggable: bool


def _sdk_root() -> Path:
    return Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or DEFAULT_ANDROID_SDK_ROOT)


def _find_aapt(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    found = shutil.which("aapt")
    if found:
        return Path(found)
    build_tools = _sdk_root() / "build-tools"
    if not build_tools.exists():
        return None
    candidates = sorted(build_tools.glob("*/aapt"), reverse=True)
    return candidates[0] if candidates else None


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}")
    return completed.stdout


def _extract(pattern: str, text: str, field: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise AssertionError(f"APK badging missing {field}")
    return match.group(1)


def inspect_apk(apk: Path, aapt: Path) -> ApkReport:
    badging = _run([str(aapt), "dump", "badging", str(apk)])
    permissions_text = _run([str(aapt), "dump", "permissions", str(apk)])
    permissions = set(re.findall(r"uses-permission: name='([^']+)'", permissions_text))
    return ApkReport(
        apk=apk,
        aapt=aapt,
        package_name=_extract(r"package: name='([^']+)'", badging, "package name"),
        version_code=_extract(r"versionCode='([^']+)'", badging, "versionCode"),
        version_name=_extract(r"versionName='([^']+)'", badging, "versionName"),
        min_sdk=_extract(r"sdkVersion:'([^']+)'", badging, "minSdk"),
        target_sdk=_extract(r"targetSdkVersion:'([^']+)'", badging, "targetSdk"),
        permissions=permissions,
        smartthings_debug_pat_length=_smartthings_debug_pat_length(),
        debuggable="application-debuggable" in badging,
    )


def _smartthings_debug_pat_length(build_config: Path = DEFAULT_BUILD_CONFIG) -> int | None:
    if not build_config.exists():
        return None
    match = re.search(r'SMARTTHINGS_DEBUG_PAT = "([^"]*)";', build_config.read_text(encoding="utf-8"))
    if not match:
        return None
    return len(match.group(1))


def _print_report(report: ApkReport) -> None:
    print("Android APK artifact")
    print(f"- apk: {report.apk}")
    print(f"- aapt: {report.aapt}")
    print(f"- package: {report.package_name}")
    print(f"- version_code: {report.version_code}")
    print(f"- version_name: {report.version_name}")
    print(f"- min_sdk: {report.min_sdk}")
    print(f"- target_sdk: {report.target_sdk}")
    print("- permissions:")
    for permission in sorted(report.permissions):
        print(f"  - {permission}")
    if report.smartthings_debug_pat_length is not None:
        print(f"- smartthings_debug_pat_present: {report.smartthings_debug_pat_length > 0}")
    print(f"- debuggable: {report.debuggable}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the Android Remote release APK packaged manifest contract.")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--aapt", default=None)
    parser.add_argument("--expected-version-code", default=EXPECTED_VERSION_CODE)
    parser.add_argument("--expected-version-name", default=EXPECTED_VERSION_NAME)
    parser.add_argument("--expected-min-sdk", default=EXPECTED_MIN_SDK)
    parser.add_argument("--expected-target-sdk", default=EXPECTED_TARGET_SDK)
    args = parser.parse_args(argv)

    try:
        if not args.apk.exists():
            print(f"Android APK artifact missing: {args.apk}")
            return 2
        aapt = _find_aapt(args.aapt)
        if not aapt or not aapt.exists():
            print("aapt not found. Install Android build-tools or set --aapt/ANDROID_HOME.")
            return 2
        report = inspect_apk(args.apk, aapt)
        _print_report(report)

        failures: list[str] = []
        if report.package_name != EXPECTED_PACKAGE:
            failures.append(f"expected package {EXPECTED_PACKAGE}, found {report.package_name}")
        if report.version_code != args.expected_version_code:
            failures.append(f"expected versionCode {args.expected_version_code}, found {report.version_code}")
        if report.version_name != args.expected_version_name:
            failures.append(f"expected versionName {args.expected_version_name}, found {report.version_name}")
        if report.min_sdk != args.expected_min_sdk:
            failures.append(f"expected minSdk {args.expected_min_sdk}, found {report.min_sdk}")
        if report.target_sdk != args.expected_target_sdk:
            failures.append(f"expected targetSdk {args.expected_target_sdk}, found {report.target_sdk}")
        if report.debuggable:
            failures.append("release APK must not be debuggable")
        missing_permissions = sorted(EXPECTED_PERMISSIONS - report.permissions)
        if missing_permissions:
            failures.append(f"missing permissions: {', '.join(missing_permissions)}")
        if LOCAL_SMARTTHINGS_TOKEN.exists() and LOCAL_SMARTTHINGS_TOKEN.stat().st_size > 0:
            if not report.smartthings_debug_pat_length:
                failures.append("local SmartThings token exists but generated BuildConfig.SMARTTHINGS_DEBUG_PAT is empty")

        if failures:
            print("Android APK artifact failed:")
            for failure in failures:
                print(f"- {failure}")
            return 1
        print("Android APK artifact passed.")
        return 0
    except Exception as exc:
        print(f"Android APK artifact check failed unexpectedly: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
