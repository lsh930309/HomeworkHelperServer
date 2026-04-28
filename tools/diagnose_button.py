"""
마이크 버튼 진단 도구
=====================
XInput / WH_KEYBOARD_LL / Raw Input(키보드) /
Raw Input(Consumer Control) / Raw Input(HID 전체) 다섯 채널을 동시에 감시합니다.

실행: python tools/diagnose_button.py
종료: Ctrl+C
"""
import ctypes
import ctypes.wintypes as wintypes
import threading
import time

# ── XInput 상수 ─────────────────────────────────────────────────────────────

XINPUT_BUTTONS = {
    0x0001: "DPAD_UP",    0x0002: "DPAD_DOWN",
    0x0004: "DPAD_LEFT",  0x0008: "DPAD_RIGHT",
    0x0010: "START",      0x0020: "BACK",
    0x0040: "LEFT_THUMB", 0x0080: "RIGHT_THUMB",
    0x0100: "LB",         0x0200: "RB",
    0x1000: "A",          0x2000: "B",
    0x4000: "X",          0x8000: "Y",
}

VK_NAMES = {
    0x08: "BACK", 0x09: "TAB", 0x0D: "RETURN", 0x10: "SHIFT",
    0x11: "CTRL", 0x12: "ALT", 0x14: "CAPITAL", 0x1B: "ESC",
    0x20: "SPACE", 0x2C: "SNAPSHOT(PrtScn)",
    0x25: "LEFT",  0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN",
    0x5B: "LWIN",  0x5C: "RWIN",
    0x70: "F1",  0x71: "F2",  0x72: "F3",  0x73: "F4",
    0x74: "F5",  0x75: "F6",  0x76: "F7",  0x77: "F8",
    0x78: "F9",  0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0xA0: "LSHIFT", 0xA1: "RSHIFT", 0xA2: "LCTRL", 0xA3: "RCTRL",
    0xA4: "LALT",   0xA5: "RALT",
    0xAD: "VOLUME_MUTE", 0xAE: "VOLUME_DOWN", 0xAF: "VOLUME_UP",
    0xB0: "MEDIA_NEXT",  0xB1: "MEDIA_PREV",
    0xB2: "MEDIA_STOP",  0xB3: "MEDIA_PLAY_PAUSE",
}

WM_NAMES = {
    0x0100: "KEYDOWN", 0x0101: "KEYUP",
    0x0104: "SYSKEYDOWN", 0x0105: "SYSKEYUP",
}

# Consumer Control Usage ID → 이름 (Usage Page 0x0C)
CONSUMER_USAGE = {
    0x00B0: "Play",            0x00B1: "Pause",
    0x00B3: "Fast Forward",    0x00B4: "Rewind",
    0x00B5: "Scan Next Track", 0x00B6: "Scan Prev Track",
    0x00B7: "Stop",            0x00CD: "Play/Pause",
    0x00CF: "Microphone",      0x00E0: "Volume",
    0x00E2: "Mute",            0x00E5: "Bass Boost",
    0x00E9: "Volume Inc",      0x00EA: "Volume Dec",
    0x0221: "AC Search",       0x0223: "AC Home",
    0x0224: "AC Back",         0x0225: "AC Forward",
    0x0226: "AC Stop",         0x0227: "AC Refresh",
    0x018A: "Email",           0x0192: "Calculator",
    0x0194: "My Computer",
}

# ── 공통 구조체 ──────────────────────────────────────────────────────────────

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

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

class RAWHID(ctypes.Structure):
    _fields_ = [
        ("dwSizeHid", wintypes.DWORD),
        ("dwCount",   wintypes.DWORD),
        ("bRawData",  ctypes.c_byte * 1),   # 가변 길이, 첫 바이트만 선언
    ]

class RAWINPUT_UNION(ctypes.Union):
    _fields_ = [
        ("keyboard", RAWKEYBOARD),
        ("hid",      RAWHID),
    ]

class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data",   RAWINPUT_UNION),
    ]

RIM_TYPEMOUSE    = 0
RIM_TYPEKEYBOARD = 1
RIM_TYPEHID      = 2
RID_INPUT        = 0x10000003
RIDEV_INPUTSINK  = 0x00000100
RI_KEY_BREAK     = 0x01

WH_KEYBOARD_LL = 13
PM_REMOVE      = 0x0001
WM_QUIT        = 0x0012
WM_INPUT       = 0x00FF
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_print_lock = threading.Lock()

def log(channel: str, msg: str) -> None:
    with _print_lock:
        print(f"[{channel:12s}] {msg}", flush=True)

def vk_str(vk: int) -> str:
    name = VK_NAMES.get(vk)
    if name:
        return f"VK=0x{vk:02X}({name})"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return f"VK=0x{vk:02X}('{chr(vk)}')"
    return f"VK=0x{vk:02X}"

# ── 1. XInput 폴링 ───────────────────────────────────────────────────────────

def xinput_thread() -> None:
    try:
        xi = ctypes.windll.xinput1_4
    except OSError:
        try:
            xi = ctypes.windll.xinput9_1_0
        except OSError:
            log("XINPUT", "XInput DLL 로드 실패")
            return

    prev = [XINPUT_STATE() for _ in range(4)]
    connected = [False] * 4
    for i in range(4):
        st = XINPUT_STATE()
        if xi.XInputGetState(i, ctypes.byref(st)) == 0:
            connected[i] = True
            prev[i] = st

    log("XINPUT", f"연결된 패드: {[i for i in range(4) if connected[i]]}")

    while True:
        for i in range(4):
            st = XINPUT_STATE()
            if xi.XInputGetState(i, ctypes.byref(st)) != 0:
                connected[i] = False
                continue
            if not connected[i]:
                connected[i] = True
                prev[i] = st
                log("XINPUT", f"패드 {i} 연결됨")
                continue
            gp, pg = st.Gamepad, prev[i].Gamepad
            changed = gp.wButtons ^ pg.wButtons
            for bit, name in XINPUT_BUTTONS.items():
                if changed & bit:
                    direction = "DOWN" if (gp.wButtons & bit) else "UP  "
                    log("XINPUT", f"패드{i} {direction} {name} (0x{bit:04X})")
            if abs(int(gp.bLeftTrigger)  - int(pg.bLeftTrigger))  > 10:
                log("XINPUT", f"패드{i} LT={gp.bLeftTrigger}")
            if abs(int(gp.bRightTrigger) - int(pg.bRightTrigger)) > 10:
                log("XINPUT", f"패드{i} RT={gp.bRightTrigger}")
            prev[i] = st
        time.sleep(0.008)

# ── 2. WH_KEYBOARD_LL ────────────────────────────────────────────────────────

def keyboard_hook_thread() -> None:
    def _handler(nCode, wParam, lParam):
        if nCode >= 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            injected = "INJECTED " if (kb.flags & 0x10) else ""
            wm = WM_NAMES.get(wParam, f"WM_0x{wParam:04X}")
            log("KBD_HOOK", f"{injected}{wm} {vk_str(kb.vkCode)} SC=0x{kb.scanCode:02X}")
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

# ── 3. Raw Input 수신 창 (키보드 + Consumer Control + 전체 HID) ──────────────

USAGE_PAGE_NAMES = {0x01: "GenericDesktop", 0x0C: "ConsumerControl"}

def raw_input_thread() -> None:
    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hinstance = kernel32.GetModuleHandleW(None)

    WNDPROC_TYPE = ctypes.WINFUNCTYPE(
        ctypes.c_longlong,
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    )

    buf = (ctypes.c_byte * 1024)()

    def _handle_raw_input(lp):
        size = wintypes.UINT(0)
        user32.GetRawInputData(lp, RID_INPUT, None,
                               ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if size.value == 0 or size.value > ctypes.sizeof(buf):
            return
        user32.GetRawInputData(lp, RID_INPUT, ctypes.byref(buf),
                               ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        ri = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
        rtype = ri.header.dwType
        hdev  = ri.header.hDevice

        if rtype == RIM_TYPEKEYBOARD:
            kb = ri.data.keyboard
            direction = "UP  " if (kb.Flags & RI_KEY_BREAK) else "DOWN"
            log("RAW_KBD",
                f"KBD {direction} {vk_str(kb.VKey)} SC=0x{kb.MakeCode:02X} "
                f"hDev=0x{hdev:016X}")

        elif rtype == RIM_TYPEHID:
            # dwSizeHid, dwCount 읽기
            dword_ptr = ctypes.cast(
                ctypes.addressof(ri) + ctypes.sizeof(RAWINPUTHEADER),
                ctypes.POINTER(wintypes.DWORD)
            )
            sz_hid = dword_ptr[0]
            count  = dword_ptr[1]
            # 실제 report bytes
            data_start = ctypes.addressof(ri) + ctypes.sizeof(RAWINPUTHEADER) + 8
            total = sz_hid * count
            raw_bytes = bytes(
                (ctypes.c_byte * total).from_address(data_start)
            )
            hex_str = " ".join(f"{b:02X}" for b in raw_bytes)

            # Consumer Control usage 디코딩 시도
            # 일반적으로 2~3바이트 report: [report_id, usage_lo, usage_hi]
            # 또는 [usage_lo, usage_hi]
            decoded = ""
            if len(raw_bytes) >= 2:
                # report_id=0 인 경우: bytes 0,1 이 usage
                usage16 = raw_bytes[0] | (raw_bytes[1] << 8)
                name = CONSUMER_USAGE.get(usage16)
                if name:
                    decoded = f" → ConsumerUsage=0x{usage16:04X}({name})"
                # report_id 있는 경우: bytes 1,2 이 usage
                if not decoded and len(raw_bytes) >= 3:
                    usage16b = raw_bytes[1] | (raw_bytes[2] << 8)
                    name2 = CONSUMER_USAGE.get(usage16b)
                    if name2:
                        decoded = f" → ConsumerUsage=0x{usage16b:04X}({name2})"

            log("RAW_HID",
                f"HID sz={sz_hid} cnt={count} bytes=[{hex_str}]{decoded} "
                f"hDev=0x{hdev:016X}")

    def _wndproc(hwnd, msg, wp, lp):
        if msg == WM_INPUT:
            _handle_raw_input(lp)
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

    cls_name = "DiagRawInput2"
    wc = WNDCLASSEXW()
    wc.cbSize        = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc   = wndproc_cb
    wc.hInstance     = hinstance
    wc.lpszClassName = cls_name
    user32.RegisterClassExW(ctypes.byref(wc))

    hwnd = user32.CreateWindowExW(
        0, cls_name, "DiagRawInput2", 0,
        0, 0, 0, 0, -3, None, hinstance, None,  # HWND_MESSAGE
    )
    if not hwnd:
        log("RAW_INPUT", f"창 생성 실패 GLE={kernel32.GetLastError()}")
        return

    # 세 가지 Usage 등록
    # 1) Keyboard (0x01/0x06)
    # 2) Consumer Control (0x0C/0x01)
    # 3) Generic Desktop – Gamepad (0x01/0x05)
    devices = (RAWINPUTDEVICE * 3)()
    # Keyboard
    devices[0].usUsagePage = 0x01
    devices[0].usUsage     = 0x06
    devices[0].dwFlags     = RIDEV_INPUTSINK
    devices[0].hwndTarget  = hwnd
    # Consumer Control
    devices[1].usUsagePage = 0x0C
    devices[1].usUsage     = 0x01
    devices[1].dwFlags     = RIDEV_INPUTSINK
    devices[1].hwndTarget  = hwnd
    # Gamepad (XInput 이외 버튼이 여기 잡힐 수 있음)
    devices[2].usUsagePage = 0x01
    devices[2].usUsage     = 0x05
    devices[2].dwFlags     = RIDEV_INPUTSINK
    devices[2].hwndTarget  = hwnd

    ok = user32.RegisterRawInputDevices(
        devices, 3, ctypes.sizeof(RAWINPUTDEVICE),
    )
    if not ok:
        log("RAW_INPUT", f"RegisterRawInputDevices 실패 GLE={kernel32.GetLastError()}")
        return
    log("RAW_INPUT", "Keyboard + ConsumerControl + Gamepad HID 등록 완료")

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("버튼 진단 도구 v2 — 마이크 버튼을 눌러보세요")
    print("채널: XInput / KBD_HOOK / RAW_KBD / RAW_HID")
    print("종료: Ctrl+C")
    print("=" * 60)

    threads = [
        threading.Thread(target=xinput_thread,       daemon=True, name="xinput"),
        threading.Thread(target=keyboard_hook_thread, daemon=True, name="kbd_hook"),
        threading.Thread(target=raw_input_thread,     daemon=True, name="raw_input"),
    ]
    for t in threads:
        t.start()

    time.sleep(0.6)
    print("\n[준비 완료] 버튼을 눌러보세요.\n")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n종료합니다.")

if __name__ == "__main__":
    main()
