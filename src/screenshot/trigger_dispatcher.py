import time
import threading
from typing import Callable, Optional


class TriggerDispatcher:
    """버튼 홀드 시간에 따라 스크린샷(짧게)과 녹화토글(길게)을 분기한다."""

    SHORT_MAX_MS: int = 500   # 이 미만 release → 스크린샷
    LONG_MIN_MS: int = 800    # 이 이상 홀드 → 녹화 토글 즉시 발화

    def __init__(
        self,
        on_screenshot: Callable[[], None],
        on_long_press: Callable[[], None],
    ) -> None:
        self._on_screenshot = on_screenshot
        self._on_long_press = on_long_press
        self._press_time: Optional[float] = None
        self._recording_fired: bool = False
        self._lock = threading.Lock()

    # --- public interface (called from MethodA) ---

    def on_press(self) -> None:
        with self._lock:
            self._press_time = time.monotonic()
            self._recording_fired = False

    def on_hold_tick(self) -> None:
        """폴링 루프 tick마다 호출. LONG_MIN_MS 도달 시 on_long_press 즉시 발화."""
        fire = False
        with self._lock:
            if self._press_time is not None and not self._recording_fired:
                elapsed_ms = (time.monotonic() - self._press_time) * 1000
                if elapsed_ms >= self.LONG_MIN_MS:
                    self._recording_fired = True
                    fire = True
        if fire:
            self._on_long_press()

    def on_release(self) -> None:
        with self._lock:
            if self._press_time is None:
                return
            elapsed_ms = (time.monotonic() - self._press_time) * 1000
            fired = self._recording_fired
            self._press_time = None
        if not fired and elapsed_ms < self.SHORT_MAX_MS:
            self._on_screenshot()
