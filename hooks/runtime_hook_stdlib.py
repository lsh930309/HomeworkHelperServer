"""
Runtime Hook: Python 표준 라이브러리 경로 추가
PyInstaller로 패키징된 환경에서 PyTorch가 표준 라이브러리를 찾을 수 있도록 합니다.
"""
import sys
import os
from pathlib import Path

# PyInstaller 패키징 환경에서만 실행
if getattr(sys, 'frozen', False):
    # 실행 파일 위치
    base_path = Path(sys.executable).parent

    # _internal/Lib 경로 추가 (Python 표준 라이브러리)
    lib_path = base_path / "_internal" / "Lib"

    if lib_path.exists():
        lib_path_str = str(lib_path)
        if lib_path_str not in sys.path:
            sys.path.insert(0, lib_path_str)
            print(f"[Runtime Hook] Python 표준 라이브러리 경로 추가: {lib_path_str}")
