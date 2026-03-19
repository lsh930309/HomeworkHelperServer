"""
게임패드 [공유] 버튼 스크린샷 메커니즘 진단 도구
=================================================

실행:  python tools/diagnose_gamepad_screenshot.py

두 가지 메커니즘 중 어떤 방법이 적용되는지 판별합니다.

  Method A — 가상 HID 키보드가 Win+Alt+PrtScn을 주입하는 방식
             → WH_KEYBOARD_LL 훅으로 이벤트를 가로채고 억제

  Method B — XInput Guide 버튼(0x0400)이 발동되는 방식
             → XInputGetStateEx 폴링으로 감지

결과는 src/screenshot/_method.txt 에 자동 저장됩니다.
다음 단계: python tools/select_screenshot_method.py
"""
import ctypes
import ctypes.wintypes as wintypes
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ──────────────────────────────────────────────────────────────
# Win32 상수
# ──────────────────────────────────────────────────────────────
WH_KEYBOARD_LL  = 13
WM_KEYDOWN      = 0x0100
WM_SYSKEYDOWN   = 0x0104
WM_QUIT         = 0x0012
VK_SNAPSHOT     = 0x2C
VK_LWIN         = 0x5B
VK_RWIN         = 0x5C
VK_MENU         = 0x12
PM_REMOVE       = 0x0001

RIM_TYPEKEYBOARD    = 1
RIDI_DEVICENAME     = 0x20000007

XINPUT_GAMEPAD_GUIDE        = 0x0400
ERROR_DEVICE_NOT_CONNECTED  = 1167

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


# ──────────────────────────────────────────────────────────────
# 구조체
# ──────────────────────────────────────────────────────────────

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [
        ("hDevice", wintypes.HANDLE),
        ("dwType",  wintypes.DWORD),
    ]


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


# ──────────────────────────────────────────────────────────────
# Raw Input 키보드 장치 열거
# ──────────────────────────────────────────────────────────────

def list_raw_keyboard_devices() -> list:
    """현재 시스템의 Raw Input 키보드 장치 경로 목록을 반환합니다."""
    count = wintypes.UINT(0)
    sz = ctypes.sizeof(RAWINPUTDEVICELIST)
    ctypes.windll.user32.GetRawInputDeviceList(None, ctypes.byref(count), sz)
    if count.value == 0:
        return []

    devices = (RAWINPUTDEVICELIST * count.value)()
    ctypes.windll.user32.GetRawInputDeviceList(devices, ctypes.byref(count), sz)

    names = []
    for d in devices:
        if d.dwType != RIM_TYPEKEYBOARD:
            continue
        buf_sz = wintypes.UINT(0)
        ctypes.windll.user32.GetRawInputDeviceInfoW(
            d.hDevice, RIDI_DEVICENAME, None, ctypes.byref(buf_sz)
        )
        if buf_sz.value == 0:
            continue
        buf = ctypes.create_unicode_buffer(buf_sz.value)
        ctypes.windll.user32.GetRawInputDeviceInfoW(
            d.hDevice, RIDI_DEVICENAME, buf, ctypes.byref(buf_sz)
        )
        names.append(buf.value)
    return names


# ──────────────────────────────────────────────────────────────
# XInput 초기화
# ──────────────────────────────────────────────────────────────

def _load_xinput_ex():
    """XInputGetStateEx (ordinal 100) 로드. 실패 시 None."""
    dll = None
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            dll = ctypes.windll.LoadLibrary(name)
            break
        except OSError:
            continue
    if dll is None:
        return None
    try:
        fn = dll[100]
        fn.restype = ctypes.c_ulong
        fn.argtypes = [ctypes.c_ulong, ctypes.POINTER(_XINPUT_STATE)]
        return fn
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
# 테스트 1: WH_KEYBOARD_LL 훅으로 Win+Alt+PrtScn 감지
# ──────────────────────────────────────────────────────────────

def test_keyboard_hook(timeout_sec: int = 12) -> bool:
    """Win+Alt+PrtScn이 LL 훅에서 감지되면 True를 반환합니다."""
    detected   = threading.Event()
    tid_holder = [0]

    def _hook_thread():
        tid_holder[0] = ctypes.windll.kernel32.GetCurrentThreadId()

        def _handler(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == VK_SNAPSHOT:
                    win_dn = bool(
                        ctypes.windll.user32.GetAsyncKeyState(VK_LWIN) & 0x8000
                        or ctypes.windll.user32.GetAsyncKeyState(VK_RWIN) & 0x8000
                    )
                    alt_dn = bool(ctypes.windll.user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                    if win_dn and alt_dn:
                        detected.set()
                        return 1  # 이벤트 삭제 (Game Bar에 전달 안 됨)
            return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

        proc = HOOKPROC(_handler)
        hook = ctypes.windll.user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
        if not hook:
            print("  [오류] WH_KEYBOARD_LL 훅 설치 실패")
            return

        msg = wintypes.MSG()
        while not detected.is_set():
            ret = ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
            if ret:
                if msg.message == WM_QUIT:
                    break
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.005)

        ctypes.windll.user32.UnhookWindowsHookEx(hook)

    t = threading.Thread(target=_hook_thread, daemon=True)
    t.start()

    # thread_id 채워질 때까지 대기
    for _ in range(40):
        if tid_holder[0]:
            break
        time.sleep(0.025)

    print(f"  게임패드 [공유] 버튼을 눌러 주세요 ({timeout_sec}초 대기)...", flush=True)
    result = detected.wait(timeout=timeout_sec)

    if tid_holder[0]:
        ctypes.windll.user32.PostThreadMessageW(tid_holder[0], WM_QUIT, 0, 0)
    t.join(timeout=2)
    return result


# ──────────────────────────────────────────────────────────────
# 보조: Raw Input 장치 변화 감지
# ──────────────────────────────────────────────────────────────

def check_raw_device_change(timeout_sec: int = 8) -> list:
    """Share 버튼 누름 전후로 새로 나타나는 Raw Input 키보드 장치를 반환합니다."""
    before = set(list_raw_keyboard_devices())
    print(f"  게임패드 [공유] 버튼을 눌러 주세요 ({timeout_sec}초 대기)...", flush=True)

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        after = set(list_raw_keyboard_devices())
        new_devs = list(after - before)
        if new_devs:
            return new_devs
        time.sleep(0.2)
    return []


# ──────────────────────────────────────────────────────────────
# 테스트 2: XInput Guide 버튼 폴링
# ──────────────────────────────────────────────────────────────

def test_xinput_guide(timeout_sec: int = 8) -> bool:
    """XInputGetStateEx로 Guide 버튼(0x0400)이 감지되면 True를 반환합니다."""
    get_state_ex = _load_xinput_ex()
    if get_state_ex is None:
        print("  [건너뜀] XInputGetStateEx(ordinal 100) 로드 불가")
        return False

    connected = []
    for i in range(4):
        state = _XINPUT_STATE()
        if get_state_ex(i, ctypes.byref(state)) == 0:
            connected.append(i)

    if not connected:
        print("  [건너뜀] XInput 컨트롤러 미감지")
        return False

    print(f"  XInput 컨트롤러 감지: 슬롯 {connected}")
    print(f"  게임패드 [공유] 버튼을 눌러 주세요 ({timeout_sec}초 대기)...", flush=True)

    prev = {i: False for i in connected}
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for i in connected:
            state = _XINPUT_STATE()
            if get_state_ex(i, ctypes.byref(state)) == 0:
                guide = bool(state.Gamepad.wButtons & XINPUT_GAMEPAD_GUIDE)
                if guide and not prev[i]:
                    return True
                prev[i] = guide
        time.sleep(0.05)
    return False


# ──────────────────────────────────────────────────────────────
# 진단 실행
# ──────────────────────────────────────────────────────────────

def run_diagnosis() -> str:
    """진단을 실행하고 채택된 방법 'A' 또는 'B'를 반환합니다."""
    print()
    print("=" * 62)
    print("  게임패드 스크린샷 메커니즘 진단 도구")
    print("=" * 62)

    # 현재 Raw Input 키보드 장치 목록
    kb_devices = list_raw_keyboard_devices()
    print(f"\n[현재 Raw Input 키보드 장치: {len(kb_devices)}개]")
    for d in kb_devices:
        print(f"  {d}")

    print()
    input("게임패드가 PC에 연결된 상태인지 확인 후 Enter 를 누르세요...")

    # ── 테스트 1: LL 훅 ─────────────────────────────────────────
    print()
    print("[테스트 1] WH_KEYBOARD_LL 훅 — Win+Alt+PrtScn 감지")
    print("  ※ Game Bar 창이 뜨면 닫아도 됩니다.")
    hook_ok = test_keyboard_hook(timeout_sec=12)
    print(f"  결과: {'감지됨 ✓' if hook_ok else '감지 안 됨'}")

    # ── 보조: Raw Input 장치 변화 ───────────────────────────────
    print()
    print("[보조 정보] Share 버튼 누름 시 새 HID 키보드 장치 출현 여부")
    new_devs = check_raw_device_change(timeout_sec=8)
    if new_devs:
        print(f"  새 장치 감지됨 ✓:")
        for d in new_devs:
            print(f"    {d}")
    else:
        print("  새 장치 없음")

    # ── 테스트 2: XInput Guide ──────────────────────────────────
    print()
    print("[테스트 2] XInput Guide 버튼 폴링 (XInputGetStateEx ordinal 100)")
    xinput_ok = test_xinput_guide(timeout_sec=8)
    print(f"  결과: {'감지됨 ✓' if xinput_ok else '감지 안 됨'}")

    # ── 판정 ────────────────────────────────────────────────────
    print()
    print("=" * 62)
    print("  판정 결과")
    print("=" * 62)

    if hook_ok:
        method = "A"
        reason = "WH_KEYBOARD_LL 훅에서 Win+Alt+PrtScn 감지됨 → 가상 키보드 주입 방식"
    elif xinput_ok:
        method = "B"
        reason = "XInput Guide 버튼 감지됨 → XInput 폴링 방식"
    else:
        method = "A"
        reason = (
            "자동 판정 불가 (Share 버튼 입력이 감지되지 않음)\n"
            "  기본값 Method A로 설정합니다. 동작하지 않으면 B로 전환하세요."
        )

    print(f"\n  채택: Method {method}")
    print(f"  이유: {reason}")

    out_path = ROOT / "src" / "screenshot" / "_method.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(method, encoding="utf-8")
    print(f"\n  결과 저장 → {out_path.relative_to(ROOT)}")
    print()
    print("  다음 단계: python tools/select_screenshot_method.py")
    print("=" * 62)
    return method


if __name__ == "__main__":
    run_diagnosis()
