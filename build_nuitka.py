#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Nuitka 빌드 스크립트 (PyInstaller 대체 테스트용)
================================================

PyInstaller spec 설정을 1:1로 Nuitka 옵션으로 매핑한 빌드 스크립트.
주요 목적: AV 오탐 감소 + 네이티브 바이너리 실행 속도 향상 검증

출력 위치: dist_nuitka/homework_helper.dist/
  └─ homework_helper.exe
  └─ assets/
  └─ src/api/dashboard/static/
  └─ src/api/dashboard/templates/
  └─ src/data/game_presets.json
  └─ [Nuitka 컴파일된 .pyd / .dll 의존성들]

사전 요구사항:
  pip install nuitka
  (MSVC 또는 MinGW C 컴파일러 필요 — Visual Studio Build Tools 권장)

실행:
  python build_nuitka.py

Nuitka vs PyInstaller 주요 차이:
  - _MEIxxxxxx 임시 폴더 없음 → AV 드로퍼 패턴 미해당
  - Python 코드를 C로 트랜스파일 후 컴파일 → 네이티브 바이너리
  - UPX 압축 불필요 (이미 컴파일된 바이너리)
  - sys._MEIPASS 없음 → get_bundle_resource_path()는 sys.executable 경로로 fallback (호환)
  - multiprocessing: Nuitka가 freeze 환경을 자동 처리 (freeze_support() 그대로 유지)
"""

import sys
import subprocess
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
OUTPUT_BASE  = PROJECT_ROOT / "dist_nuitka"
# Nuitka standalone 출력: dist_nuitka/homework_helper.dist/
OUTPUT_DIST  = OUTPUT_BASE / "homework_helper.dist"


def check_nuitka() -> bool:
    """Nuitka 설치 여부 확인."""
    result = subprocess.run(
        [sys.executable, "-m", "nuitka", "--version"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[OK] Nuitka 확인: {result.stdout.strip()}")
        return True
    print("[ERROR] Nuitka가 설치되어 있지 않습니다.")
    print("        pip install nuitka  으로 설치 후 재실행하세요.")
    return False


def clean_previous_build():
    """이전 빌드 결과물 정리."""
    if OUTPUT_DIST.exists():
        print(f"[정리] 이전 빌드 결과물 삭제 중: {OUTPUT_DIST}")
        shutil.rmtree(OUTPUT_DIST)
    # Nuitka 중간 빌드 캐시 (homework_helper.build)
    build_cache = PROJECT_ROOT / "homework_helper.build"
    if build_cache.exists():
        print(f"[정리] 빌드 캐시 삭제 중: {build_cache}")
        shutil.rmtree(build_cache)


def build():
    if not check_nuitka():
        sys.exit(1)

    clean_previous_build()

    OUTPUT_BASE.mkdir(exist_ok=True)

    # ================================================================
    # Nuitka 빌드 명령어
    # PyInstaller spec → Nuitka 옵션 1:1 매핑
    # ================================================================
    cmd = [
        sys.executable, "-m", "nuitka",

        # ── 출력 모드 ─────────────────────────────────────────────
        "--standalone",           # onedir 모드: exe + 의존성을 한 폴더에 출력
        f"--output-dir={OUTPUT_BASE}",

        # ── Windows 전용 옵션 ──────────────────────────────────────
        "--disable-console",      # 콘솔 창 숨김 (spec: console=False)
        "--windows-icon-from-ico=assets/icons/app/app_icon.ico",

        # ── 플러그인: 동적 의존성 자동 처리 ───────────────────────
        "--enable-plugin=pyqt6",  # PyQt6 DLL 자동 포함 + 경로 처리
        "--enable-plugin=pydantic",  # Pydantic v2 모델 동적 생성 처리

        # ── 데이터 파일 (Python이 아닌 리소스만) ──────────────────
        # Python 소스는 Nuitka가 import 추적으로 자동 컴파일.
        # HTML / CSS / JS / JSON / 폰트 / 아이콘만 명시적으로 포함.
        "--include-data-dir=assets=assets",
        "--include-data-dir=src/api/dashboard/static=src/api/dashboard/static",
        "--include-data-dir=src/api/dashboard/templates=src/api/dashboard/templates",
        "--include-data-files=src/data/game_presets.json=src/data/game_presets.json",

        # ── 동적 로딩 패키지 명시 포함 ────────────────────────────
        # Nuitka 정적 분석으로 찾지 못하는 런타임 import를 명시.
        # (spec의 hiddenimports에 대응)
        "--include-package=uvicorn",      # 내부 라우터/미들웨어 동적 로딩
        "--include-package=fastapi",      # 의존성 주입 / 라우팅
        "--include-package=starlette",    # fastapi 하위 의존성
        "--include-package=sqlalchemy",   # 방언(dialect) 동적 로딩
        "--include-package=pydantic",     # 모델 동적 생성
        "--include-package=requests",     # HoYoLab API / 서버 헬스체크
        "--include-package=win32com",     # win32com.client (COM 자동화)
        "--include-package=genshin",      # HoYoLab Python SDK
        "--include-package=jsonschema",   # 스키마 검증

        # pywin32: 패키지가 아닌 단일 .pyd 모듈로 배포됨
        "--include-module=win32api",
        "--include-module=win32security",
        "--include-module=win32process",
        "--include-module=win32con",
        "--include-module=win32event",
        "--include-module=winerror",
        "--include-module=winshell",
        "--include-module=psutil",

        # ── 불필요한 무거운 라이브러리 제외 ──────────────────────
        # (spec의 excludes에 대응 — LSH 쪽으로 분리된 항목들)
        "--nofollow-import-to=torch",
        "--nofollow-import-to=torchvision",
        "--nofollow-import-to=torchaudio",
        "--nofollow-import-to=cv2",
        "--nofollow-import-to=av",
        "--nofollow-import-to=skimage",
        "--nofollow-import-to=scipy",
        "--nofollow-import-to=PIL",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=numpy",
        "--nofollow-import-to=imageio",

        # ── 빌드 편의 옵션 ────────────────────────────────────────
        "--assume-yes-for-downloads",  # 빌드 중 추가 다운로드 자동 수락

        # ── 진입점 ────────────────────────────────────────────────
        "homework_helper.pyw",
    ]

    print("\n" + "=" * 60)
    print("Nuitka 빌드 시작")
    print("=" * 60)
    print(f"진입점: homework_helper.pyw")
    print(f"출력:   {OUTPUT_DIST}")
    print("=" * 60 + "\n")

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    print("\n" + "=" * 60)
    if result.returncode == 0:
        print("빌드 성공!")
        print(f"결과물 위치: {OUTPUT_DIST}")
        _print_post_build_notes()
    else:
        print(f"빌드 실패 (returncode={result.returncode})")
        _print_troubleshooting()
    print("=" * 60)

    sys.exit(result.returncode)


def _print_post_build_notes():
    """빌드 성공 후 체크리스트 출력."""
    print("""
── 빌드 후 확인 체크리스트 ──────────────────────────────

1. 기본 실행 확인
   dist_nuitka/homework_helper.dist/homework_helper.exe 실행

2. API 서버 기동 확인
   앱 실행 후 브라우저에서 http://127.0.0.1:8000/settings 접속

3. 대시보드 확인
   http://127.0.0.1:8000/dashboard 접속

4. multiprocessing 동작 확인 (핵심)
   - 앱 시작 시 서버 프로세스가 별도 PID로 뜨는지 확인
   - 작업 관리자에서 homework_helper.exe 두 개(GUI + 서버) 확인

5. 관리자 권한 전환 확인
   - 설정 → 관리자 권한으로 실행 토글
   - Task Scheduler 예약 작업(HomeworkHelper_Admin) 실행 여부 확인

6. 리소스 로딩 확인
   - 폰트 정상 적용 (NEXON Lv1 Gothic)
   - 게임 스태미나 아이콘 표시
   - 대시보드 CSS/JS 정상 로딩

── 알려진 Nuitka 전환 고려사항 ──────────────────────────

• sys._MEIPASS 없음
  get_bundle_resource_path()가 sys.executable 경로로 자동 fallback.
  별도 코드 수정 없이 동작함.

• cleanup_old_mei_folders()
  _MEI* 폴더가 없으므로 "정리할 폴더가 없습니다" 출력 후 정상 종료.
  무해하나, 추후 Nuitka 확정 시 조건부 처리 또는 제거 가능.

• multiprocessing
  Nuitka가 freeze 환경을 자동 패치. freeze_support() 유지 필요.
""")


def _print_troubleshooting():
    """빌드 실패 시 트러블슈팅 가이드 출력."""
    print("""
── 트러블슈팅 ───────────────────────────────────────────

• ModuleNotFoundError (런타임)
  → 해당 모듈을 --include-module 또는 --include-package 에 추가

• ImportError: DLL load failed (pywin32 관련)
  → pywin32 post-install 스크립트 실행:
     python Scripts/pywin32_postinstall.py -install

• Qt 플러그인 오류 (플랫폼 DLL 누락)
  → --enable-plugin=pyqt6 가 적용되었는지 확인
  → Nuitka 최신 버전으로 업데이트: pip install -U nuitka

• Pydantic ValidationError (컴파일 최적화 충돌)
  → --enable-plugin=pydantic 확인
  → pydantic v1이면 플러그인 제거 후 --include-package=pydantic 만 유지

• C 컴파일러 오류
  → Visual Studio Build Tools 설치 확인
  → 또는 MinGW: conda install m2w64-gcc
""")


if __name__ == "__main__":
    build()
