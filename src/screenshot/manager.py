"""스크린샷 기능 통합 매니저.

_ACTIVE_METHOD 값은 tools/select_screenshot_method.py 가 자동으로 수정합니다.
직접 변경하거나 _method.txt 를 통해 런타임에도 오버라이드할 수 있습니다.
"""
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# select_screenshot_method.py 가 이 줄을 수정합니다 — 직접 편집 가능
_ACTIVE_METHOD = "A"

_METHOD_FILE = Path(__file__).parent / "_method.txt"


def _resolve_method() -> str:
    """_method.txt 가 있으면 우선 적용, 없으면 _ACTIVE_METHOD 사용."""
    if _METHOD_FILE.exists():
        val = _METHOD_FILE.read_text(encoding="utf-8").strip().upper()
        if val in ("A", "B"):
            return val
    return _ACTIVE_METHOD


class ScreenshotManager:
    """게임패드 스크린샷 기능의 통합 진입점.

    사용 예:
        mgr = ScreenshotManager(save_dir="D:/Screenshots")
        mgr.set_on_captured(lambda path: print("저장:", path))
        mgr.start()
        # ... 앱 종료 시
        mgr.stop()
    """

    def __init__(self, save_dir: Optional[str] = None):
        self._save_dir   = save_dir
        self._method_id  = _resolve_method()
        self._impl       = None
        self._on_captured: Optional[Callable[[str], None]] = None

    # ── 공개 API ────────────────────────────────────────────────

    def set_on_captured(self, fn: Callable[[str], None]) -> None:
        """캡처 완료 시 호출될 콜백. 인자로 저장 파일 경로(str)를 전달합니다."""
        self._on_captured = fn

    def start(self) -> None:
        """트리거 감지를 시작합니다."""
        self._impl = self._create_impl()
        self._impl.set_callback(self._on_trigger)
        self._impl.start()
        logger.info("ScreenshotManager 시작 (Method %s, save_dir=%s)",
                    self._method_id, self._save_dir)

    def stop(self) -> None:
        """트리거 감지를 정지합니다."""
        if self._impl:
            self._impl.stop()
            self._impl = None
        logger.info("ScreenshotManager 정지")

    def capture_now(self) -> Optional[str]:
        """즉시 스크린샷을 촬영합니다. 저장 경로를 반환하며 실패 시 None."""
        from src.screenshot.capture import take_screenshot
        return take_screenshot(save_dir=self._save_dir)

    @property
    def method_id(self) -> str:
        """현재 활성화된 방법 ID ('A' 또는 'B')."""
        return self._method_id

    # ── 내부 구현 ────────────────────────────────────────────────

    def _on_trigger(self) -> None:
        path = self.capture_now()
        if path and self._on_captured:
            self._on_captured(path)

    def _create_impl(self):
        if self._method_id == "B":
            from src.screenshot.method_b import MethodB
            return MethodB()
        from src.screenshot.method_a import MethodA
        return MethodA()
