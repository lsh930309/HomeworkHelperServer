#!/usr/bin/env python3
"""Smoke/preflight Android HomeworkHelper Remote APK on a device or emulator.

This script is intentionally safe to run before the Android SDK License is
accepted: by default it reports the missing APK/adb/device as an explicit
blocker instead of pretending the Android lane is green.  Once the APK exists,
it can install the debug build and launch the main activity via adb.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = PROJECT_ROOT / "remote_clients" / "android" / "HomeworkHelperRemote"
DEFAULT_APK = ANDROID_ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
DEFAULT_PACKAGE = "dev.homeworkhelper.remote"
DEFAULT_ACTIVITY = "dev.homeworkhelper.remote/.MainActivity"
DEFAULT_ANDROID_SDK_ROOT = Path("/opt/homebrew/share/android-commandlinetools")
USAGE_ACCESS_SETTINGS_ACTION = "android.settings.USAGE_ACCESS_SETTINGS"
USAGE_STATS_OP = "android:get_usage_stats"


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    output: str


def _run(command: list[str]) -> CommandResult:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return CommandResult(tuple(command), completed.returncode, completed.stdout)


def _adb_path(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    found = shutil.which("adb")
    if found:
        return found
    sdk_root = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or DEFAULT_ANDROID_SDK_ROOT)
    candidate = sdk_root / "platform-tools" / "adb"
    return str(candidate) if candidate.exists() else None


def _connected_devices(adb: str) -> list[str]:
    result = _run([adb, "devices"])
    if result.returncode != 0:
        raise RuntimeError(f"adb devices failed:\n{result.output}")
    devices: list[str] = []
    for line in result.output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def _package_installed(adb: str, package_name: str, *, device: str | None = None) -> bool:
    command = [adb]
    if device:
        command.extend(["-s", device])
    command.extend(["shell", "pm", "path", package_name])
    result = _run(command)
    return result.returncode == 0 and f"package:{package_name}" in result.output


def _usage_stats_appop(adb: str, package_name: str, *, device: str | None = None) -> str:
    result = _run(_command_with_device(adb, device, ["shell", "cmd", "appops", "get", package_name, "GET_USAGE_STATS"]))
    output = result.output.strip()
    if result.returncode != 0 or not output:
        return f"unknown ({output or 'no appops output'})"
    return output


def _usage_stats_allowed(appop_output: str) -> bool:
    return bool(re.search(r"\ballow\b", appop_output, flags=re.IGNORECASE))


def _open_usage_access_settings(adb: str, *, device: str | None = None) -> CommandResult:
    return _run(_command_with_device(adb, device, ["shell", "am", "start", "-a", USAGE_ACCESS_SETTINGS_ACTION]))


def _assert_manifest_contract() -> None:
    build_file = ANDROID_ROOT / "app" / "build.gradle.kts"
    manifest = ANDROID_ROOT / "app" / "src" / "main" / "AndroidManifest.xml"
    build_text = build_file.read_text(encoding="utf-8")
    manifest_text = manifest.read_text(encoding="utf-8")
    if f'applicationId = "{DEFAULT_PACKAGE}"' not in build_text:
        raise AssertionError(f"applicationId must remain {DEFAULT_PACKAGE}")
    for marker in ["android.intent.action.MAIN", "android.intent.category.LAUNCHER", "android.permission.INTERNET"]:
        if marker not in manifest_text:
            raise AssertionError(f"Android manifest missing {marker}")


def _command_with_device(adb: str, device: str | None, rest: list[str]) -> list[str]:
    command = [adb]
    if device:
        command.extend(["-s", device])
    command.extend(rest)
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install/launch smoke for Android HomeworkHelper Remote APK.")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK, help="Path to the debug APK to install.")
    parser.add_argument("--adb", default=None, help="Path to adb; defaults to PATH or ANDROID_HOME/platform-tools/adb.")
    parser.add_argument("--device", default=None, help="Explicit adb serial. Defaults to the only connected device.")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="Android applicationId/package name.")
    parser.add_argument("--activity", default=DEFAULT_ACTIVITY, help="Component passed to adb shell am start -n.")
    parser.add_argument(
        "--allow-missing-apk",
        action="store_true",
        help="Exit 0 when the APK is missing, while still reporting the blocker. Useful before SDK License acceptance.",
    )
    parser.add_argument("--skip-install", action="store_true", help="Do not run adb install; only verify device/package and launch.")
    parser.add_argument("--skip-launch", action="store_true", help="Do not launch the activity after install/package verification.")
    parser.add_argument("--report-usage-access", action="store_true", help="Report GET_USAGE_STATS appop state after package verification.")
    parser.add_argument("--require-usage-access", action="store_true", help="Fail unless GET_USAGE_STATS appop is allowed after package verification.")
    parser.add_argument("--open-usage-access-settings", action="store_true", help="Open Android Usage Access settings after package verification.")
    args = parser.parse_args(argv)

    try:
        _assert_manifest_contract()
    except Exception as exc:
        print(f"Android smoke contract failed: {exc}", file=sys.stderr)
        return 1

    if not args.apk.exists():
        message = f"Android APK missing: {args.apk}. Run ./gradlew :app:assembleDebug after accepting Android SDK licenses."
        print(message)
        return 0 if args.allow_missing_apk else 2

    adb = _adb_path(args.adb)
    if not adb:
        print("adb not found. Install Android platform-tools or set --adb/ANDROID_HOME.", file=sys.stderr)
        return 2

    try:
        devices = _connected_devices(adb)
    except Exception as exc:
        print(f"Android smoke blocked: {exc}", file=sys.stderr)
        return 2
    device = args.device
    if device:
        if device not in devices:
            print(f"Requested adb device {device!r} is not connected. Connected: {devices}", file=sys.stderr)
            return 2
    else:
        if len(devices) != 1:
            print(f"Expected exactly one connected adb device; connected={devices}. Use --device.", file=sys.stderr)
            return 2
        device = devices[0]

    if not args.skip_install:
        install_result = _run(_command_with_device(adb, device, ["install", "-r", str(args.apk)]))
        print(install_result.output.rstrip())
        if install_result.returncode != 0:
            print("adb install failed", file=sys.stderr)
            return 1

    if not _package_installed(adb, args.package, device=device):
        print(f"Package {args.package} is not installed on {device}.", file=sys.stderr)
        return 1

    if args.report_usage_access or args.require_usage_access:
        usage_appop = _usage_stats_appop(adb, args.package, device=device)
        print(f"UsageStats appop: {usage_appop}")
        if args.require_usage_access and not _usage_stats_allowed(usage_appop):
            print(
                "UsageStats access not allowed. Re-run with --open-usage-access-settings and enable the app in Android settings.",
                file=sys.stderr,
            )
            return 1

    if args.open_usage_access_settings:
        settings_result = _open_usage_access_settings(adb, device=device)
        print(settings_result.output.rstrip())
        if settings_result.returncode != 0:
            print("opening Usage Access settings failed", file=sys.stderr)
            return 1

    if not args.skip_launch:
        launch_result = _run(_command_with_device(adb, device, ["shell", "am", "start", "-n", args.activity]))
        print(launch_result.output.rstrip())
        if launch_result.returncode != 0:
            print("adb launch failed", file=sys.stderr)
            return 1
        if not re.search(r"Status: ok|Starting:", launch_result.output, flags=re.IGNORECASE):
            print("adb launch output did not confirm activity start", file=sys.stderr)
            return 1

    print(f"Android Remote Controller smoke passed on {device}: {args.package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
