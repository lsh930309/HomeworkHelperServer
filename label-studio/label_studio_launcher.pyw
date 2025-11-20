#!/usr/bin/env python3
"""
Label Studio Manager Launcher
독립 실행 가능한 GUI 툴 진입점
"""

import sys
import os
from pathlib import Path

# label-studio/gui 디렉토리를 sys.path에 추가
gui_dir = Path(__file__).parent / "gui"
if str(gui_dir.parent) not in sys.path:
    sys.path.insert(0, str(gui_dir.parent))

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
