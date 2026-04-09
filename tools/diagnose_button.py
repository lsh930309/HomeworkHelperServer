"""
마이크 버튼 진단 도구
=====================
실행하면 XInput, 키보드(WH_KEYBOARD_LL), Raw Input 세 채널을 동시에 감시합니다.
버튼을 누르면 어느 채널에서 신호가 잡히는지, 어떤 값인지 출력합니다.

실행: python tools/diagnose_button.py
종료: Ctrl+C
"""
import ctypes
import ctypes.wintypes as wintypes
import threading
import time
import sys

# ── XInput 상수 ─────────────────────────────────────────────────────────────

XINPUT_BUTTONS = {
    0x0001: "DPAD_UP",
    0x0002: "DPAD_DOWN",
    0x0004: "DPAD_LEFT",
    0x0008: "DPAD_RIGHT",
    0x0010: "START",
    0x0020: "BACK",
    0x0040: "LEFT_THUMB",
    0x0080: "RIGHT_THUMB",
    0x0100: "LEFT_SHOULDER",
    0x0200: "RIGHT_SHOULDER",
    0x1000: "A",
    0x2000: "B",
    0x4000: "X",
    0x8000: "Y",
}

VK_NAMES = {
    0x08: "BACK", 0x09: "TAB", 0x0D: "RETURN", 0x10: "SHIFT",
    0x11: "CTRL", 0x12: "ALT/MENU", 0x13: "PAUSE", 0x14: "CAPITAL",
    0x1B: "ESC", 0x20: "SPACE", 0x21: "PRIOR", 0x22: "NEXT",
    0x23: "END", 0x24: "HOME", 0x25: "LEFT", 0x26: "UP",
    0x27: "RIGHT", 0x28: "DOWN", 0x2C: "SNAPSHOT(PrtScn)",
    0x2D: "INSERT", 0x2E: "DELETE",
    0x5B: "LWIN", 0x5C: "RWIN", 0x5D: "APPS",
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4",
    0x74: "F5", 0x75: "F6", 0x76: "F7", 0x77: "F8",
    0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0xA0: "LSHIFT", 0xA1: "RSHIFT", 0xA2: "LCTRL", 0xA3: "RCTRL",
    0xA4: "LALT", 0xA5: "RALT",
    0xAD: "VOLUME_MUTE", 0xAE: "VOLUME_DOWN", 0xAF: "VOLUME_UP",
    0xB0: "MEDIA_NEXT", 0xB1: "MEDIA_PREV", 0xB2: "MEDIA_STOP",
    0xB3: "MEDIA_PLAY_PAUSE",
}

WM_NAMES = {
    0x0100: "WM_KEYDOWN",
    0x0101: "WM_KEYUP",
    0x0104: "WM_SYSKEYDOWN",
    0x0105: "WM_SYSKEYUP",
}


# ── XInput 구조체 ────────────────────────────────────────────────────────────

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons",      wintypes.WORD),
        ("bLeftTrigger",  ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX",      wintypes.SHORT),
        ("sThumbLY",      wintypes.SHORT),
        ("sThumbRX",      wintypes.SHORT),
        ("sThumbRY",      wintypes.SHORT),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad",        XINPUT_GAMEPAD),
    ]


# ── Raw Input 구조체 ─────────────────────────────────────────────────────────

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", ctypes.c_ushort),
        ("usUsage",     ctypes.c_ushort),
        ("dwFlags",     wintypes.DWORD),
        ("hwndTarget",  wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType",  wintypes.DWORD),
        ("dwSize",  wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam",  wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode",         ctypes.c_ushort),
        ("Flags",            ctypes.c_ushort),
        ("Reserved",         ctypes.c_ushort),
        ("VKey",             ctypes.c_ushort),
        ("Message",          wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWINPUT_UNION(ctypes.Union):
    _fields_ = [("keyboard", RAWKEYBOARD)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data",   RAWINPUT_UNION),
    ]


# ── WH_KEYBOARD_LL 구조체 ────────────────────────────────────────────────────

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# ── 출력 헬퍼 ────────────────────────────────────────────────────────────────

_print_lock = threading.Lock()


def log(channel: str, msg: str) -> None:
    with _print_lock:
        print(f"[{channel:10s}] {msg}", flush=True)


# ── 1. XInput 폴링 스레드 ────────────────────────────────────────────────────

def xinput_thread() -> None:
    try:
        xi = ctypes.windll.xinput1_4
    except OSError:
        try:
            xi = ctypes.windll.xinput9_1_0
        except OSError:
            log("XINPUT", "XInput DLL 로드 실패 — 건너뜀")
            return

    prev = [XINPUT_STATE() for _ in range(4)]
    connected = [False] * 4

    # 초기 상태 수집
    for i in range(4):
        st = XINPUT_STATE()
        if xi.XInputGetState(i, ctypes.byref(st)) == 0:
            connected[i] = True
            prev[i] = st

    log("XINPUT", f"연결된 패드: {[i for i in range(4) if connected[i]]}")

    while True:
        for i in range(4):
            st = XINPUT_STATE()
            ret = xi.XInputGetState(i, ctypes.byref(st))
            if ret != 0:
                if connected[i]:
                    log("XINPUT", f"패드 {i} 연결 끊김")
                    connected[i] = False
                continue
            if not connected[i]:
                log("XINPUT", f"패드 {i} 연결됨")
                connected[i] = True
                prev[i] = st
                continue

            gp = st.Gamepad
            pg = prev[i].Gamepad

            # 버튼 변화
            changed = gp.wButtons ^ pg.wButtons
            if changed:
                pressed  = changed & gp.wButtons
                released = changed & pg.wButtons
                for bit, name in XINPUT_BUTTONS.items():
                    if pressed & bit:
                        log("XINPUT", f"패드{i} 버튼 DOWN: {name} (0x{bit:04X})")
                    if released & bit:
                        log("XINPUT", f"패드{i} 버튼 UP:   {name} (0x{bit:04X})")

            # 트리거 변화 (임계값 10)
            if abs(int(gp.bLeftTrigger) - int(pg.bLeftTrigger)) > 10:
                log("XINPUT", f"패드{i} LT: {gp.bLeftTrigger}")
            if abs(int(gp.bRightTrigger) - int(pg.bRightTrigger)) > 10:
                log("XINPUT", f"패드{i} RT: {gp.bRightTrigger}")

            prev[i] = st
        time.sleep(0.008)  # ~120 Hz


# ── 2. WH_KEYBOARD_LL 훅 스레드 ─────────────────────────────────────────────

WH_KEYBOARD_LL = 13
PM_REMOVE       = 0x0001
WM_QUIT         = 0x0012
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


def keyboard_hook_thread() -> None:
    thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

    def _handler(nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk   = kb.vkCode
            sc   = kb.scanCode
            flags = kb.flags
            wm_name = WM_NAMES.get(wParam, f"WM_0x{wParam:04X}")
            vk_name = VK_NAMES.get(vk, None)
            if vk_name:
                vk_str = f"VK=0x{vk:02X}({vk_name})"
            elif 0x30 <= vk <= 0x39:
                vk_str = f"VK=0x{vk:02X}('{chr(vk)}')"
            elif 0x41 <= vk <= 0x5A:
                vk_str = f"VK=0x{vk:02X}('{chr(vk)}')"
            else:
                vk_str = f"VK=0x{vk:02X}"
            injected = "INJECTED " if (flags & 0x10) else ""
            log("KBD_HOOK", f"{injected}{wm_name} {vk_str} SC=0x{sc:02X} flags=0x{flags:02X}")
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    ctypes.windll.user32.CallNextHookEx.restype  = ctypes.c_longlong
    ctypes.windll.user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
    ]
    proc = HOOKPROC(_handler)
    hook = ctypes.windll.user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
    if not hook:
        log("KBD_HOOK", f"훅 설치 실패 GLE={ctypes.windll.kernel32.GetLastError()}")
        return
    log("KBD_HOOK", "훅 설치 완료")

    msg = wintypes.MSG()
    while True:
        ret = ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
        if ret:
            if msg.message == WM_QUIT:
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.005)

    ctypes.windll.user32.UnhookWindowsHookEx(hook)


# ── 3. Raw Input 수신 창 스레드 ─────────────────────────────────────────────

RIM_TYPEKEYBOARD = 1
WM_INPUT         = 0x00FF
RIDEV_INPUTSINK  = 0x00000100
RI_KEY_BREAK     = 0x01   # key up


def raw_input_thread() -> None:
    """숨김 창을 만들어 WM_INPUT(Raw Keyboard)을 수신."""
    user32  = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hinstance = kernel32.GetModuleHandleW(None)

    # 윈도우 클래스 등록
    WNDPROC_TYPE = ctypes.WINFUNCTYPE(
        ctypes.c_longlong,
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    )

    ri_buf = (ctypes.c_byte * 256)()

    def _wndproc(hwnd, msg, wp, lp):
        if msg == WM_INPUT:
            size = wintypes.UINT(0)
            ctypes.windll.user32.GetRawInputData(
                lp, 0x10000003,  # RID_INPUT
                None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER),
            )
            if size.value <= ctypes.sizeof(ri_buf):
                ctypes.windll.user32.GetRawInputData(
                    lp, 0x10000003,
                    ctypes.byref(ri_buf), ctypes.byref(size),
                    ctypes.sizeof(RAWINPUTHEADER),
                )
                ri = ctypes.cast(ri_buf, ctypes.POINTER(RAWINPUT)).contents
                if ri.header.dwType == RIM_TYPEKEYBOARD:
                    kb = ri.data.keyboard
                    direction = "UP  " if (kb.Flags & RI_KEY_BREAK) else "DOWN"
                    vk   = kb.VKey
                    vk_name = VK_NAMES.get(vk, None)
                    if vk_name:
                        vk_str = f"VK=0x{vk:02X}({vk_name})"
                    elif 0x30 <= vk <= 0x39:
                        vk_str = f"VK=0x{vk:02X}('{chr(vk)}')"
                    elif 0x41 <= vk <= 0x5A:
                        vk_str = f"VK=0x{vk:02X}('{chr(vk)}')"
                    else:
                        vk_str = f"VK=0x{vk:02X}"
                    hdev = ri.header.hDevice
                    log("RAW_INPUT",
                        f"KBD {direction} {vk_str} SC=0x{kb.MakeCode:02X} "
                        f"flags=0x{kb.Flags:02X} hDevice=0x{hdev:016X}")
            return user32.DefWindowProcW(hwnd, msg, wp, lp)
        elif msg == 0x0002:  # WM_DESTROY
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    wndproc_cb = WNDPROC_TYPE(_wndproc)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize",        wintypes.UINT),
            ("style",         wintypes.UINT),
            ("lpfnWndProc",   WNDPROC_TYPE),
            ("cbClsExtra",    ctypes.c_int),
            ("cbWndExtra",    ctypes.c_int),
            ("hInstance",     wintypes.HINSTANCE),
            ("hIcon",         wintypes.HANDLE),
            ("hCursor",       wintypes.HANDLE),
            ("hbrBackground", wintypes.HANDLE),
            ("lpszMenuName",  wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm",       wintypes.HANDLE),
        ]

    cls_name = "DiagRawInput"
    wc = WNDCLASSEXW()
    wc.cbSize      = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wndproc_cb
    wc.hInstance   = hinstance
    wc.lpszClassName = cls_name
    user32.RegisterClassExW(ctypes.byref(wc))

    hwnd = user32.CreateWindowExW(
        0, cls_name, "DiagRawInput", 0,
        0, 0, 0, 0, -3, None, hinstance, None,  # HWND_MESSAGE
    )
    if not hwnd:
        log("RAW_INPUT", f"창 생성 실패 GLE={kernel32.GetLastError()}")
        return

    # Raw Keyboard 등록 (RIDEV_INPUTSINK: 포커스 없어도 수신)
    rid = RAWINPUTDEVICE()
    rid.usUsagePage = 0x01   # Generic Desktop
    rid.usUsage     = 0x06   # Keyboard
    rid.dwFlags     = RIDEV_INPUTSINK
    rid.hwndTarget  = hwnd
    ok = user32.RegisterRawInputDevices(
        ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE),
    )
    if not ok:
        log("RAW_INPUT", f"RegisterRawInputDevices 실패 GLE={kernel32.GetLastError()}")
        return
    log("RAW_INPUT", "Raw Keyboard 수신 등록 완료")

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("버튼 진단 도구 — 마이크 버튼을 눌러보세요")
    print("XInput / WH_KEYBOARD_LL / Raw Input 세 채널 동시 감시")
    print("종료: Ctrl+C")
    print("=" * 60)

    threads = [
        threading.Thread(target=xinput_thread,       daemon=True, name="xinput"),
        threading.Thread(target=keyboard_hook_thread, daemon=True, name="kbd_hook"),
        threading.Thread(target=raw_input_thread,     daemon=True, name="raw_input"),
    ]
    for t in threads:
        t.start()

    # 스레드 초기화 대기
    time.sleep(0.5)
    print("\n[준비 완료] 버튼을 눌러보세요.\n")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
