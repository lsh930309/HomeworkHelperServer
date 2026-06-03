#!/usr/bin/env python3
"""Build the optional Android tsnet bridge AAR."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NATIVE_DIR = PROJECT_ROOT / "remote_clients/android/HomeworkHelperRemote/native/tailnetbridge"
DEFAULT_OUTPUT = PROJECT_ROOT / "local-artifacts/android-tailnet/homeworkhelper-tailnet.aar"
DEFAULT_ANDROID_HOME = Path.home() / "Library/Android/sdk"
DEFAULT_ANDROID_NDK_HOME = DEFAULT_ANDROID_HOME / "ndk/29.0.14206865"
DEFAULT_TARGET = "android/arm64"
DEFAULT_ANDROID_API = "26"


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def validate_aar(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"AAR was not created: {path}")
    with zipfile.ZipFile(path) as aar:
        names = set(aar.namelist())
        required = {
            "classes.jar",
            "jni/arm64-v8a/libgojni.so",
        }
        missing = sorted(required - names)
        if missing:
            raise SystemExit(f"AAR is missing required entries: {', '.join(missing)}")
        with aar.open("classes.jar") as classes_file:
            jar_bytes = classes_file.read()
    classes_tmp = path.with_suffix(".classes.jar")
    classes_tmp.write_bytes(jar_bytes)
    try:
        with zipfile.ZipFile(classes_tmp) as classes:
            class_names = set(classes.namelist())
        expected = {
            "dev/homeworkhelper/remote/nativebridge/tailnetbridge/Bridge.class",
            "dev/homeworkhelper/remote/nativebridge/tailnetbridge/Tailnetbridge.class",
        }
        missing = sorted(expected - class_names)
        if missing:
            raise SystemExit(f"AAR classes.jar is missing bridge classes: {', '.join(missing)}")
    finally:
        classes_tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--androidapi", default=DEFAULT_ANDROID_API)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    env = os.environ.copy()
    env.setdefault("ANDROID_HOME", str(DEFAULT_ANDROID_HOME))
    env.setdefault("ANDROID_NDK_HOME", str(DEFAULT_ANDROID_NDK_HOME))
    env.setdefault("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.skip_tests:
        run(["go", "test", "./..."], cwd=NATIVE_DIR, env=env)
    run(
        [
            "gomobile",
            "bind",
            f"-target={args.target}",
            f"-androidapi={args.androidapi}",
            "-javapkg=dev.homeworkhelper.remote.nativebridge",
            "-o",
            str(args.output),
            ".",
        ],
        cwd=NATIVE_DIR,
        env=env,
    )
    validate_aar(args.output)
    print(f"Android tailnet bridge AAR: {args.output} ({args.output.stat().st_size} bytes)")
    print("Gradle property: homeworkhelper.android.embeddedTailnetAar=" + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
