#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PyInstaller 자동 빌드 스크립트 (Portable + Installer)
- .spec 파일 기반 빌드 (onedir 모드)
- ZIP 배포 파일 자동 생성 (Portable 버전)
- Inno Setup 인스톨러 자동 생성
- release 폴더에 최종 배포 파일 출력 (ZIP + Setup.exe)
"""

import os
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path
from datetime import datetime

# ==================== 설정 ====================
PROJECT_ROOT = Path(__file__).parent
RELEASE_DIR = PROJECT_ROOT / "release"
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"
INSTALLER_OUTPUT_DIR = PROJECT_ROOT / "installer_output"

# 빌드 대상
SPEC_FILE = PROJECT_ROOT / "homework_helper.spec"
APP_NAME = "homework_helper"
APP_FOLDER = DIST_DIR / APP_NAME  # onedir 결과물 폴더
APP_VERSION = "1.0.0"

# Inno Setup 경로 (일반적인 설치 경로)
INNO_SETUP_PATH = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
INSTALLER_SCRIPT = PROJECT_ROOT / "installer.iss"

# ================================================


def print_section(title):
    """섹션 제목 출력"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def clean_build_artifacts():
    """빌드 산출물 폴더 삭제"""
    print_section("이전 빌드 산출물 정리")

    for folder in [BUILD_DIR, DIST_DIR, INSTALLER_OUTPUT_DIR]:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                print(f"[OK] 삭제: {folder.name}/")
            except Exception as e:
                print(f"[경고] 삭제 실패 ({folder.name}): {e}")
        else:
            print(f"  (없음: {folder.name}/)")


def ensure_release_dir():
    """release 폴더 생성 (없으면)"""
    if not RELEASE_DIR.exists():
        RELEASE_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[OK] release 폴더 생성")
    return RELEASE_DIR


def build_with_pyinstaller():
    """PyInstaller로 .spec 파일 기반 빌드"""
    print_section("PyInstaller 빌드 시작 (onedir 모드)")

    if not SPEC_FILE.exists():
        print(f"[오류] .spec 파일 없음: {SPEC_FILE}")
        return False

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",  # 기존 빌드 덮어쓰기 확인 생략
        "--clean",      # 이전 빌드 캐시 정리
    ]

    print(f"빌드 명령: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
        print("\n[OK] PyInstaller 빌드 성공!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[오류] 빌드 실패: {e}")
        return False


def create_zip_distribution():
    """onedir 결과물을 ZIP으로 압축하여 release 폴더에 저장"""
    print_section("ZIP 배포 파일 생성")

    if not APP_FOLDER.exists():
        print(f"[오류] 배포 폴더 없음: {APP_FOLDER}")
        return False

    ensure_release_dir()
    zip_filename = f"HomeworkHelper_v{APP_VERSION}_Portable.zip"
    zip_path = RELEASE_DIR / zip_filename

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(APP_FOLDER):
                for file in files:
                    file_path = Path(root) / file
                    # ZIP 내 경로: homework_helper/...
                    arcname = file_path.relative_to(DIST_DIR)
                    zipf.write(file_path, arcname)

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"[OK] ZIP 생성 완료: {zip_filename}")
        print(f"  파일 크기: {size_mb:.2f} MB")
        print(f"  저장 위치: {zip_path}")
        return True
    except Exception as e:
        print(f"[오류] ZIP 생성 실패: {e}")
        return False


def create_installer():
    """Inno Setup으로 인스톨러 생성"""
    print_section("Inno Setup 인스톨러 생성")

    # Inno Setup 설치 확인
    if not INNO_SETUP_PATH.exists():
        print(f"[건너뛰기] Inno Setup이 설치되어 있지 않습니다.")
        print(f"  예상 경로: {INNO_SETUP_PATH}")
        print(f"  다운로드: https://jrsoftware.org/isinfo.php")
        return False

    # .iss 스크립트 확인
    if not INSTALLER_SCRIPT.exists():
        print(f"[오류] 인스톨러 스크립트 없음: {INSTALLER_SCRIPT}")
        return False

    # 앱 폴더 확인
    if not APP_FOLDER.exists():
        print(f"[오류] 배포 폴더 없음: {APP_FOLDER}")
        return False

    cmd = [str(INNO_SETUP_PATH), str(INSTALLER_SCRIPT)]
    print(f"인스톨러 명령: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, check=True, cwd=PROJECT_ROOT,
                                 capture_output=True, text=True)
        print(result.stdout)
        print("\n[OK] 인스톨러 생성 성공!")

        # 생성된 인스톨러를 release 폴더로 복사
        if INSTALLER_OUTPUT_DIR.exists():
            for setup_file in INSTALLER_OUTPUT_DIR.glob("*.exe"):
                dest = RELEASE_DIR / setup_file.name
                shutil.copy2(setup_file, dest)
                size_mb = dest.stat().st_size / (1024 * 1024)
                print(f"  인스톨러: {setup_file.name} ({size_mb:.2f} MB)")
                print(f"  저장 위치: {dest}")

        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[오류] 인스톨러 생성 실패: {e}")
        if e.stderr:
            print(f"오류 메시지:\n{e.stderr}")
        return False


def print_summary():
    """빌드 결과 요약"""
    print_section("빌드 완료 - 결과 요약")

    print("\n배포 파일 목록 (release 폴더):")
    print("-" * 70)

    if not RELEASE_DIR.exists():
        print("  (release 폴더 없음)")
        return

    has_files = False

    # 1. 인스톨러
    for setup_file in RELEASE_DIR.glob("*Setup*.exe"):
        size_mb = setup_file.stat().st_size / (1024 * 1024)
        print(f"  [인스톨러] {setup_file.name} ({size_mb:.2f} MB)")
        has_files = True

    # 2. ZIP
    for zip_file in RELEASE_DIR.glob("*.zip"):
        size_mb = zip_file.stat().st_size / (1024 * 1024)
        print(f"  [Portable] {zip_file.name} ({size_mb:.2f} MB)")
        has_files = True

    if not has_files:
        print("  (파일 없음)")

    print("-" * 70)
    print(f"\n배포 경로: {RELEASE_DIR.absolute()}")
    print("\n사용 방법:")
    print("  1. 설치 프로그램: *Setup*.exe 실행")
    print("  2. Portable 버전: *.zip 압축 해제 후 실행")


def main():
    """메인 함수"""
    print_section("HomeworkHelper 빌드 스크립트 (Portable + Installer)")
    print(f"프로젝트 경로: {PROJECT_ROOT}")
    print(f"최종 결과물: ZIP (Portable) + 인스톨러 (Setup.exe)")
    print(f"버전: {APP_VERSION}")

    # 0. .spec 파일 존재 확인
    if not SPEC_FILE.exists():
        print(f"\n[오류] {SPEC_FILE.name} 파일을 찾을 수 없습니다.")
        return 1

    # 1. 이전 빌드 산출물 정리
    clean_build_artifacts()

    # 2. PyInstaller 빌드 (onedir 모드)
    if not build_with_pyinstaller():
        print("\n[실패] 빌드 과정에서 오류가 발생했습니다.")
        return 1

    # 3. 배포 파일 생성
    success_count = 0

    # 3-1. ZIP 생성
    if create_zip_distribution():
        success_count += 1

    # 3-2. 인스톨러 생성 (Inno Setup 있는 경우)
    if create_installer():
        success_count += 1

    # 4. 결과 요약
    print_summary()

    if success_count == 0:
        print("\n[경고] 배포 파일이 생성되지 않았습니다.")
        return 1

    print("\n" + "=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[중단] 사용자에 의해 중단됨")
        sys.exit(1)
    except Exception as e:
        print(f"\n[오류] 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
