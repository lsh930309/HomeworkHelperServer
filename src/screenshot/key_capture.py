"""단발성 키 캡처 유틸리티.

설정 UI에서 "버튼 설정..." 을 눌렀을 때 사용자가 누른 게임패드 버튼의
VK 코드를 한 번만 캡처합니다. 진단 도구와 동일한 WH_KEYBOARD_LL 채널을
사용하므로, method_a.py 가 실제로 감지·억제하는 것과 같은 경로입니다.

사용 예:
    from src.screenshot.key_capture import capture_one_key

    capture_one_key(
        timeout_sec=10.0,
        on_captured=lambda vk: print(f"캡처됨: 0x{vk:02X}"),
        on_timeout=lambda: print("시간 초과"),
    )
"""
import ctypes
import ctypes.wintypes as wintypes
import threading
import time
from typing import Callable, Optional

# ── 수식키 필터 (트리거로 허용하지 않는 VK 목록) ─────────────────────────────
_MODIFIER_VKS = frozenset({
    0x10,        # VK_SHIFT
    0x11,        # VK_CONTROL
    0x12,        # VK_MENU (Alt)
    0x5B,        # VK_LWIN
    0x5C,        # VK_RWIN
    0xA0,        # VK_LSHIFT
    0xA1,        # VK_RSHIFT
    0xA2,        # VK_LCONTROL
    0xA3,        # VK_RCONTROL
    0xA4,        # VK_LMENU
    0xA5,        # VK_RMENU
})

_VK_ESC = 0x1B

# ── VK → 표시 이름 매핑 ──────────────────────────────────────────────────────
VK_DISPLAY_NAMES: dict = {
    # 일반 키
    0x08: "백스페이스",    0x09: "탭",           0x0D: "엔터",
    0x1B: "ESC",          0x20: "스페이스",
    0x21: "Page Up",      0x22: "Page Down",
    0x23: "End",          0x24: "Home",
    0x25: "←",            0x26: "↑",
    0x27: "→",            0x28: "↓",
    0x2C: "PrtScn",       0x2D: "Insert",       0x2E: "Delete",
    # Win
    0x5B: "Win (왼쪽)",   0x5C: "Win (오른쪽)",
    # F 키
    0x70: "F1",  0x71: "F2",  0x72: "F3",  0x73: "F4",
    0x74: "F5",  0x75: "F6",  0x76: "F7",  0x77: "F8",
    0x78: "F9",  0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    # 미디어 키
    0xAD: "볼륨 음소거",   0xAE: "볼륨 내리기",  0xAF: "볼륨 높이기",
    0xB0: "다음 트랙",     0xB1: "이전 트랙",
    0xB2: "미디어 정지",   0xB3: "재생/일시정지",
    # 수식키 (참조용)
    0x10: "Shift",         0x11: "Ctrl",          0x12: "Alt",
    0xA0: "Shift (왼쪽)", 0xA1: "Shift (오른쪽)",
    0xA2: "Ctrl (왼쪽)",  0xA3: "Ctrl (오른쪽)",
    0xA4: "Alt (왼쪽)",   0xA5: "Alt (오른쪽)",
}


def vk_to_display_name(vk: int) -> str:
    """VK 코드를 사람이 읽기 쉬운 이름으로 변환합니다."""
    if vk in VK_DISPLAY_NAMES:
        return VK_DISPLAY_NAMES[vk]
    if 0x30 <= vk <= 0x39:
        return chr(vk)          # '0'~'9'
    if 0x41 <= vk <= 0x5A:
        return chr(vk)          # 'A'~'Z'
    return f"VK 0x{vk:02X}"


# ── WH_KEYBOARD_LL 타입 정의 ─────────────────────────────────────────────────

WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_SYSKEYDOWN  = 0x0104
WM_QUIT        = 0x0012
PM_REMOVE      = 0x0001

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# ── 공개 API ─────────────────────────────────────────────────────────────────

def capture_one_key(
    timeout_sec: float = 10.0,
    on_captured: Optional[Callable[[int], None]] = None,
    on_timeout:  Optional[Callable[[], None]]    = None,
) -> None:
    """백그라운드 스레드에서 다음 비수식 키 DOWN 이벤트를 캡처합니다.

    캡처한 키는 억제(return 1)되어 OS·게임에 전달되지 않습니다.
    ESC 는 취소로 처리되어 on_timeout 콜백을 호출합니다.

    Args:
        timeout_sec:  이 시간(초) 안에 입력이 없으면 on_timeout 호출.
        on_captured:  캡처 성공 시 vk_code(int) 를 인자로 호출.
        on_timeout:   시간 초과 또는 ESC 취소 시 호출.
    """
    t = threading.Thread(
        target=_capture_thread,
        args=(timeout_sec, on_captured, on_timeout),
        daemon=True,
        name="key-capture",
    )
    t.start()


# ── 내부 구현 ─────────────────────────────────────────────────────────────────

def _capture_thread(
    timeout_sec: float,
    on_captured: Optional[Callable[[int], None]],
    on_timeout:  Optional[Callable[[], None]],
) -> None:
    thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
    captured_vk: list = []   # [vk] 또는 []

    def _handler(nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            if vk not in _MODIFIER_VKS:
                captured_vk.append(vk if vk != _VK_ESC else None)
                # 훅 스레드 루프 종료
                ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
                return 1   # 이벤트 삭제
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    ctypes.windll.user32.CallNextHookEx.restype  = ctypes.c_longlong
    ctypes.windll.user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
    ]

    proc = HOOKPROC(_handler)
    hook = ctypes.windll.user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
    if not hook:
        if on_timeout:
            on_timeout()
        return

    deadline = time.monotonic() + timeout_sec
    msg = wintypes.MSG()

    while time.monotonic() < deadline:
        ret = ctypes.windll.user32.PeekMessageW(
            ctypes.byref(msg), None, 0, 0, PM_REMOVE
        )
        if ret:
            if msg.message == WM_QUIT:
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.005)

    ctypes.windll.user32.UnhookWindowsHookEx(hook)

    if captured_vk and captured_vk[0] is not None:
        if on_captured:
            on_captured(captured_vk[0])
    else:
        if on_timeout:
            on_timeout()
