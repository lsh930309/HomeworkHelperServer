"""Method C: WinRT RawGameController 폴링 기반 스크린샷 트리거.

Xbox 라이센스 취득 패드(예: Gamesir G7 Pro)처럼 WH_KEYBOARD_LL 훅이나
XInput Guide 버튼으로 Share 버튼이 감지되지 않는 경우,
Windows.Gaming.Input.RawGameController API를 폴링해 버튼 프레스를 감지합니다.

_method.txt 형식: "C:<button_index>"  예) "C:3"
button_index = -1 이면 어떤 버튼이든 첫 프레스를 트리거로 사용합니다.
"""
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 0.05   # 50 ms
MAX_BUTTONS = 64


def _get_controllers():
    """연결된 RawGameController 목록 반환. winrt 미설치 시 빈 리스트."""
    try:
        from winrt.windows.gaming.input import RawGameController
        return list(RawGameController.raw_game_controllers)
    except Exception as exc:
        logger.debug("RawGameController 열거 실패: %s", exc)
        return []


class MethodC:
    """WinRT RawGameController 폴링 기반 스크린샷 트리거."""

    def __init__(self, button_index: int = -1, dispatcher=None):
        """
        Args:
            button_index: 감지할 버튼 인덱스 (0-based).
                          -1 이면 임의 버튼 첫 프레스를 트리거로 사용합니다.
            dispatcher: TriggerDispatcher 인스턴스 (있으면 홀드 분기 사용).
        """
        self._button_index = button_index
        self._callback: Optional[Callable] = None
        self._dispatcher = dispatcher
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._prev_states: dict = {}   # {controller_id: [bool, ...]}

    # ── 공개 API ────────────────────────────────────────────────

    def set_callback(self, fn: Callable) -> None:
        self._callback = fn

    def start(self) -> None:
        if self._running:
            return
        controllers = _get_controllers()
        if not controllers:
            logger.error("MethodC: RawGameController 감지 없음 — 시작 불가")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="screenshot-winrt-c",
        )
        self._thread.start()
        logger.info(
            "MethodC: 폴링 시작 (button_index=%s, %.0f ms 간격)",
            self._button_index if self._button_index >= 0 else "any",
            POLL_INTERVAL_SEC * 1000,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._prev_states.clear()
        logger.info("MethodC: 폴링 종료")

    # ── 내부 구현 ────────────────────────────────────────────────

    def _read_buttons(self, controller) -> Optional[list]:
        """컨트롤러의 현재 버튼 상태 리스트 반환. 실패 시 None."""
        try:
            n = controller.button_count
            if n == 0 or n > MAX_BUTTONS:
                return None
            buttons = [False] * n
            axes    = [0.0]   * controller.axis_count
            switches = [0]    * controller.switch_count
            _ts, buttons, _ax, _sw = controller.get_current_reading(
                buttons, axes, switches
            )
            return list(buttons)
        except Exception as exc:
            logger.debug("버튼 읽기 실패: %s", exc)
            return None

    def _poll_loop(self) -> None:
        while self._running:
            try:
                controllers = _get_controllers()
                for ctrl in controllers:
                    cid = id(ctrl)
                    curr = self._read_buttons(ctrl)
                    if curr is None:
                        continue
                    prev = self._prev_states.get(cid, [False] * len(curr))
                    # 길이 불일치 보정
                    if len(prev) != len(curr):
                        prev = [False] * len(curr)

                    if self._dispatcher:
                        # dispatcher 모드: rising/falling edge + hold tick
                        idx = self._button_index
                        if idx >= 0 and idx < len(curr):
                            # rising edge (버튼 눌림)
                            if curr[idx] and not prev[idx]:
                                logger.debug("MethodC: 버튼[%d] 프레스 감지", idx)
                                self._dispatcher.on_press()
                            # hold tick (버튼 홀드 중)
                            elif curr[idx] and prev[idx]:
                                self._dispatcher.on_hold_tick()
                            # falling edge (버튼 뗌)
                            elif not curr[idx] and prev[idx]:
                                logger.debug("MethodC: 버튼[%d] 릴리즈 감지", idx)
                                self._dispatcher.on_release()
                        elif idx < 0:
                            # auto 모드: 첫 번째 변화 버튼 사용
                            for i, (c, p) in enumerate(zip(curr, prev)):
                                if c and not p:
                                    logger.debug("MethodC: 버튼[%d] 프레스 (auto 모드)", i)
                                    self._dispatcher.on_press()
                                    break
                                elif not c and p:
                                    self._dispatcher.on_release()
                                    break
                            # hold tick: 임의 버튼이 눌려있으면
                            if any(c and p for c, p in zip(curr, prev)):
                                self._dispatcher.on_hold_tick()
                    else:
                        # legacy 모드: 직접 callback 호출
                        triggered = False
                        if self._button_index >= 0:
                            idx = self._button_index
                            if idx < len(curr) and curr[idx] and not prev[idx]:
                                triggered = True
                                logger.debug("MethodC: 버튼[%d] 프레스 감지", idx)
                        else:
                            for i, (c, p) in enumerate(zip(curr, prev)):
                                if c and not p:
                                    triggered = True
                                    logger.debug("MethodC: 버튼[%d] 프레스 (auto 모드)", i)
                                    break

                        if triggered and self._callback:
                            threading.Thread(
                                target=self._callback,
                                daemon=True,
                                name="screenshot-capture",
                            ).start()

                    self._prev_states[cid] = curr
            except Exception as exc:
                logger.debug("MethodC 폴링 예외: %s", exc)

            time.sleep(POLL_INTERVAL_SEC)


def discover_button_index(timeout_sec: float = 10.0) -> Optional[int]:
    """
    모든 RawGameController를 폴링하며 새로 눌린 버튼 인덱스를 반환합니다.
    진단 도구에서 호출합니다.

    Returns:
        감지된 버튼 인덱스. 타임아웃 시 None.
    """
    controllers = _get_controllers()
    if not controllers:
        logger.error("discover_button_index: 컨트롤러 없음")
        return None

    # 초기 상태 스냅샷
    prev_states: dict = {}
    for ctrl in controllers:
        cid = id(ctrl)
        n = getattr(ctrl, 'button_count', 0)
        if n == 0:
            continue
        buttons = [False] * n
        axes    = [0.0]   * getattr(ctrl, 'axis_count', 0)
        switches = [0]    * getattr(ctrl, 'switch_count', 0)
        try:
            _ts, buttons, _ax, _sw = ctrl.get_current_reading(buttons, axes, switches)
            prev_states[cid] = list(buttons)
        except Exception:
            prev_states[cid] = [False] * n

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            for ctrl in _get_controllers():
                cid = id(ctrl)
                n = getattr(ctrl, 'button_count', 0)
                if n == 0:
                    continue
                buttons = [False] * n
                axes    = [0.0]   * getattr(ctrl, 'axis_count', 0)
                switches = [0]    * getattr(ctrl, 'switch_count', 0)
                try:
                    _ts, buttons, _ax, _sw = ctrl.get_current_reading(buttons, axes, switches)
                except Exception:
                    continue
                curr = list(buttons)
                prev = prev_states.get(cid, [False] * len(curr))
                if len(prev) != len(curr):
                    prev = [False] * len(curr)
                for i, (c, p) in enumerate(zip(curr, prev)):
                    if c and not p:
                        return i
                prev_states[cid] = curr
        except Exception:
            pass
        time.sleep(0.05)
    return None
