#!/usr/bin/env python3
"""Build a Finder-launchable macOS .app bundle for HomeworkHelperRemote.

`swift run` launches the SwiftUI executable as a terminal-attached process.
For manual UI testing, package the executable into an app bundle and launch it
with Finder/open so keyboard focus and lifecycle behave like a real app.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MACOS_ROOT = PROJECT_ROOT / "remote_clients" / "macos" / "HomeworkHelperRemote"
EXECUTABLE = MACOS_ROOT / ".build" / "release" / "HomeworkHelperRemote"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "dist" / "macos"
APP_NAME = "HomeworkHelperRemote.app"
BUNDLE_IDENTIFIER = "dev.homeworkhelper.remote.macos"
ICON_SOURCE = PROJECT_ROOT / "assets" / "icons" / "app" / "app_icon.png"
ICON_NAME = "HomeworkHelperRemote.icns"


def _run(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed ({completed.returncode}):\n{completed.stdout}")
    if completed.stdout.strip():
        print(completed.stdout.rstrip())


def _info_plist() -> dict[str, object]:
    return {
        "CFBundleDevelopmentRegion": "ko",
        "CFBundleDisplayName": "HomeworkHelper Remote",
        "CFBundleExecutable": "HomeworkHelperRemote",
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleIconFile": ICON_NAME,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "HomeworkHelperRemote",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "LSMinimumSystemVersion": "13.0",
        "NSAppTransportSecurity": {
            # Remote Agent is intentionally exposed on a private LAN/Tailscale
            # HTTP endpoint during local remote-control testing. Pairing +
            # bearer tokens still protect the command surface.
            "NSAllowsArbitraryLoads": True,
        },
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    }


def _copy_icon(resources: Path) -> None:
    if not ICON_SOURCE.exists():
        return
    iconset = resources / "HomeworkHelperRemote.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 128, 256, 512]
    for size in sizes:
        target = iconset / f"icon_{size}x{size}.png"
        _run(["sips", "-z", str(size), str(size), str(ICON_SOURCE), "--out", str(target)], cwd=PROJECT_ROOT)
        retina = iconset / f"icon_{size}x{size}@2x.png"
        _run(["sips", "-z", str(size * 2), str(size * 2), str(ICON_SOURCE), "--out", str(retina)], cwd=PROJECT_ROOT)
    _run(["iconutil", "-c", "icns", str(iconset), "-o", str(resources / ICON_NAME)], cwd=PROJECT_ROOT)
    shutil.rmtree(iconset, ignore_errors=True)


def package_app(output_dir: Path) -> Path:
    _run(["swift", "build", "-c", "release"], cwd=MACOS_ROOT)
    if not EXECUTABLE.exists():
        raise FileNotFoundError(f"Swift release executable missing: {EXECUTABLE}")

    app = output_dir / APP_NAME
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    if app.exists():
        shutil.rmtree(app)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    target_executable = macos / "HomeworkHelperRemote"
    shutil.copy2(EXECUTABLE, target_executable)
    target_executable.chmod(0o755)
    try:
        _copy_icon(resources)
    except Exception as exc:
        print(f"warning: app icon generation skipped: {exc}")
    with (contents / "Info.plist").open("wb") as file:
        plistlib.dump(_info_plist(), file, sort_keys=True)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package HomeworkHelperRemote as a macOS .app bundle.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    try:
        app = package_app(args.output_dir)
    except Exception as exc:
        print(f"macOS app packaging failed: {exc}", file=sys.stderr)
        return 1
    print(f"macOS app packaged: {app}")
    print(f"Launch with: open {app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
