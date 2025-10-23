#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PyInstaller 자동 빌드 스크립트
- 이전 버전 자동 백업 (타임스탬프 기반)
- 빌드 산출물 자동 정리
- release 폴더에 최종 실행파일만 출력
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# ==================== 설정 ====================
PROJECT_ROOT = Path(__file__).parent
RELEASE_DIR = PROJECT_ROOT / "release"
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"

# 빌드 대상
MAIN_SCRIPT = "homework_helper.pyw"
APP_NAME = "homework_helper"
EXE_NAME = f"{APP_NAME}.exe"

# 포함할 리소스
DATAS = [
    ("font", "font"),
    ("img", "img"),
]

# Hidden imports (PyInstaller가 자동 탐지 못하는 모듈)
HIDDEN_IMPORTS = [
    "uvicorn",
    "fastapi",
    "sqlalchemy",
    "requests",
    "PyQt6",
    "psutil",
]

# Windows 전용 imports
if os.name == 'nt':
    HIDDEN_IMPORTS.extend([
        "win32api",
        "win32security",
        "win32process",
        "win32con",
        "win32com.client",
    ])

# ================================================


def print_section(title):
    """섹션 제목 출력"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def backup_existing_exe():
    """기존 .exe 파일을 타임스탬프로 백업"""
    exe_path = RELEASE_DIR / EXE_NAME

    if not exe_path.exists():
        print(f"기존 실행파일 없음. 백업 생략.")
        return

    # 파일 생성 시간 가져오기
    timestamp = os.path.getctime(exe_path)
    dt = datetime.fromtimestamp(timestamp)
    backup_name = f"{APP_NAME}_{dt.strftime('%y-%m-%d-%H%M%S')}.exe"
    backup_path = RELEASE_DIR / backup_name

    # 백업
    try:
        shutil.move(str(exe_path), str(backup_path))
        print(f"[OK] 이전 버전 백업: {backup_name}")
    except Exception as e:
        print(f"[경고] 백업 실패: {e}")


def clean_build_artifacts():
    """빌드 산출물 폴더 삭제"""
    print_section("빌드 산출물 정리")

    for folder in [BUILD_DIR, DIST_DIR]:
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
    else:
        print(f"[OK] release 폴더 확인")


def build_with_pyinstaller():
    """PyInstaller로 빌드"""
    print_section("PyInstaller 빌드 시작")

    # PyInstaller 명령 생성
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",  # 콘솔 창 숨김
        "--onefile",   # 단일 실행파일
        "--clean",     # 이전 빌드 캐시 정리
    ]

    # 아이콘 설정 (있으면)
    icon_path = PROJECT_ROOT / "img" / "app_icon.ico"
    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])

    # 데이터 파일 추가
    for src, dest in DATAS:
        src_path = PROJECT_ROOT / src
        if src_path.exists():
            cmd.extend(["--add-data", f"{src};{dest}"])

    # Hidden imports 추가
    for module in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", module])

    # 메인 스크립트
    cmd.append(str(PROJECT_ROOT / MAIN_SCRIPT))

    # 명령 출력
    print(f"빌드 명령:\n{' '.join(cmd)}\n")

    # 실행
    try:
        result = subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
        print("\n[OK] 빌드 성공!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[오류] 빌드 실패: {e}")
        return False


def copy_to_release():
    """dist 폴더의 .exe를 release 폴더로 복사"""
    print_section("최종 실행파일 복사")

    src_exe = DIST_DIR / EXE_NAME
    dest_exe = RELEASE_DIR / EXE_NAME

    if not src_exe.exists():
        print(f"[오류] 실행파일 없음: {src_exe}")
        return False

    try:
        shutil.copy2(str(src_exe), str(dest_exe))
        print(f"[OK] 복사 완료: {EXE_NAME} -> release/")

        # 파일 크기 출력
        size_mb = dest_exe.stat().st_size / (1024 * 1024)
        print(f"  파일 크기: {size_mb:.2f} MB")
        return True
    except Exception as e:
        print(f"[오류] 복사 실패: {e}")
        return False


def main():
    """메인 함수"""
    print_section("숙제 관리자 빌드 스크립트")
    print(f"프로젝트 경로: {PROJECT_ROOT}")
    print(f"빌드 대상: {MAIN_SCRIPT}")

    # 0. 메인 스크립트 존재 확인
    if not (PROJECT_ROOT / MAIN_SCRIPT).exists():
        print(f"\n[오류] {MAIN_SCRIPT} 파일을 찾을 수 없습니다.")
        return 1

    # 1. release 폴더 생성
    print_section("준비 단계")
    ensure_release_dir()

    # 2. 기존 실행파일 백업
    backup_existing_exe()

    # 3. 이전 빌드 산출물 정리
    clean_build_artifacts()

    # 4. PyInstaller 빌드
    if not build_with_pyinstaller():
        return 1

    # 5. 최종 실행파일을 release 폴더로 복사
    if not copy_to_release():
        return 1

    # 6. 빌드 산출물 정리
    clean_build_artifacts()

    # 완료
    print_section("빌드 완료!")
    print(f"[OK] 실행파일 경로: {RELEASE_DIR / EXE_NAME}")
    print(f"[OK] 이전 버전들: {RELEASE_DIR}/ 폴더 참조")
    print("\n" + "=" * 60 + "\n")

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
