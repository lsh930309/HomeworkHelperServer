"""Method B: XInput Guide 버튼 폴링 기반 스크린샷 트리거.

게임패드 [공유] 버튼이 XInput Guide 버튼(0x0400)으로 매핑된 경우(Method B),
비공개 API XInputGetStateEx(ordinal 100)를 폴링해 버튼 프레스를 감지합니다.

폴링 방식이므로 키보드 이벤트가 전혀 발생하지 않고,
마우스/키보드 UI 모드 전환도 일어나지 않습니다.

주의:
  - XInputGetStateEx 는 공개 API 가 아닙니다 (Windows 업데이트로 제거될 수 있음).
  - 표준 XInputGetState 로드를 fallback 으로 시도하지만,
    이 경우 Guide 버튼(0x0400)이 wButtons 에 포함되지 않아 감지가 불가합니다.
"""
import ctypes
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

XINPUT_GAMEPAD_GUIDE       = 0x0400
POLL_INTERVAL_SEC          = 0.05    # 50 ms
MAX_CONTROLLERS            = 4
ERROR_DEVICE_NOT_CONNECTED = 1167


class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons",      ctypes.c_ushort),
        ("bLeftTrigger",  ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX",      ctypes.c_short),
        ("sThumbLY",      ctypes.c_short),
        ("sThumbRX",      ctypes.c_short),
        ("sThumbRY",      ctypes.c_short),
    ]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad",        _XINPUT_GAMEPAD),
    ]


class MethodB:
    """XInput Guide 버튼 폴링 기반 스크린샷 트리거."""

    def __init__(self):
        self._callback: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._prev_guide = [False] * MAX_CONTROLLERS
        self._get_state: Optional[object] = self._init_xinput()

    # ── 공개 API ────────────────────────────────────────────────

    def set_callback(self, fn: Callable) -> None:
        """Guide 버튼 감지 시 호출될 함수를 등록합니다."""
        self._callback = fn

    def start(self) -> None:
        """XInput 폴링 스레드를 시작합니다."""
        if self._get_state is None:
            logger.error("MethodB: XInput 초기화 실패 — 시작 불가")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="screenshot-xinput-b",
        )
        self._thread.start()

    def stop(self) -> None:
        """폴링 스레드를 종료합니다."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    # ── 내부 구현 ────────────────────────────────────────────────

    def _init_xinput(self) -> Optional[object]:
        """XInputGetStateEx (ordinal 100) 로드. 실패 시 None."""
        dll = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                dll = ctypes.windll.LoadLibrary(name)
                break
            except OSError:
                continue
        if dll is None:
            logger.error("MethodB: XInput DLL 로드 실패")
            return None

        try:
            fn = dll[100]   # XInputGetStateEx — Guide 버튼 포함
            fn.restype  = ctypes.c_ulong
            fn.argtypes = [ctypes.c_ulong, ctypes.POINTER(_XINPUT_STATE)]
            logger.info("MethodB: XInputGetStateEx(ordinal 100) 로드 성공")
            return fn
        except Exception:
            logger.warning(
                "MethodB: ordinal 100 로드 실패 → 표준 XInputGetState 시도 "
                "(Guide 버튼 감지 불가 가능)"
            )
            try:
                fn = dll.XInputGetState
                fn.restype  = ctypes.c_ulong
                fn.argtypes = [ctypes.c_ulong, ctypes.POINTER(_XINPUT_STATE)]
                return fn
            except Exception:
                logger.error("MethodB: XInputGetState 로드도 실패")
                return None

    def _poll_loop(self) -> None:
        logger.info("MethodB: XInput 폴링 시작 (%.0f ms 간격)", POLL_INTERVAL_SEC * 1000)
        while self._running:
            for i in range(MAX_CONTROLLERS):
                state = _XINPUT_STATE()
                ret = self._get_state(i, ctypes.byref(state))
                if ret == 0:
                    guide_now = bool(state.Gamepad.wButtons & XINPUT_GAMEPAD_GUIDE)
                    if guide_now and not self._prev_guide[i]:
                        # 엣지 감지 — 누르는 순간 한 번만 발동
                        logger.debug("MethodB: Guide 버튼 프레스 (슬롯 %d)", i)
                        if self._callback:
                            threading.Thread(
                                target=self._callback,
                                daemon=True,
                                name="screenshot-capture",
                            ).start()
                    self._prev_guide[i] = guide_now
                elif ret == ERROR_DEVICE_NOT_CONNECTED:
                    self._prev_guide[i] = False
            time.sleep(POLL_INTERVAL_SEC)
        logger.info("MethodB: XInput 폴링 종료")
