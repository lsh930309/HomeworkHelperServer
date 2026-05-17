#!/usr/bin/env python3
"""Run the physical-device Android Remote verification stage.

Connect one Android device with USB debugging enabled, then run this script.
The script installs/launches the APK, reports Usage Access state, and drives the
full Android UI e2e through adb with adb reverse so no emulator or LAN IP is
required.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADB = "/opt/homebrew/share/android-commandlinetools/platform-tools/adb"


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]


def _run(step: Step) -> None:
    print(f"\n==> {step.name}", flush=True)
    print("$ " + " ".join(step.command), flush=True)
    completed = subprocess.run(step.command, cwd=PROJECT_ROOT, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Android Remote physical-device verification.")
    parser.add_argument("--adb", default=DEFAULT_ADB, help="Path to adb.")
    parser.add_argument("--device", default=None, help="Explicit adb serial when more than one device is connected.")
    parser.add_argument("--port", type=int, default=8000, help="Temporary host Remote Agent port used by e2e smoke.")
    args = parser.parse_args(argv)

    device_args = ["--adb", args.adb]
    if args.device:
        device_args.extend(["--device", args.device])

    steps = [
        Step(
            "Device install/launch smoke",
            [sys.executable, "tools/smoke_android_remote_controller.py", *device_args, "--report-usage-access"],
        ),
        Step(
            "Device UI e2e smoke via adb reverse",
            [
                sys.executable,
                "tools/smoke_android_remote_e2e.py",
                *device_args,
                "--port",
                str(args.port),
                "--adb-reverse",
                "--android-base-url",
                f"http://127.0.0.1:{args.port}",
            ],
        ),
    ]
    for step in steps:
        _run(step)
    print("\nAndroid physical-device verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
