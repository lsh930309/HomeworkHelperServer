#!/usr/bin/env python3
"""
Label Studio Manager Launcher
독립 실행 가능한 GUI 툴 진입점
"""

# PyTorch를 가장 먼저 import (PyQt6 DLL 충돌 방지 - WinError 1114 해결)
try:
    import sys
    import os
    from pathlib import Path

    # PyTorch 경로를 sys.path 끝에 추가 (낮은 우선순위)
    # 이렇게 하면 typing_extensions 등은 시스템 경로에서 로드되고,
    # torch/torchvision만 PyTorch 경로에서 로드됨 (권한 충돌 방지)
    appdata = os.getenv('APPDATA') or os.path.expanduser('~')
    pytorch_dir = Path(appdata) / "HomeworkHelper" / "pytorch" / "Lib" / "site-packages"

    if pytorch_dir.exists():
        pytorch_str = str(pytorch_dir)
        # 기존에 추가된 경로가 있으면 제거 (중복 방지)
        if pytorch_str in sys.path:
            sys.path.remove(pytorch_str)
        # sys.path 끝에 추가 (낮은 우선순위)
        sys.path.append(pytorch_str)

    # PyTorch를 최우선으로 import (PyQt6보다 먼저 - DLL 충돌 방지)
    import torch
    print(f"✅ PyTorch {torch.__version__} 사전 로드 완료 (PyQt6 DLL 충돌 방지)")
except ImportError:
    # PyTorch 미설치 시 무시
    pass
except PermissionError as e:
    # Windows 권한 충돌 시 경로 제거 후 계속 진행
    print(f"⚠️ PyTorch 경로 권한 오류: {e}")
    print("   → PyTorch 경로를 sys.path에서 제거하고 계속 진행합니다.")
    try:
        pytorch_str = str(Path(os.getenv('APPDATA') or os.path.expanduser('~')) / "HomeworkHelper" / "pytorch" / "Lib" / "site-packages")
        if pytorch_str in sys.path:
            sys.path.remove(pytorch_str)
    except:
        pass
except Exception as e:
    print(f"⚠️ PyTorch 사전 로드 실패 (무시됨): {e}")

import sys
import os
from pathlib import Path

# label-studio/gui 디렉토리를 sys.path에 추가
gui_dir = Path(__file__).parent / "gui"
if str(gui_dir.parent) not in sys.path:
    sys.path.insert(0, str(gui_dir.parent))

# tools 디렉토리를 sys.path에 추가 (video_sampler, video_segmenter 사용)
if getattr(sys, 'frozen', False):
    # PyInstaller 패키징 환경
    tools_dir = Path(sys.executable).parent / "_internal" / "tools"
else:
    # 개발 환경
    tools_dir = Path(__file__).parent.parent / "tools"

if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from gui.label_studio_manager import LabelStudioManager


def main():
    """메인 함수"""
    # Qt 애플리케이션 생성
    app = QApplication(sys.argv)
    app.setApplicationName("Label Studio Manager")
    app.setOrganizationName("HomeworkHelper")

    # 메인 윈도우 생성 및 표시
    window = LabelStudioManager()
    window.show()

    # 이벤트 루프 시작
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
