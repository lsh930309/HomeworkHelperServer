"""스크린샷 기능 통합 매니저.

_method.txt 형식:
  "A"       — Method A (WH_KEYBOARD_LL, Win+Alt+PrtScn 가로채기)
  "C:<idx>" — Method C (WinRT RawGameController, 버튼 인덱스 idx)
"""
import logging
from pathlib import Path
from typing import Callable, Optional

from src.screenshot.trigger_dispatcher import TriggerDispatcher

logger = logging.getLogger(__name__)

_ACTIVE_METHOD = "A"
_METHOD_FILE = Path(__file__).parent / "_method.txt"


def _resolve_method() -> tuple:
    """(method_id: str, button_index: int) 반환."""
    if _METHOD_FILE.exists():
        val = _METHOD_FILE.read_text(encoding="utf-8").strip().upper()
        if ":" in val:
            parts = val.split(":", 1)
            method = parts[0].strip()
            try:
                idx = int(parts[1].strip())
            except ValueError:
                idx = -1
            if method in ("A", "C"):
                return method, idx
        elif val in ("A", "C"):
            return val, -1
    return _ACTIVE_METHOD, -1


class ScreenshotManager:
    """게임패드 스크린샷 기능의 통합 진입점.

    사용 예:
        mgr = ScreenshotManager(save_dir="D:/Screenshots")
        mgr.set_on_captured(lambda path: print("저장:", path))
        mgr.start()
        # ... 앱 종료 시
        mgr.stop()
    """

    def __init__(
        self,
        save_dir: Optional[str] = None,
        get_target_hwnd: Optional[Callable[[], Optional[int]]] = None,
    ):
        """
        Args:
            save_dir: 스크린샷 저장 디렉터리.
            get_target_hwnd: 게임 창 모드 캡처 시 대상 HWND 반환 콜백.
        """
        self._save_dir = save_dir
        self._get_target_hwnd = get_target_hwnd
        self._method_id, self._button_index = _resolve_method()
        self._impl = None
        self._on_captured: Optional[Callable[[str], None]] = None
        self._capture_mode: str = "fullscreen"  # "fullscreen" | "game_window"
        self._long_press_callback: Optional[Callable[[], None]] = None
        self._dispatcher = TriggerDispatcher(
            on_screenshot=self._on_trigger,
            on_long_press=self._on_long_press_trigger,
        )

    # ── 공개 API ────────────────────────────────────────────────

    def set_on_captured(self, fn: Callable[[str], None]) -> None:
        """캡처 완료 시 호출될 콜백. 인자로 저장 파일 경로(str)를 전달합니다."""
        self._on_captured = fn

    def set_on_long_press(self, fn: Callable[[], None]) -> None:
        """롱프레스(녹화 토글) 시 호출될 콜백을 등록합니다."""
        self._long_press_callback = fn

    def set_save_dir(self, save_dir: Optional[str]) -> None:
        self._save_dir = save_dir

    def set_capture_mode(self, mode: str) -> None:
        """캡처 모드 설정. 'fullscreen' | 'game_window'."""
        self._capture_mode = mode

    def start(self) -> None:
        """트리거 감지를 시작합니다."""
        self._impl = self._create_impl()
        if self._impl is None:
            return
        # dispatcher가 있으면 callback은 dispatcher 경유로 호출됨
        # legacy fallback용으로도 callback 설정 유지
        self._impl.set_callback(self._on_trigger)
        self._impl.start()
        logger.info(
            "ScreenshotManager 시작 (Method %s, button=%s, save_dir=%s)",
            self._method_id,
            self._button_index if self._method_id == "C" else "n/a",
            self._save_dir,
        )

    def stop(self) -> None:
        """트리거 감지를 정지합니다."""
        if self._impl:
            self._impl.stop()
            self._impl = None
        logger.info("ScreenshotManager 정지")

    def capture_now(self) -> Optional[str]:
        """즉시 스크린샷을 촬영합니다. 저장 경로를 반환하며 실패 시 None."""
        from src.screenshot.capture import take_screenshot, take_screenshot_window
        if self._capture_mode == "game_window" and self._get_target_hwnd:
            hwnd = self._get_target_hwnd()
            if hwnd:
                result = take_screenshot_window(hwnd, save_dir=self._save_dir)
                if result:
                    return result
        return take_screenshot(save_dir=self._save_dir)

    @property
    def method_id(self) -> str:
        return self._method_id

    @property
    def button_index(self) -> int:
        return self._button_index

    # ── 내부 구현 ────────────────────────────────────────────────

    def _on_trigger(self) -> None:
        path = self.capture_now()
        if path and self._on_captured:
            self._on_captured(path)

    def _on_long_press_trigger(self) -> None:
        if self._long_press_callback:
            self._long_press_callback()

    def _create_impl(self):
        if self._method_id == "C":
            try:
                from src.screenshot.method_c import MethodC
                return MethodC(button_index=self._button_index, dispatcher=self._dispatcher)
            except Exception as exc:
                logger.error("MethodC 초기화 실패: %s", exc)
                return None
        # Default: Method A
        try:
            from src.screenshot.method_a import MethodA
            return MethodA(dispatcher=self._dispatcher)
        except Exception as exc:
            logger.error("MethodA 초기화 실패: %s", exc)
            return None
