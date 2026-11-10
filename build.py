#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build and package the native HomeworkHelper product for this checkout."""

import os
import sys
import shutil
import subprocess
import zipfile
import re
import platform
import argparse
import hashlib
import importlib.metadata
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from tools.version_policy import BuildVersion, VersionLedger, VersionPolicyError, read_snapshot

# ==================== 설정 ====================
PROJECT_ROOT = Path(__file__).parent
RELEASE_DIR = PROJECT_ROOT / "release"
ARCHIVES_DIR = RELEASE_DIR / "archives"
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"
WINDOWS_VERSION_FILE = "build.version.json"
DASHBOARD_FRONTEND_DIR = PROJECT_ROOT / "src" / "api" / "dashboard" / "frontend"
DASHBOARD_STATIC_BUILD_DIR = BUILD_DIR / "dashboard-static"
DASHBOARD_CACHE_DIR = BUILD_DIR / "dashboard-cache"

SPEC_FILE = PROJECT_ROOT / "homework_helper.spec"
APP_NAME = "homework_helper"
APP_FOLDER = DIST_DIR / APP_NAME

INNO_SETUP_PATH = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
INSTALLER_SCRIPT = PROJECT_ROOT / "installer.iss"
MACOS_PACKAGE_TOOL = PROJECT_ROOT / "tools" / "package_macos_remote_app.py"
MACOS_CLIENT_DIR = PROJECT_ROOT / "clients" / "macos"
MACOS_APP_NAME = "HomeworkHelperRemote.app"
MACOS_APP_BUNDLE = DIST_DIR / "macos" / MACOS_APP_NAME
MACOS_SWIFT_RELEASE_EXECUTABLE = MACOS_CLIENT_DIR / ".build" / "release" / "HomeworkHelperRemote"
MACOS_APP_EXECUTABLE = MACOS_APP_BUNDLE / "Contents" / "MacOS" / "HomeworkHelperRemote"
MACOS_APP_PROCESS_NAME = "HomeworkHelperRemote"
MACOS_PKG_SCRIPTS_DIR = BUILD_DIR / "macos-pkg-scripts"
MACOS_CODESIGN_IDENTITY_ENV = "HH_MACOS_CODESIGN_IDENTITY"
MACOS_DEFAULT_CODESIGN_IDENTITY = "HomeworkHelperRemote Local Code Signing"

VERSION_ID = r"(?:v[0-9]+\.[0-9]+\.[0-9]+|dev\.[1-9][0-9]*)"
VERSIONED_PACKAGE_NAME = re.compile(
    rf"(?:HomeworkHelper_{VERSION_ID}_(?:Setup\.exe|Portable\.zip)|HomeworkHelperRemote_{VERSION_ID}\.pkg)"
)
WINDOWS_ARCHIVE_ID = rf"(?:{VERSION_ID}|v[0-9]+\.[0-9]+\.[0-9]+_b[1-9][0-9]*_g[0-9a-f]{{4,40}})"
WINDOWS_PACKAGE_PAIR = re.compile(rf"HomeworkHelper_(?P<version>{WINDOWS_ARCHIVE_ID})_(?:Setup\.exe|Portable\.zip)")
WINDOWS_PYTHON_VERSION = (3, 14)
WINDOWS_REQUIRED_DISTRIBUTIONS = (
    "PySide6",
    "PyInstaller",
    "pywin32",
    "winshell",
    "pycaw",
    "Windows-Toasts",
    "winrt-Windows.Gaming.Input",
    "winrt-Windows.Media.Control",
    "winrt-Windows.Foundation",
    "winrt-Windows.Foundation.Collections",
    "winrt-Windows.Media",
    "winrt-Windows.Storage.Streams",
)

# 코드 서명
CERT_DIR = PROJECT_ROOT / "certs"
CERT_THUMBPRINT_FILE = CERT_DIR / ".thumbprint"
# ================================================


class BuildConfigError(RuntimeError):
    """Raised when local build configuration is missing or invalid."""


def configure_console_output(stdout=None, stderr=None) -> None:
    """Replace glyphs unsupported by the active Windows console encoding."""
    streams = (
        sys.stdout if stdout is None else stdout,
        sys.stderr if stderr is None else stderr,
    )
    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def bootstrap_windows_build_runtime(
    argv: list[str],
    *,
    system_name: str | None = None,
    project_root: Path = PROJECT_ROOT,
    python_executable: str | None = None,
    python_version: tuple[int, int] | None = None,
    runner=subprocess.run,
    launcher_finder=shutil.which,
) -> int | None:
    """Update the repository .venv and delegate without shell activation."""
    if (system_name or platform.system()) != "Windows":
        return None

    current_python = Path(python_executable or sys.executable)
    current_version = python_version or tuple(sys.version_info[:2])
    managed_python = project_root / ".venv" / "Scripts" / "python.exe"

    if not managed_python.exists():
        if current_version == WINDOWS_PYTHON_VERSION:
            launcher = [str(current_python)]
        else:
            py_launcher = launcher_finder("py")
            if not py_launcher:
                raise BuildConfigError(
                    "Python 3.14가 필요합니다. Python Launcher를 포함해 Python 3.14를 "
                    "설치한 뒤 build.py를 다시 실행하세요."
                )
            launcher = [str(py_launcher), "-3.14"]
        print(f"[준비] Windows 프로젝트 가상환경 생성: {managed_python.parent.parent}")
        created = runner([*launcher, "-m", "venv", str(managed_python.parent.parent)], cwd=project_root)
        if created.returncode != 0 or not managed_python.exists():
            raise BuildConfigError("Windows 프로젝트 Python 3.14 가상환경 생성에 실패했습니다.")

    if current_python.resolve() != managed_python.resolve():
        delegated = runner(
            [str(managed_python), str(project_root / "build.py"), *argv],
            cwd=project_root,
        )
        return int(delegated.returncode)

    print("[준비] requirements.txt 의존성 설치 및 업데이트")
    installed = runner(
        [
            str(managed_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            "-r",
            str(project_root / "requirements.txt"),
        ],
        cwd=project_root,
    )
    if installed.returncode != 0:
        raise BuildConfigError("Windows 빌드 의존성 설치에 실패했습니다.")
    return None


def installed_distribution_versions(names: tuple[str, ...]) -> dict[str, str]:
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "missing"
    return versions


def validate_windows_build_runtime(
    *,
    python_version: tuple[int, int] | None = None,
    distribution_versions=None,
) -> dict[str, str]:
    """Require Python 3.14, build dependencies, and one Qt binding."""
    current_version = python_version or tuple(sys.version_info[:2])
    if current_version != WINDOWS_PYTHON_VERSION:
        raise BuildConfigError(
            "Windows 빌드는 Python 3.14가 필요합니다. "
            f"현재 버전: {current_version[0]}.{current_version[1]}"
        )

    version_reader = distribution_versions or installed_distribution_versions
    versions = version_reader(WINDOWS_REQUIRED_DISTRIBUTIONS)
    missing = [name for name, version in versions.items() if version == "missing"]
    if missing:
        raise BuildConfigError("Windows 빌드 필수 패키지가 없습니다: " + ", ".join(missing))

    bindings = version_reader(("PySide6", "PyQt6"))
    installed_bindings = [name for name, version in bindings.items() if version != "missing"]
    if installed_bindings != ["PySide6"]:
        found = ", ".join(installed_bindings) if installed_bindings else "없음"
        raise BuildConfigError(
            "Windows 빌드 환경에는 PySide6만 설치되어야 합니다. "
            f"현재 감지된 Qt 바인딩: {found}"
        )
    return versions


def select_build_target(system_name: str | None = None) -> str:
    """Return the release target for the current OS."""
    system_name = system_name or platform.system()
    if system_name == "Windows":
        return "windows-host"
    if system_name == "Darwin":
        return "macos-client"
    raise BuildConfigError(f"지원하지 않는 빌드 환경입니다: {system_name or 'unknown'}")


def determine_parallel_jobs(cpu_count: int | None = None) -> int:
    cpu_count = cpu_count or os.cpu_count() or 1
    return max(1, min(int(cpu_count), 12))


def release_filename(prefix: str, version_info: dict, suffix: str, extension: str) -> str:
    suffix_part = f"_{suffix}" if suffix else ""
    return f"{prefix}_{version_info['string']}{suffix_part}.{extension}"


def checkout_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, errors="surrogateescape", capture_output=True,
    ).stdout.strip()


def clean_checkout_commit(repo: Path) -> str:
    if checkout_git(repo, "status", "--porcelain"):
        raise BuildConfigError("작업 checkout에 커밋되지 않은 변경 사항이 있습니다.")
    return checkout_git(repo, "rev-parse", "HEAD")


def make_policy_version_info(snapshot: BuildVersion) -> dict:
    return {
        "target": "windows-host" if snapshot.product == "host" else "macos-client",
        "version": snapshot.version,
        "base_version": snapshot.base_version,
        "string": snapshot.version if snapshot.version.startswith("dev.") else f"v{snapshot.version}",
        "git_hash": snapshot.commit,
        "jobs": determine_parallel_jobs(),
    }


def load_windows_version_info(repo: Path | None = None) -> dict:
    """Read the Mac-issued version of this exact, clean Windows checkout."""
    repo = PROJECT_ROOT if repo is None else repo
    try:
        commit = clean_checkout_commit(repo)
        snapshot = read_snapshot(repo / WINDOWS_VERSION_FILE, product="host", commit=commit)
    except (OSError, ValueError, subprocess.SubprocessError, VersionPolicyError) as exc:
        raise BuildConfigError(f"Windows 빌드 버전 확인 실패. 맥에서 먼저 소스를 준비하세요. {exc}") from exc
    return make_policy_version_info(snapshot)


def load_macos_version_info(repo: Path | None = None) -> dict:
    """Resolve the client version from the Mac ledger before starting native tools."""
    repo = PROJECT_ROOT if repo is None else repo
    try:
        commit = clean_checkout_commit(repo)
        branch = checkout_git(repo, "branch", "--show-current")
        ledger = VersionLedger(repo)
        if not branch:
            event, issued = ledger.read_main(commit) or (None, None)
            if event not in {"minor", "major"} or issued is None or issued.product != "client":
                raise BuildConfigError("브랜치를 선택하거나, 발급된 클라이언트 릴리즈 커밋에서 실행하세요.")
        snapshot = ledger.resolve_build("client", commit, development=branch not in {"main", ""})
    except (OSError, ValueError, subprocess.SubprocessError, VersionPolicyError) as exc:
        raise BuildConfigError(f"macOS 빌드 버전 확인 실패. {exc}") from exc
    return make_policy_version_info(snapshot)


def windows_package_paths(version_info: dict, release_dir: Path | None = None) -> tuple[Path, Path]:
    release_dir = RELEASE_DIR if release_dir is None else release_dir
    return (
        release_dir / release_filename("HomeworkHelper", version_info, "Setup", "exe"),
        release_dir / release_filename("HomeworkHelper", version_info, "Portable", "zip"),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BuildLog:
    """Stream the native build log to the calling console."""

    def log(self, message="", style=None):
        print(message)

    def log_section(self, title):
        self.log("\n" + "=" * 70)
        self.log(title)
        self.log("=" * 70)

    def set_status(self, status):
        self.log(f"[상태] {status}")

def artifact_archive_bucket(file_path: Path) -> tuple[str, str] | None:
    """Return (target, artifact_type) for release artifacts that should be archived."""
    name = file_path.name
    suffix = file_path.suffix.lower()
    if suffix not in {".exe", ".zip", ".pkg"}:
        return None
    if not (
        name.startswith("HomeworkHelper_")
        or name.startswith("HomeworkHelperRemote_")
    ):
        return None
    if name.startswith("HomeworkHelperRemote_"):
        target = "macos-client"
    else:
        target = "windows-host"
    artifact_type = {
        ".exe": "installer",
        ".zip": "portable",
        ".pkg": "pkg",
    }[suffix]
    return target, artifact_type


def iter_release_artifacts_for_archive() -> list[Path]:
    if not RELEASE_DIR.exists():
        return []
    return [
        path
        for path in RELEASE_DIR.iterdir()
        if path.is_file() and artifact_archive_bucket(path) is not None
    ]


def _complete_windows_pair(paths: tuple[Path, Path]) -> bool:
    return all(path.is_file() and path.stat().st_size > 0 for path in paths)


def _archive_windows_pair(console, release_id: str) -> int:
    """Publish a complete immutable pair before removing any active files."""
    info = {"string": release_id}
    active = windows_package_paths(info)
    archive = ARCHIVES_DIR / "windows-host"
    pair_dir = archive / "by-version" / release_id
    archived = 0
    if pair_dir.exists():
        if not _complete_windows_pair(windows_package_paths(info, pair_dir)):
            raise BuildConfigError(f"보관된 Windows 패키지 쌍이 불완전합니다: {release_id}")
    else:
        # An unambiguous package pair from the previous layout is already a backup.
        existing = [list(archive.rglob(path.name)) for path in active]
        has_previous = all(len(paths) == 1 for paths in existing) and _complete_windows_pair(
            (existing[0][0], existing[1][0])
        )
        if not has_previous and _complete_windows_pair(active):
            pair_dir.parent.mkdir(parents=True, exist_ok=True)
            # Staging lives outside the Windows archive reader's namespace.
            with tempfile.TemporaryDirectory(prefix=".pair-stage-", dir=ARCHIVES_DIR) as temporary:
                staged = Path(temporary)
                for file in active:
                    shutil.copy2(file, staged / file.name)
                staged.rename(pair_dir)
            archived = 2
            console.log(f"  ✓ {release_id} Setup·Portable 쌍 보관")
        elif not has_previous:
            console.log(f"  ⚠ 미완성 Windows 산출물 정리: {release_id}", "warning")

    for file in active:
        file.unlink(missing_ok=True)
    return archived


def prune_archive_files(console, *, keep: int = 10, days: int = 90):
    """Keep archives bounded by target/type count and age."""
    if keep < 1:
        keep = 1
    if not ARCHIVES_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=max(1, days))
    deleted = 0
    windows_pairs = ARCHIVES_DIR / "windows-host" / "by-version"
    pairs = []
    for folder in windows_pairs.glob("*"):
        if folder.is_dir() and re.fullmatch(WINDOWS_ARCHIVE_ID, folder.name):
            paths = windows_package_paths({"string": folder.name}, folder)
            if _complete_windows_pair(paths):
                pairs.append((max(path.stat().st_mtime for path in paths), folder))
    for index, (mtime, folder) in enumerate(sorted(pairs, reverse=True)):
        if index >= keep or datetime.fromtimestamp(mtime) < cutoff:
            try:
                # Remove the pair from the restore namespace in one operation.
                with tempfile.TemporaryDirectory(prefix=".pair-prune-", dir=ARCHIVES_DIR) as temporary:
                    folder.rename(Path(temporary) / folder.name)
                deleted += 2
            except OSError as error:
                console.log(f"  ⚠ Windows archive 정리 실패 ({folder.name}): {error}", 'warning')

    bucket_dirs = [
        path
        for path in ARCHIVES_DIR.glob("*/*")
        if path.is_dir() and path != windows_pairs
    ]
    for bucket_dir in bucket_dirs:
        archived_files = sorted(
            [path for path in bucket_dir.glob("*/*") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for index, file_path in enumerate(archived_files):
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            if index >= keep or mtime < cutoff:
                try:
                    file_path.unlink()
                    deleted += 1
                except Exception as e:
                    console.log(f"  ⚠ archive pruning 실패 ({file_path.name}): {e}", 'warning')

    # 빈 날짜/버킷 디렉터리를 뒤에서부터 정리한다.
    for folder in sorted(ARCHIVES_DIR.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        if folder.is_dir():
            try:
                next(folder.iterdir())
            except StopIteration:
                folder.rmdir()
            except Exception:
                pass

    if deleted:
        console.log(f"  ✓ 오래된 archive {deleted}개 정리 완료")


def archive_old_files(console, *, archive_keep: int = 10, archive_days: int = 90, prune_archives: bool = True):
    """이전 산출물을 보관하고 새 버전은 이름당 한 경로를 유지한다."""
    console.log_section("이전 버전 파일 아카이빙")
    console.set_status("이전 버전 파일 아카이빙 중...")

    date_folder = datetime.now().strftime("%y-%m-%d")
    files_to_archive = iter_release_artifacts_for_archive()

    if not files_to_archive:
        console.log("  (아카이빙할 파일 없음)")
        if prune_archives:
            prune_archive_files(console, keep=archive_keep, days=archive_days)
        return

    archived_count = 0
    windows_versions = set()
    for file_path in files_to_archive:
        match = WINDOWS_PACKAGE_PAIR.fullmatch(file_path.name)
        if match:
            windows_versions.add(match["version"])
            continue
        bucket = artifact_archive_bucket(file_path)
        if bucket is None:
            continue
        target, artifact_type = bucket
        slot = "by-version" if VERSIONED_PACKAGE_NAME.fullmatch(file_path.name) else date_folder
        archive_subdir = ARCHIVES_DIR / target / artifact_type / slot

        archive_subdir.mkdir(parents=True, exist_ok=True)
        dest = archive_subdir / file_path.name
        if slot == "by-version":
            file_path.replace(dest)
        else:
            shutil.move(str(file_path), str(dest))
        archived_count += 1
        console.log(f"  ✓ {file_path.name} → archives/{target}/{artifact_type}/{slot}/")

    for release_id in sorted(windows_versions):
        archived_count += _archive_windows_pair(console, release_id)

    console.log(f"\n총 {archived_count}개 파일 아카이빙 완료", 'success')
    if prune_archives:
        prune_archive_files(console, keep=archive_keep, days=archive_days)


def clean_build_artifacts(console):
    """빌드 산출물 폴더 삭제"""
    console.log_section("이전 빌드 산출물 정리")
    console.set_status("이전 빌드 산출물 정리 중...")

    for folder in [BUILD_DIR, DIST_DIR]:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                console.log(f"  ✓ 삭제: {folder.name}/", 'success')
            except Exception as e:
                console.log(f"  ⚠ 삭제 실패 ({folder.name}): {e}", 'warning')
        else:
            console.log(f"  (없음: {folder.name}/)")



def cleanup_intermediate_artifacts(console, *, deep_clean: bool = False):
    """빌드 종료 후 최종 release 산출물을 제외한 중간 산출물을 정리."""
    console.log_section("중간 산출물 정리")
    for folder in [DIST_DIR, BUILD_DIR]:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                console.log(f"  ✓ 삭제: {folder.relative_to(PROJECT_ROOT)}/", 'success')
            except Exception as e:
                console.log(f"  ⚠ 삭제 실패 ({folder.name}): {e}", 'warning')
    if deep_clean:
        swift_build = MACOS_CLIENT_DIR / ".build"
        for folder in [swift_build]:
            if folder.exists():
                try:
                    shutil.rmtree(folder)
                    console.log(f"  ✓ deep-clean 삭제: {folder.relative_to(PROJECT_ROOT)}/", 'success')
                except Exception as e:
                    console.log(f"  ⚠ deep-clean 실패 ({folder.name}): {e}", 'warning')


def ensure_release_dir(console):
    """release 폴더 생성"""
    if not RELEASE_DIR.exists():
        RELEASE_DIR.mkdir(parents=True, exist_ok=True)
        console.log("  ✓ release 폴더 생성", 'success')
    return RELEASE_DIR



def build_dashboard_frontend(console):
    """대시보드 프론트엔드 번들을 ignored build 디렉터리에 생성."""
    frontend_dir = DASHBOARD_FRONTEND_DIR
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        console.log("  (대시보드 프론트엔드 package.json 없음 - 건너뜀)")
        return True

    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        console.log("  ✗ npm을 찾을 수 없어 대시보드 번들을 생성할 수 없습니다.", 'error')
        return False

    console.log_section("대시보드 프론트엔드 빌드")
    console.set_status("대시보드 프론트엔드 빌드 중...")

    install_cmd = [npm_cmd, "ci"] if (frontend_dir / "package-lock.json").exists() else [npm_cmd, "install"]
    for cmd in (install_cmd, [npm_cmd, "run", "build"]):
        console.log(f"실행: {' '.join(cmd)}")
        try:
            process = subprocess.run(
                cmd,
                cwd=frontend_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=False,
            )
        except Exception as e:
            console.log(f"✗ 대시보드 빌드 명령 실행 실패: {e}", 'error')
            return False
        if process.stdout:
            for line in process.stdout.splitlines():
                if line.strip():
                    console.log(f"  {line}")
        if process.returncode != 0:
            console.log(f"✗ 대시보드 빌드 실패 (exit={process.returncode})", 'error')
            return False

    expected = (
        DASHBOARD_STATIC_BUILD_DIR / "dashboard.js",
        DASHBOARD_STATIC_BUILD_DIR / "dashboard.css",
    )
    missing = [path for path in expected if not path.exists()]
    if missing:
        console.log("✗ 대시보드 빌드 산출물이 없습니다: " + ", ".join(str(path) for path in missing), 'error')
        return False

    # 과거 빌드가 소스 트리에 남긴 산출물은 패키징 입력이 되지 않도록 제거합니다.
    for stale in (
        PROJECT_ROOT / "src" / "api" / "dashboard" / "static" / "index.html",
        PROJECT_ROOT / "src" / "api" / "dashboard" / "static" / "dashboard.js",
        PROJECT_ROOT / "src" / "api" / "dashboard" / "static" / "dashboard.css",
        frontend_dir / "tsconfig.tsbuildinfo",
    ):
        if stale.exists():
            try:
                stale.unlink()
                console.log(f"  ✓ 소스 트리 산출물 제거: {stale.relative_to(PROJECT_ROOT)}")
            except Exception as e:
                console.log(f"  ⚠ 생성 파일 정리 실패 ({stale.name}): {e}", 'warning')

    console.log(f"✓ 대시보드 프론트엔드 빌드 완료: {DASHBOARD_STATIC_BUILD_DIR.relative_to(PROJECT_ROOT)}", 'success')
    return True

def build_with_pyinstaller(console):
    """PyInstaller로 빌드"""
    console.log_section("PyInstaller 빌드 시작 (onedir 모드)")
    console.set_status("PyInstaller 빌드 중...")

    if not SPEC_FILE.exists():
        console.log(f"✗ .spec 파일 없음: {SPEC_FILE}", 'error')
        return False

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--clean",
    ]

    console.log(f"빌드 명령: {' '.join(cmd)}\n")

    try:
        pyinstaller_env = dict(os.environ)
        pyinstaller_env["QT_API"] = "PySide6"
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=PROJECT_ROOT,
            env=pyinstaller_env,
            bufsize=1
        )

        for line in process.stdout:
            if line.strip():
                console.log(f"  → {line.strip()}")

        process.wait()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)

        console.log("\n✓ PyInstaller 빌드 성공!", 'success')
        return True
    except subprocess.CalledProcessError as e:
        console.log(f"\n✗ 빌드 실패: {e}", 'error')
        return False


def find_signtool():
    """Windows SDK에서 signtool.exe 경로를 자동 탐색"""
    # 일반적인 Windows SDK 경로들
    sdk_roots = [
        Path(r"C:\Program Files (x86)\Windows Kits\10\bin"),
        Path(r"C:\Program Files\Windows Kits\10\bin"),
    ]

    for sdk_root in sdk_roots:
        if not sdk_root.exists():
            continue
        # 가장 최신 SDK 버전 폴더 사용
        version_dirs = sorted(sdk_root.glob("10.*"), reverse=True)
        for version_dir in version_dirs:
            signtool = version_dir / "x64" / "signtool.exe"
            if signtool.exists():
                return signtool

    # PATH에서 찾기
    signtool_in_path = shutil.which("signtool")
    if signtool_in_path:
        return Path(signtool_in_path)

    return None


def sign_file(console, file_path, signtool_path, cert_thumbprint):
    """개별 파일에 코드 서명 적용 (Windows 인증서 저장소 기반)"""
    file_path = Path(file_path)
    if not file_path.exists():
        console.log(f"  ⚠ 파일 없음: {file_path.name}", 'warning')
        return False

    cmd = [
        str(signtool_path), "sign",
        "/s", "My",
        "/sha1", cert_thumbprint,
        "/fd", "SHA256",
        "/td", "SHA256",
        "/tr", "http://timestamp.digicert.com",
        "/d", "HomeworkHelper",
        str(file_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )
        if result.returncode == 0:
            console.log(f"  ✓ 서명 완료: {file_path.name}", 'success')
            return True
        else:
            console.log(f"  ✗ 서명 실패: {file_path.name}", 'error')
            console.log(f"    {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        console.log(f"  ✗ 서명 타임아웃: {file_path.name}", 'error')
        return False
    except Exception as e:
        console.log(f"  ✗ 서명 오류: {e}", 'error')
        return False


def sign_build_artifacts(console, _version_info, target_files=None):
    """빌드 산출물에 코드 서명 적용

    Args:
        target_files: 서명할 파일 경로 리스트. None이면 dist 내 메인 exe를 서명.
    Returns:
        bool: 서명 성공 여부 (signtool/인증서 미발견 시에도 True 반환)
    """
    console.log_section("코드 서명")
    console.set_status("코드 서명 중...")

    # signtool 탐색
    signtool_path = find_signtool()
    if not signtool_path:
        console.log("  ⚠ signtool.exe를 찾을 수 없습니다", 'warning')
        console.log("    Windows SDK를 설치하면 코드 서명이 가능합니다")
        console.log("    https://developer.microsoft.com/windows/downloads/windows-sdk/")
        return True  # 서명 없이 계속 진행

    console.log(f"  signtool: {signtool_path}")

    # 인증서 썸프린트 확인 (환경 변수 또는 파일)
    cert_thumbprint = os.environ.get("HH_CERT_THUMBPRINT", "")
    if not cert_thumbprint:
        if CERT_THUMBPRINT_FILE.exists():
            cert_thumbprint = CERT_THUMBPRINT_FILE.read_text(encoding='utf-8').strip()
        else:
            console.log("  ⚠ 인증서 썸프린트를 찾을 수 없습니다", 'warning')
            console.log("    환경 변수 HH_CERT_THUMBPRINT를 설정하거나")
            console.log(f"    certs/create_cert.ps1을 실행하여 {CERT_THUMBPRINT_FILE.name} 파일을 생성하세요")
            return True  # 서명 없이 계속 진행

    # 서명 대상 파일 결정
    if target_files is None:
        main_exe = APP_FOLDER / "homework_helper.exe"
        target_files = [main_exe, APP_FOLDER / "homework_helper_service.exe"]

    # 서명 수행
    signed_count = 0
    for file_path in target_files:
        if sign_file(console, file_path, signtool_path, cert_thumbprint):
            signed_count += 1

    console.log(f"\n  서명 결과: {signed_count}/{len(target_files)} 파일 서명 완료")
    return signed_count == len(target_files)


def create_zip_distribution(console, version_info):
    """ZIP 배포 파일 생성"""
    console.log_section("ZIP 배포 파일 생성")
    console.set_status("ZIP 파일 생성 중...")

    if not APP_FOLDER.exists():
        console.log(f"✗ 배포 폴더 없음: {APP_FOLDER}", 'error')
        return False

    ensure_release_dir(console)
    zip_filename = release_filename("HomeworkHelper", version_info, "Portable", "zip")
    zip_path = RELEASE_DIR / zip_filename

    try:
        console.log("파일 목록 수집 중...")
        all_files = []
        for root, dirs, files in os.walk(APP_FOLDER):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(DIST_DIR)
                all_files.append((file_path, arcname))

        console.log(f"총 {len(all_files)}개 파일 압축 중...")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, (file_path, arcname) in enumerate(all_files):
                zipf.write(file_path, arcname)

                # 진행률 업데이트 (65% ~ 75%)
                if i % 10 == 0:
                    console.log(f"  압축 중: {i}/{len(all_files)} 파일...")

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        console.log(f"\n✓ ZIP 생성 완료: {zip_filename}", 'success')
        console.log(f"  파일 크기: {size_mb:.2f} MB")
        console.log(f"  저장 위치: {zip_path}")
        return True
    except Exception as e:
        console.log(f"✗ ZIP 생성 실패: {e}", 'error')
        return False


def windows_installer_output_base(version_info):
    return f"HomeworkHelper_{version_info['string']}_Setup"


def create_inno_setup_command(version_info):
    """Build an ISCC command without mutating installer.iss."""
    return [
        str(INNO_SETUP_PATH),
        str(INSTALLER_SCRIPT),
        f"/DMyAppVersion={version_info['version']}",
        f"/DMyAppOutputBaseFilename={windows_installer_output_base(version_info)}",
    ]


def create_installer(console, version_info):
    """Inno Setup으로 인스톨러 생성"""
    console.log_section("Inno Setup 인스톨러 생성")
    console.set_status("인스톨러 생성 중...")

    if not INNO_SETUP_PATH.exists():
        console.log("⚠ Inno Setup이 설치되어 있지 않습니다", 'warning')
        console.log(f"  예상 경로: {INNO_SETUP_PATH}")
        console.log("  다운로드: https://jrsoftware.org/isinfo.php")
        return False

    if not INSTALLER_SCRIPT.exists():
        console.log(f"✗ 인스톨러 스크립트 없음: {INSTALLER_SCRIPT}", 'error')
        return False

    if not APP_FOLDER.exists():
        console.log(f"✗ 배포 폴더 없음: {APP_FOLDER}", 'error')
        return False

    cmd = create_inno_setup_command(version_info)
    console.log(f"인스톨러 명령: {' '.join(cmd)}\n")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=PROJECT_ROOT,
            bufsize=1
        )

        for line in process.stdout:
            if line.strip():
                console.log(f"  → {line.strip()}")

        process.wait()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)

        console.log("\n✓ 인스톨러 생성 성공!", 'success')

        expected_filename = f"{windows_installer_output_base(version_info)}.exe"
        generated_file = RELEASE_DIR / expected_filename

        if generated_file.exists():
            size_mb = generated_file.stat().st_size / (1024 * 1024)
            console.log(f"  인스톨러: {expected_filename} ({size_mb:.2f} MB)")
            console.log(f"  저장 위치: {generated_file}")
        else:
            console.log(f"✗ 생성된 인스톨러 파일을 찾을 수 없습니다: {expected_filename}", 'error')
            return False

        return True
    except subprocess.CalledProcessError as e:
        console.log(f"\n✗ 인스톨러 생성 실패: {e}", 'error')
        return False


def macos_pkg_path(version_info):
    return RELEASE_DIR / release_filename("HomeworkHelperRemote", version_info, "", "pkg")


def macos_pkg_preinstall_script(process_name: str = MACOS_APP_PROCESS_NAME) -> str:
    """Return the PKG preinstall script that stops the running macOS client."""
    return f"""#!/bin/sh
set +e

APP_PROCESS="{process_name}"

/usr/bin/pkill -TERM -x "$APP_PROCESS" >/dev/null 2>&1 || true

for _attempt in 1 2 3 4 5; do
  if ! /usr/bin/pgrep -x "$APP_PROCESS" >/dev/null 2>&1; then
    exit 0
  fi
  /bin/sleep 1
done

/usr/bin/pkill -KILL -x "$APP_PROCESS" >/dev/null 2>&1 || true
exit 0
"""


def prepare_macos_pkg_scripts_dir(scripts_dir: Path | None = None) -> Path:
    """Create pkgbuild scripts dir with a preinstall hook for in-place updates."""
    scripts_dir = scripts_dir or MACOS_PKG_SCRIPTS_DIR
    if scripts_dir.exists():
        shutil.rmtree(scripts_dir)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    preinstall = scripts_dir / "preinstall"
    preinstall.write_text(macos_pkg_preinstall_script(), encoding="utf-8")
    preinstall.chmod(0o755)
    return scripts_dir


def create_pkgbuild_command(app_bundle: Path, pkg_path: Path, scripts_dir: Path | None = None):
    scripts_dir = scripts_dir or MACOS_PKG_SCRIPTS_DIR
    return [
        "pkgbuild",
        "--component",
        str(app_bundle),
        "--install-location",
        "/Applications",
        "--scripts",
        str(scripts_dir),
        str(pkg_path),
    ]


def macos_codesign_identity(env: dict[str, str] | None = None) -> str:
    env = env or os.environ
    return (env.get(MACOS_CODESIGN_IDENTITY_ENV) or MACOS_DEFAULT_CODESIGN_IDENTITY).strip()


def resolve_macos_codesign_identity(identity: str) -> str:
    """Resolve one valid identity to its exact fingerprint, never a name substring."""
    if not identity or platform.system() != "Darwin" or not shutil.which("security"):
        raise RuntimeError("macOS code-signing identity를 확인할 수 없습니다.")
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"], cwd=PROJECT_ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    matches = []
    for fingerprint, name in re.findall(r'([A-Fa-f0-9]{40})\s+"([^"\n]+)"', result.stdout or ""):
        if identity == name or identity.upper() == fingerprint.upper():
            matches.append(fingerprint.upper())
    matches = list(dict.fromkeys(matches))
    if result.returncode != 0 or len(matches) != 1:
        raise RuntimeError(f"서명 identity 선택이 없거나 모호합니다: {identity} (유효 일치 {len(matches)}개)")
    return matches[0]


def macos_codesign_identity_available(identity: str) -> bool:
    try:
        resolve_macos_codesign_identity(identity)
        return True
    except (OSError, RuntimeError):
        return False


def create_macos_app_bundle_command(version_info: dict, output_dir: Path, codesign_identity: str) -> list[str]:
    # Keep the release label independent of the numeric version macOS requires.
    return [
        sys.executable,
        str(MACOS_PACKAGE_TOOL),
        "--output-dir",
        str(output_dir),
        "--version",
        version_info["base_version"],
        "--build",
        version_info["base_version"],
        "--jobs",
        str(version_info["jobs"]),
        "--release-id",
        version_info["string"],
        "--git-hash",
        version_info["git_hash"],
        "--codesign-identity",
        codesign_identity,
    ]


def build_macos_remote_app(console, version_info):
    """Build the Swift macOS remote client and package it as a .app bundle."""
    console.log_section("macOS Remote Client 앱 번들 생성")
    console.set_status("Swift release 빌드 및 .app 생성 중...")

    ensure_release_dir(console)
    if not MACOS_PACKAGE_TOOL.exists():
        console.log(f"✗ macOS 패키징 도구 없음: {MACOS_PACKAGE_TOOL}", 'error')
        return False

    output_dir = DIST_DIR / "macos"
    try:
        codesign_identity = resolve_macos_codesign_identity(macos_codesign_identity())
    except (OSError, RuntimeError) as error:
        console.log(f"✗ {error}", 'error')
        return False
    console.log(f"  macOS code-signing identity: {codesign_identity}")
    cmd = create_macos_app_bundle_command(version_info, output_dir, codesign_identity)
    console.log(f"앱 번들 명령: {' '.join(cmd)}\n")
    try:
        process = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as e:
        console.log(f"✗ macOS 앱 번들 명령 실행 실패: {e}", 'error')
        return False
    if process.stdout:
        for line in process.stdout.splitlines():
            if line.strip():
                console.log(f"  {line}")
    if process.returncode != 0:
        console.log(f"✗ macOS 앱 번들 생성 실패 (exit={process.returncode})", 'error')
        return False
    if not MACOS_APP_BUNDLE.exists():
        console.log(f"✗ 앱 번들을 찾을 수 없습니다: {MACOS_APP_BUNDLE}", 'error')
        return False
    if not MACOS_SWIFT_RELEASE_EXECUTABLE.exists():
        console.log(f"✗ Swift release 실행 파일을 찾을 수 없습니다: {MACOS_SWIFT_RELEASE_EXECUTABLE}", 'error')
        return False
    if not MACOS_APP_EXECUTABLE.exists():
        console.log(f"✗ 앱 번들 실행 파일을 찾을 수 없습니다: {MACOS_APP_EXECUTABLE}", 'error')
        return False
    swift_hash = sha256_file(MACOS_SWIFT_RELEASE_EXECUTABLE)
    app_hash = sha256_file(MACOS_APP_EXECUTABLE)
    console.log(f"  Swift release SHA256: {swift_hash}")
    console.log(f"  App bundle SHA256:   {app_hash}")
    if swift_hash != app_hash:
        console.log("  codesign 후 app bundle binary hash가 달라졌습니다. 서명된 번들에서는 정상입니다.", 'warning')
    console.log(
        "  App metadata: "
        f"release={version_info['string']}, git={version_info['git_hash']}"
    )
    return True


def create_macos_pkg(console, version_info):
    """Create a macOS .pkg installer in release/."""
    console.log_section("macOS PKG 인스톨러 생성")
    console.set_status("pkgbuild 실행 중...")

    if not shutil.which("pkgbuild"):
        console.log("✗ pkgbuild를 찾을 수 없습니다. Xcode Command Line Tools가 필요합니다.", 'error')
        return False
    if not MACOS_APP_BUNDLE.exists():
        console.log(f"✗ 앱 번들 없음: {MACOS_APP_BUNDLE}", 'error')
        return False
    pkg_path = macos_pkg_path(version_info)
    if pkg_path.exists():
        pkg_path.unlink()
    scripts_dir = prepare_macos_pkg_scripts_dir()
    console.log(f"PKG preinstall script: {scripts_dir / 'preinstall'}")
    cmd = create_pkgbuild_command(MACOS_APP_BUNDLE, pkg_path, scripts_dir)
    console.log(f"PKG 명령: {' '.join(cmd)}\n")
    try:
        process = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as e:
        pkg_path.unlink(missing_ok=True)
        console.log(f"✗ pkgbuild 실행 실패: {e}", 'error')
        return False
    if process.stdout:
        for line in process.stdout.splitlines():
            if line.strip():
                console.log(f"  {line}")
    if process.returncode != 0 or not pkg_path.is_file():
        pkg_path.unlink(missing_ok=True)
        console.log(f"✗ pkgbuild 산출물 생성 실패 (exit={process.returncode})", 'error')
        return False
    size_mb = pkg_path.stat().st_size / (1024 * 1024)
    console.log(f"✓ PKG 생성 완료: {pkg_path.name} ({size_mb:.2f} MB)", 'success')
    return True


def print_summary(console, version_info):
    """빌드 결과 요약"""
    console.log_section("빌드 완료 - 결과 요약")
    console.log(f"빌드 버전: {version_info['version']}")
    paths = (windows_package_paths(version_info) if version_info["target"] == "windows-host"
             else (macos_pkg_path(version_info),))
    for path in paths:
        size_mb = path.stat().st_size / (1024 * 1024)
        console.log(f"  {path} ({size_mb:.2f} MB)")


def run_windows_build(console, version_info) -> int:
    if not build_dashboard_frontend(console):
        return 0
    if not build_with_pyinstaller(console):
        return 0
    if not sign_build_artifacts(console, version_info):
        console.log("\n✗ 코드 서명 실패로 빌드를 중단합니다.", 'error')
        return 0

    setup, portable = windows_package_paths(version_info)
    complete = False
    try:
        if not create_zip_distribution(console, version_info) or not portable.is_file():
            return 0
        if not create_installer(console, version_info) or not setup.is_file():
            return 0
        if not sign_build_artifacts(console, version_info, target_files=[setup]):
            console.log("\n✗ 인스톨러 코드 서명 실패로 빌드를 중단합니다.", 'error')
            return 0
        complete = True
        return 2
    finally:
        if not complete:
            for path in (setup, portable):
                path.unlink(missing_ok=True)


def run_macos_build(console, version_info) -> int:
    if not build_macos_remote_app(console, version_info):
        return 0
    return 1 if create_macos_pkg(console, version_info) else 0


def run_build_process(console, version_info, *, archive_keep, archive_days, prune_archives, deep_clean) -> bool:
    try:
        archive_old_files(console, archive_keep=archive_keep, archive_days=archive_days, prune_archives=prune_archives)
        clean_build_artifacts(console)
        build_target = run_windows_build if version_info["target"] == "windows-host" else run_macos_build
        if not build_target(console, version_info):
            console.log("✗ 빌드 실패: 배포 파일을 완성하지 못했습니다.", 'error')
            return False
        print_summary(console, version_info)
        return True
    finally:
        cleanup_intermediate_artifacts(console, deep_clean=deep_clean)


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="HomeworkHelper platform-aware release builder.", allow_abbrev=False)
    parser.add_argument(
        "--target",
        choices=("windows-host", "macos-client"),
        default=None,
        help="빌드 타깃을 강제 지정합니다. 기본값은 현재 OS 자동 감지입니다.",
    )
    parser.add_argument(
        "--deep-clean",
        action="store_true",
        help="빌드 후 Swift .build 같은 플랫폼별 캐시까지 정리합니다.",
    )
    parser.add_argument(
        "--archive-keep",
        type=int,
        default=10,
        help="target/type별 archive에 보존할 최신 산출물 수입니다.",
    )
    parser.add_argument(
        "--archive-days",
        type=int,
        default=90,
        help="archive 산출물 보존 일수입니다.",
    )
    parser.add_argument(
        "--no-prune-archives",
        action="store_true",
        help="archive 자동 정리를 비활성화합니다.",
    )
    return parser.parse_args(argv)


def validate_target_inputs(target: str):
    if target == "windows-host":
        if platform.system() != "Windows":
            raise BuildConfigError("windows-host 빌드는 Windows 환경에서만 실행할 수 있습니다.")
        if not SPEC_FILE.exists():
            raise BuildConfigError(f"{SPEC_FILE.name} 파일을 찾을 수 없습니다.")
    if target == "macos-client" and platform.system() != "Darwin":
        raise BuildConfigError("macos-client 빌드는 macOS 환경에서만 실행할 수 있습니다.")


def main(argv: list[str] | None = None):
    """메인 함수"""
    configure_console_output()
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(effective_argv)
    try:
        target = args.target or select_build_target()
        validate_target_inputs(target)
        if target == "windows-host":
            version_info = load_windows_version_info()
            delegated_exit = bootstrap_windows_build_runtime(effective_argv)
            if delegated_exit is not None:
                return delegated_exit
            validate_windows_build_runtime()
        else:
            version_info = load_macos_version_info()
    except BuildConfigError as exc:
        print(f"[오류] {exc}")
        return 1

    console = BuildLog()
    console.log_section("빌드 설정")
    console.log(f"타깃: {version_info['target']}")
    console.log(f"버전: {version_info['version']}")
    console.log(f"병렬 작업 수: {version_info['jobs']}")
    success = run_build_process(
        console,
        version_info,
        archive_keep=args.archive_keep,
        archive_days=args.archive_days,
        prune_archives=not args.no_prune_archives,
        deep_clean=args.deep_clean,
    )
    return 0 if success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[중단] 사용자에 의해 중단됨")
        sys.exit(1)
    except Exception as e:
        print(f"\n[오류] 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
