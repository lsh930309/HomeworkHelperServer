#!/usr/bin/env python3
"""One-time Windows setup: install Python 3.14 and recreate project .venv."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


PYTHON_PACKAGE_ID = "Python.Python.3.14"
PYTHON_SELECTOR = "-3.14"


def fail(message: str) -> NoReturn:
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(1)


def run(command: list[str]) -> None:
    print(f"> {' '.join(command)}")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        fail(f"Command failed with exit code {completed.returncode}: {command[0]}")


def captured(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        fail(detail or f"Command failed with exit code {completed.returncode}: {command[0]}")
    return completed.stdout.strip()


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def assert_no_links(root: Path) -> None:
    for current_root, directories, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_root)
        for name in [*directories, *files]:
            candidate = current / name
            is_junction = getattr(candidate, "is_junction", lambda: False)
            if candidate.is_symlink() or is_junction():
                fail(f"Refusing to remove a link or junction inside .venv: {candidate}")


def find_python_launcher() -> str:
    launcher = shutil.which("py")
    if launcher:
        return launcher

    windows_directory = os.environ.get("WINDIR")
    if windows_directory:
        system_launcher = Path(windows_directory) / "py.exe"
        if system_launcher.is_file():
            return str(system_launcher)
    fail("Python Launcher (py.exe) was not found after installing Python 3.14.")


def main() -> int:
    if os.name != "nt":
        fail("This script can only run on Windows.")
    if not ctypes.windll.shell32.IsUserAnAdmin():
        fail("Run this script from PowerShell or Command Prompt as Administrator.")

    project_root = Path(__file__).resolve().parent
    venv_path = project_root / ".venv"
    if venv_path.parent != project_root:
        fail(f"Unsafe .venv path: {venv_path}")
    if is_inside(Path(sys.executable), venv_path):
        fail(
            "This script is running from the .venv that it must replace. "
            "Deactivate it and run: py -3.13 reset_windows_python314_venv.py"
        )

    winget = shutil.which("winget")
    if not winget:
        fail("winget was not found. Install or update Microsoft App Installer and retry.")

    print("[1/3] Installing or updating system Python 3.14.")
    run(
        [
            winget,
            "install",
            "--id",
            PYTHON_PACKAGE_ID,
            "--exact",
            "--source",
            "winget",
            "--scope",
            "machine",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ]
    )

    launcher = find_python_launcher()
    installed_version = captured(
        [launcher, PYTHON_SELECTOR, "-c", "import platform; print(platform.python_version())"]
    )
    if not installed_version.startswith("3.14."):
        fail(f"Python 3.14 verification failed. Detected version: {installed_version}")
    print(f"      Detected Python version: {installed_version}")

    if venv_path.exists():
        if not venv_path.is_dir():
            fail(f".venv is not a directory: {venv_path}")
        if venv_path.is_symlink() or getattr(venv_path, "is_junction", lambda: False)():
            fail(f".venv is a link or junction: {venv_path}")
        assert_no_links(venv_path)

        print("[2/3] Existing virtual environment to remove:")
        print(f"      {venv_path}")
        if input("Type RECREATE to continue: ") != "RECREATE":
            fail("Virtual environment recreation was cancelled.")

        shutil.rmtree(venv_path)
        if venv_path.exists():
            fail(f"Failed to remove .venv: {venv_path}")
    else:
        print("[2/3] Existing .venv was not found; skipping removal.")

    print("[3/3] Creating the project .venv with Python 3.14.")
    run([launcher, PYTHON_SELECTOR, "-m", "venv", str(venv_path)])

    venv_python = venv_path / "Scripts" / "python.exe"
    if not venv_python.is_file():
        fail(f"Python executable was not found in .venv: {venv_python}")
    venv_version = captured(
        [str(venv_python), "-c", "import platform; print(platform.python_version())"]
    )
    if not venv_version.startswith("3.14."):
        fail(f"Recreated .venv version verification failed: {venv_version}")

    print()
    print(f"Completed: .venv Python {venv_version}")
    print("Run python build.py or .venv\\Scripts\\python.exe build.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
