"""Method A: WH_KEYBOARD_LL 훅으로 VK_MEDIA_STOP 가로채기.

게임패드 버튼을 Gamesir Connect에서 [미디어 정지] 키(VK=0xB2)로 매핑하면,
이 훅이 해당 이벤트를 가로채고 억제합니다.

미디어 키는 게임의 입력 장치 감지(게임패드↔키/마 UI 전환)를 유발하지 않으므로
WH_KEYBOARD_LL 억제만으로 게임 프로세스에 어떠한 키보드 신호도 전달되지 않습니다.

동작 방식:
  - 별도 데몬 스레드에서 SetWindowsHookExW(WH_KEYBOARD_LL)를 설치
  - 해당 스레드에서 PeekMessageW 루프로 훅 콜백을 처리
  - VK_MEDIA_STOP 감지 시 콜백에서 1을 반환해 이벤트를 삭제
  - 캡처는 또 다른 데몬 스레드에서 비동기 실행
"""
import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
import time
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.screenshot.trigger_dispatcher import TriggerDispatcher

logger = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
WM_SYSKEYDOWN  = 0x0104
WM_SYSKEYUP    = 0x0105
WM_QUIT        = 0x0012
VK_MEDIA_STOP  = 0xB2     # 미디어 정지 키 (게임 UI 전환 미유발)
PM_REMOVE      = 0x0001

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MethodA:
    """WH_KEYBOARD_LL 훅 기반 스크린샷 트리거."""

    def __init__(self, dispatcher=None):
        self._callback: Optional[Callable] = None
        self._dispatcher = dispatcher
        self._thread: Optional[threading.Thread] = None
        self._thread_id: int = 0
        self._running: bool = False

    # ── 공개 API ────────────────────────────────────────────────

    def set_callback(self, fn: Callable) -> None:
        """VK_MEDIA_STOP 감지 시 호출될 함수를 등록합니다."""
        self._callback = fn

    def start(self) -> None:
        """훅 스레드를 시작합니다."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._hook_thread,
            daemon=True,
            name="screenshot-hook-a",
        )
        self._thread.start()
        # thread_id 가 채워질 때까지 최대 1초 대기
        for _ in range(40):
            if self._thread_id:
                break
            time.sleep(0.025)

    def stop(self) -> None:
        """훅을 해제하고 스레드를 종료합니다."""
        self._running = False
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=3)
        self._thread_id = 0

    # ── 내부 구현 ────────────────────────────────────────────────

    def _hook_thread(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._key_held = False  # VK_MEDIA_STOP 홀드 상태 추적

        # proc 은 GC 방지를 위해 로컬 변수로 유지 (함수 스코프 내 살아있음)
        def _handler(nCode: int, wParam: int, lParam: int) -> int:
            if nCode >= 0:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == VK_MEDIA_STOP:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        if not self._key_held:
                            self._key_held = True
                            logger.debug("MethodA: VK_MEDIA_STOP 키 다운 감지")
                            if self._dispatcher:
                                self._dispatcher.on_press()
                            elif self._callback:
                                threading.Thread(
                                    target=self._callback,
                                    daemon=True,
                                    name="screenshot-capture",
                                ).start()
                        return 1  # 이벤트 삭제 (게임/OS 미전달)
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        if self._key_held:
                            self._key_held = False
                            logger.debug("MethodA: VK_MEDIA_STOP 키 업 감지")
                            if self._dispatcher:
                                self._dispatcher.on_release()
                        return 1  # 이벤트 삭제
            return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

        ctypes.windll.user32.CallNextHookEx.restype = ctypes.c_longlong
        ctypes.windll.user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
        ]
        proc = HOOKPROC(_handler)
        hook = ctypes.windll.user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)

        if not hook:
            err = ctypes.windll.kernel32.GetLastError()
            logger.error("WH_KEYBOARD_LL 훅 설치 실패 (GetLastError=%d)", err)
            self._running = False
            return

        logger.info("MethodA: 훅 설치 완료 (thread_id=%d)", self._thread_id)

        msg = wintypes.MSG()
        while self._running:
            ret = ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
            if ret:
                if msg.message == WM_QUIT:
                    break
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            else:
                # dispatcher tick (홀드 감지)
                if self._dispatcher and self._key_held:
                    self._dispatcher.on_hold_tick()
                time.sleep(0.005)  # 5 ms 슬립 (CPU 부하 최소화)

        ctypes.windll.user32.UnhookWindowsHookEx(hook)
        logger.info("MethodA: 훅 해제 완료")
