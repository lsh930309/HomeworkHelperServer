"""게임패드 스크린샷 기능 패키지.

사용 전 진단 도구를 먼저 실행하세요:
  python tools/diagnose_gamepad_screenshot.py
  python tools/select_screenshot_method.py
"""
from src.screenshot.manager import ScreenshotManager

__all__ = ["ScreenshotManager"]
