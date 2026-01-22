#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PyInstaller 자동 빌드 스크립트 (onedir + Inno Setup)
- .spec 파일 기반 빌드 (onedir 모드)
- ZIP 배포 파일 자동 생성
- Inno Setup 인스톨러 자동 생성
- 자동 버전 관리 및 이전 버전 아카이빙
- release 폴더에 최종 배포 파일 출력
"""

import os
import sys
import shutil
import subprocess
import zipfile
import re
from pathlib import Path
from datetime import datetime

# Windows에서만 작동하는 키보드 입력 라이브러리
if sys.platform == 'win32':
    import msvcrt
else:
    print("[오류] 이 스크립트는 Windows에서만 실행할 수 있습니다.")
    sys.exit(1)

# ==================== 설정 ====================
PROJECT_ROOT = Path(__file__).parent
RELEASE_DIR = PROJECT_ROOT / "release"
ARCHIVES_DIR = RELEASE_DIR / "archives"
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"
# INSTALLER_OUTPUT_DIR 제거: installer.iss에서 자동 생성

# 빌드 대상
SPEC_FILE = PROJECT_ROOT / "homework_helper.spec"
APP_NAME = "homework_helper"
APP_FOLDER = DIST_DIR / APP_NAME  # onedir 결과물 폴더

# Inno Setup 경로 (일반적인 설치 경로)
INNO_SETUP_PATH = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
INSTALLER_SCRIPT = PROJECT_ROOT / "installer.iss"

# 버전 패턴: HomeworkHelper_vA.B.C.yymmddhhmmss_*.{exe,zip}
VERSION_PATTERN = re.compile(r'v(\d+)\.(\d+)\.(\d+)\.(\d{12})')

# ================================================


def print_section(title):
    """섹션 제목 출력"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def get_latest_version():
    """release 폴더에서 최신 버전 찾기"""
    if not RELEASE_DIR.exists():
        return None

    latest_version = None
    latest_timestamp = None

    # release 폴더의 모든 exe, zip 파일 검사
    for file_path in RELEASE_DIR.glob("HomeworkHelper_v*"):
        match = VERSION_PATTERN.search(file_path.name)
        if match:
            major, minor, patch, timestamp = match.groups()
            version_tuple = (int(major), int(minor), int(patch), timestamp)

            if latest_version is None or version_tuple > latest_version:
                latest_version = version_tuple
                latest_timestamp = timestamp

    if latest_version:
        major, minor, patch, timestamp = latest_version
        return {
            'major': major,
            'minor': minor,
            'patch': patch,
            'timestamp': timestamp,
            'string': f"v{major}.{minor}.{patch}.{timestamp}"
        }

    return None


def interactive_version_input(latest_version):
    """대화형 버전 입력 UI"""
    print_section("버전 설정")

    # 기본값 설정
    if latest_version:
        current = [latest_version['major'], latest_version['minor'], latest_version['patch']]
        print(f"최신 버전: {latest_version['string']}")
        print(f"현재 기본값: v{current[0]}.{current[1]}.{current[2]}.yymmddhhmmss")
    else:
        current = [1, 0, 0]
        print("첫 번째 빌드입니다.")
        print(f"기본값: v{current[0]}.{current[1]}.{current[2]}.yymmddhhmmss")

    print("\n조작 방법:")
    print("  좌/우 방향키: 자릿수 이동 (A ← → B ← → C)")
    print("  상/하 방향키: 숫자 증가/감소")
    print("  Enter: 확정")
    print("  ESC: 취소")

    position = 0  # 0=major, 1=minor, 2=patch
    original = current.copy()

    def print_version():
        """현재 버전 상태 출력"""
        parts = []
        for i, num in enumerate(current):
            if i == position:
                parts.append(f"[{num}]")  # 현재 선택된 자리
            else:
                parts.append(str(num))
        print(f"\r버전 선택: v{'.'.join(parts)}               ", end='', flush=True)

    print()
    print_version()

    while True:
        if msvcrt.kbhit():
            key = msvcrt.getch()

            # ESC
            if key == b'\x1b':
                print("\n\n[취소] 빌드를 중단합니다.")
                return None

            # Enter
            elif key == b'\r':
                # 버전 검증: 원본보다 작으면 안 됨
                new_tuple = tuple(current)
                old_tuple = tuple(original)

                if new_tuple < old_tuple:
                    print("\n\n[오류] 이전 버전보다 낮은 버전은 설정할 수 없습니다.")
                    print(f"  이전: v{original[0]}.{original[1]}.{original[2]}")
                    print(f"  입력: v{current[0]}.{current[1]}.{current[2]}")
                    print("\n다시 입력해주세요.")
                    print_version()
                    continue

                timestamp = datetime.now().strftime("%y%m%d%H%M%S")
                version_string = f"v{current[0]}.{current[1]}.{current[2]}.{timestamp}"
                print(f"\n\n선택된 버전: {version_string}")
                return {
                    'major': current[0],
                    'minor': current[1],
                    'patch': current[2],
                    'timestamp': timestamp,
                    'string': version_string
                }

            # 방향키
            elif key == b'\xe0':  # 확장 키 (방향키)
                arrow = msvcrt.getch()

                # 좌
                if arrow == b'K':
                    position = max(0, position - 1)

                # 우
                elif arrow == b'M':
                    position = min(2, position + 1)

                # 상 (증가)
                elif arrow == b'H':
                    # 앞자리가 증가하면 뒷자리 0으로 초기화
                    old_value = current[position]
                    current[position] += 1

                    if current[position] > old_value:
                        # major가 증가하면 minor, patch를 0으로
                        if position == 0:
                            current[1] = 0
                            current[2] = 0
                        # minor가 증가하면 patch를 0으로
                        elif position == 1:
                            current[2] = 0

                # 하 (감소, 원본보다 작아질 수 없음)
                elif arrow == b'P':
                    new_value = [current[0], current[1], current[2]]
                    new_value[position] = max(0, current[position] - 1)

                    # 감소 후 버전이 원본보다 작아지는지 확인
                    if tuple(new_value) >= tuple(original):
                        current[position] = new_value[position]

                print_version()


def archive_old_files(new_version):
    """이전 버전 파일들을 archives 폴더로 이동"""
    print_section("이전 버전 파일 아카이빙")

    if not RELEASE_DIR.exists():
        print("  (이전 버전 파일 없음)")
        return

    # 현재 날짜 폴더 (yy-mm-dd)
    date_folder = datetime.now().strftime("%y-%m-%d")

    archived_count = 0

    # Installer와 Portable 파일 각각 처리
    for file_path in RELEASE_DIR.glob("HomeworkHelper_v*"):
        if file_path.is_file():
            # 파일 타입 확인
            if file_path.suffix == '.exe':
                archive_subdir = ARCHIVES_DIR / "installer" / date_folder
            elif file_path.suffix == '.zip':
                archive_subdir = ARCHIVES_DIR / "portable" / date_folder
            else:
                continue

            # 아카이브 폴더 생성
            archive_subdir.mkdir(parents=True, exist_ok=True)

            # 파일 이동
            dest = archive_subdir / file_path.name
            shutil.move(str(file_path), str(dest))
            print(f"[OK] 아카이빙: {file_path.name} → {archive_subdir.relative_to(RELEASE_DIR)}/")
            archived_count += 1

    if archived_count == 0:
        print("  (아카이빙할 파일 없음)")
    else:
        print(f"\n총 {archived_count}개 파일 아카이빙 완료")


def clean_build_artifacts():
    """빌드 산출물 폴더 삭제"""
    print_section("이전 빌드 산출물 정리")

    for folder in [BUILD_DIR, DIST_DIR]:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                print(f"[OK] 삭제: {folder.name}/")
            except Exception as e:
                print(f"[경고] 삭제 실패 ({folder.name}): {e}")
        else:
            print(f"  (없음: {folder.name}/)")

    # installer_output은 Inno Setup이 자동 생성하므로 미리 만들 필요 없음
    # 하지만 이전 빌드의 잔여 파일은 정리
    # installer_output_dir = PROJECT_ROOT / "installer_output"
    # if installer_output_dir.exists():
    #     try:
    #         shutil.rmtree(installer_output_dir)
    #         print(f"[OK] 삭제: installer_output/")
    #     except Exception as e:
    #         print(f"[경고] 삭제 실패 (installer_output): {e}")


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


def create_zip_distribution(version_info):
    """onedir 결과물을 ZIP으로 압축하여 release 폴더에 저장"""
    print_section("ZIP 배포 파일 생성")

    if not APP_FOLDER.exists():
        print(f"[오류] 배포 폴더 없음: {APP_FOLDER}")
        return False

    ensure_release_dir()
    zip_filename = f"HomeworkHelper_{version_info['string']}_Portable.zip"
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


def update_installer_script_version(version_info):
    """installer.iss 파일의 버전 정보 업데이트"""
    if not INSTALLER_SCRIPT.exists():
        return False

    try:
        with open(INSTALLER_SCRIPT, 'r', encoding='utf-8') as f:
            content = f.read()

        # #define MyAppVersion "x.x.x" 패턴 찾아서 업데이트
        version_string = f"{version_info['major']}.{version_info['minor']}.{version_info['patch']}"
        content = re.sub(
            r'(#define MyAppVersion\s+")[^"]+(")',
            rf'\g<1>{version_string}\g<2>',
            content
        )

        with open(INSTALLER_SCRIPT, 'w', encoding='utf-8') as f:
            f.write(content)

        return True
    except Exception as e:
        print(f"[경고] installer.iss 버전 업데이트 실패: {e}")
        return False


def create_installer(version_info):
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

    # installer.iss 버전 정보 업데이트
    update_installer_script_version(version_info)

    cmd = [str(INNO_SETUP_PATH), str(INSTALLER_SCRIPT)]
    print(f"인스톨러 명령: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, check=True, cwd=PROJECT_ROOT,
                                 capture_output=True, text=True)
        print(result.stdout)
        print("\n[OK] 인스톨러 생성 성공!")

        # 생성된 인스톨러 파일명 변경 (타임스탬프 추가)
        # installer.iss의 OutputBaseFilename=HomeworkHelper_Setup_vX.Y.Z
        base_version = f"{version_info['major']}.{version_info['minor']}.{version_info['patch']}"
        expected_filename = f"HomeworkHelper_Setup_v{base_version}.exe"
        generated_file = RELEASE_DIR / expected_filename
        
        if generated_file.exists():
            # 새 파일명: HomeworkHelper_vX.Y.Z.timestamp_Setup.exe
            new_name = f"HomeworkHelper_{version_info['string']}_Setup.exe"
            dest = RELEASE_DIR / new_name

            # 이름 변경
            shutil.move(str(generated_file), str(dest))
            
            size_mb = dest.stat().st_size / (1024 * 1024)
            print(f"  인스톨러: {new_name} ({size_mb:.2f} MB)")
            print(f"  저장 위치: {dest}")
        else:
            print(f"[경고] 생성된 인스톨러 파일을 찾을 수 없습니다: {expected_filename}")

        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[오류] 인스톨러 생성 실패: {e}")
        if e.stderr:
            print(f"오류 메시지:\n{e.stderr}")
        return False


def print_summary(version_info):
    """빌드 결과 요약"""
    print_section("빌드 완료 - 결과 요약")

    print(f"\n빌드 버전: {version_info['string']}")
    print("\n배포 파일 목록 (release 폴더):")
    print("-" * 70)

    if not RELEASE_DIR.exists():
        print("  (release 폴더 없음)")
        return

    has_files = False

    # 1. 인스톨러
    for setup_file in RELEASE_DIR.glob(f"*{version_info['string']}*Setup*.exe"):
        size_mb = setup_file.stat().st_size / (1024 * 1024)
        print(f"  [인스톨러] {setup_file.name} ({size_mb:.2f} MB)")
        has_files = True

    # 2. ZIP
    for zip_file in RELEASE_DIR.glob(f"*{version_info['string']}*Portable*.zip"):
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
    print_section("HomeworkHelper 빌드 스크립트 (onedir + Installer)")
    print(f"프로젝트 경로: {PROJECT_ROOT}")
    print(f"빌드 모드: onedir (폴더 배포)")

    # 0. .spec 파일 존재 확인
    if not SPEC_FILE.exists():
        print(f"\n[오류] {SPEC_FILE.name} 파일을 찾을 수 없습니다.")
        return 1

    # 1. 최신 버전 확인
    latest_version = get_latest_version()

    # 2. 대화형 버전 입력
    version_info = interactive_version_input(latest_version)
    if version_info is None:
        return 1

    # 3. 이전 파일 아카이빙
    archive_old_files(version_info)

    # 4. 이전 빌드 산출물 정리
    clean_build_artifacts()

    # 5. PyInstaller 빌드 (onedir 모드)
    if not build_with_pyinstaller():
        print("\n[실패] 빌드 과정에서 오류가 발생했습니다.")
        return 1

    # 6. 배포 파일 생성
    success_count = 0

    # 6-1. ZIP 생성
    if create_zip_distribution(version_info):
        success_count += 1

    # 6-2. 인스톨러 생성 (Inno Setup 있는 경우)
    if create_installer(version_info):
        success_count += 1

    # 7. 결과 요약
    print_summary(version_info)

    if success_count == 0:
        print("\n[경고] 배포 파일이 생성되지 않았습니다.")
        return 1

    # 8. release 폴더를 Windows Explorer로 열기
    try:
        subprocess.Popen(['explorer', str(RELEASE_DIR.absolute())])
        print(f"[OK] release 폴더를 열었습니다: {RELEASE_DIR.absolute()}")
    except Exception as e:
        print(f"[경고] release 폴더 열기 실패: {e}")

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
