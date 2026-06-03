#!/usr/bin/env python3
"""Run the device-free Android Remote internal verification stage."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = PROJECT_ROOT / "remote_clients" / "android" / "HomeworkHelperRemote"
DEFAULT_JAVA_HOME = "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
DEFAULT_ANDROID_HOME = "/opt/homebrew/share/android-commandlinetools"
DEFAULT_SANDBOX_HOME = Path("/private/tmp/homeworkhelper-android-verify-home")
DEFAULT_GRADLE_HOME = Path("/private/tmp/homeworkhelper-android-gradle")
DEFAULT_ANDROID_USER_HOME = Path("/private/tmp/homeworkhelper-android-user")


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    cwd: Path = PROJECT_ROOT


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("JAVA_HOME", DEFAULT_JAVA_HOME)
    env.setdefault("ANDROID_HOME", DEFAULT_ANDROID_HOME)
    env.setdefault("ANDROID_SDK_ROOT", env["ANDROID_HOME"])
    DEFAULT_SANDBOX_HOME.mkdir(parents=True, exist_ok=True)
    DEFAULT_GRADLE_HOME.mkdir(parents=True, exist_ok=True)
    DEFAULT_ANDROID_USER_HOME.mkdir(parents=True, exist_ok=True)
    env.setdefault("GRADLE_USER_HOME", str(DEFAULT_GRADLE_HOME))
    env.setdefault("ANDROID_USER_HOME", str(DEFAULT_ANDROID_USER_HOME))
    gradle_opts = env.get("GRADLE_OPTS", "")
    for option in [
        f"-Duser.home={DEFAULT_SANDBOX_HOME}",
        "-Dkotlin.daemon.enabled=false",
    ]:
        if option not in gradle_opts:
            gradle_opts = f"{gradle_opts} {option}".strip()
    env["GRADLE_OPTS"] = gradle_opts
    return env


def _run(step: Step, env: dict[str, str]) -> None:
    print(f"\n==> {step.name}", flush=True)
    print("$ " + " ".join(step.command), flush=True)
    completed = subprocess.run(step.command, cwd=step.cwd, env=env, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    env = _env()
    steps = [
        Step("Android static contract", [sys.executable, "-m", "pytest", "tests/test_remote_android_client_static.py"]),
        Step("Android SDK readiness", [sys.executable, "tools/check_android_sdk_readiness.py"]),
        Step("Gradle assembleRelease", ["./gradlew", ":app:assembleRelease", "--stacktrace"], cwd=ANDROID_ROOT),
        Step("APK artifact contract", [sys.executable, "tools/check_android_apk_artifact.py"]),
    ]
    for step in steps:
        _run(step, env)
    print("\nAndroid internal verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
