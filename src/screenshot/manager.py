"""스크린샷 기능 통합 매니저 (Method A 고정).

Gamesir G7 Pro 등 HID 가상 키보드 드라이버 기반 게임패드는
공유 버튼 입력을 Win+Alt+PrtScn 키 이벤트로 주입합니다.
WH_KEYBOARD_LL 훅(Method A)이 이를 Game Bar보다 먼저 가로채 처리합니다.
"""
import logging
from typing import Callable, Optional

from src.screenshot.trigger_dispatcher import TriggerDispatcher

logger = logging.getLogger(__name__)


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
        self._get_game_name: Optional[Callable[[], str]] = None
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

    def set_game_name_provider(self, fn: Callable[[], str]) -> None:
        """현재 활성 게임 이름을 반환하는 콜백을 등록합니다 (파일명 생성에 사용)."""
        self._get_game_name = fn

    def set_save_dir(self, save_dir: Optional[str]) -> None:
        self._save_dir = save_dir

    def set_capture_mode(self, mode: str) -> None:
        """캡처 모드 설정. 'fullscreen' | 'game_window'."""
        self._capture_mode = mode

    def start(self) -> None:
        """트리거 감지를 시작합니다."""
        if self._impl is not None:
            return  # 이미 실행 중
        self._impl = self._create_impl()
        if self._impl is None:
            return
        self._impl.set_callback(self._on_trigger)
        self._impl.start()
        logger.info("ScreenshotManager 시작 (save_dir=%s)", self._save_dir)

    def stop(self) -> None:
        """트리거 감지를 정지합니다."""
        if self._impl:
            self._impl.stop()
            self._impl = None
        logger.info("ScreenshotManager 정지")

    def capture_now(self) -> Optional[str]:
        """즉시 스크린샷을 촬영합니다. 저장 경로를 반환하며 실패 시 None."""
        from src.screenshot.capture import take_screenshot, take_screenshot_window
        game_name = self._get_game_name() if self._get_game_name else ""
        if self._capture_mode == "game_window" and self._get_target_hwnd:
            hwnd = self._get_target_hwnd()
            if hwnd:
                result = take_screenshot_window(hwnd, save_dir=self._save_dir, game_name=game_name)
                if result:
                    return result
        return take_screenshot(save_dir=self._save_dir, game_name=game_name)

    # ── 내부 구현 ────────────────────────────────────────────────

    def _on_trigger(self) -> None:
        # WH_KEYBOARD_LL hook callback 안에서 호출될 수 있으므로
        # 블로킹 캡처는 반드시 별도 스레드에서 실행해야 함
        # (hook callback 내 블로킹 시 Windows가 ~200ms timeout 후 훅 무력화)
        import threading as _threading
        _threading.Thread(
            target=self._do_capture,
            daemon=True,
            name="screenshot-capture",
        ).start()

    def _do_capture(self) -> None:
        path = self.capture_now()
        if path and self._on_captured:
            self._on_captured(path)

    def _on_long_press_trigger(self) -> None:
        if self._long_press_callback:
            self._long_press_callback()

    def _create_impl(self):
        try:
            from src.screenshot.method_a import MethodA
            return MethodA(dispatcher=self._dispatcher)
        except Exception as exc:
            logger.error("MethodA 초기화 실패: %s", exc)
            return None
