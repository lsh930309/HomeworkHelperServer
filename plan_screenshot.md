# 스크린샷 기능 구현 계획

> 작성일: 2026-03-19
> 상태: 사전 조사 완료, 구현 보류 (메커니즘 확인 필요)

---

## 배경

사이드바에 여분 공간이 생겨 새로운 기능 섹션 추가를 검토 중.
게임 스크린샷 기능을 사이드바에 통합하되, **게임패드 버튼으로 트리거**하는 방식을 목표로 함.

---

## 사용 환경

- 게임패드: Gamesir (Xbox 라이센스 취득 제품)
- PC 인식: Xbox 360 컨트롤러로 인식
- 현재 동작: 패드의 **[공유] 버튼** → Game Bar 스크린샷 촬영
- 문제점:
  - Xbox 라이센스 제품이라 제조사 제공 버튼 리매핑 기능 없음
  - Game Bar 방식 사용 시, 게임패드→키보드/마우스 UI 전환이 발생해 **마우스 커서가 화면에 나타남**

---

## 목표

1. [공유] 버튼 입력을 가로채어 Game Bar 대신 **앱 자체 스크린샷** 기능 실행
2. 이 과정에서 키보드/마우스 입력이 발생하지 않도록 하여 **마우스 커서 비표시 유지**
3. 스크린샷 결과를 사이드바에서 확인/관리할 수 있도록 통합

---

## 메커니즘 분석

### [공유] 버튼의 동작 원리 추정

Xbox 360 컨트롤러 프로토콜에는 "공유" 버튼이 원래 없음.
따라서 Gamesir 펌웨어/드라이버가 둘 중 하나의 방식으로 동작하는 것으로 추정:

| 방식 | 가능성 | 설명 |
|---|---|---|
| **가상 HID 키보드로 `Win+Alt+PrtScn` 주입** | **높음** | 컨트롤러 드라이버가 가상 키보드 장치를 생성하고 해당 키 조합 전송 |
| **XInput Guide 버튼 → Game Bar가 해석** | 낮음 | XInput의 Guide 버튼(0x0400)을 Game Bar가 감지해 처리 |

### 메커니즘 확인 방법 (추후 수행)

장치관리자(`devmgmt.msc`) → 휴먼 인터페이스 장치:

- **패드 연결 시 "HID 키보드 장치"가 새로 생김** → 가상 키보드 방식 → **구현 방법 A**
- **새로 생기지 않음** → XInput Guide 버튼 방식 → **구현 방법 B**

---

## 구현 방법 A: WH_KEYBOARD_LL 훅 (가상 키보드 방식)

### 원리

`WH_KEYBOARD_LL`은 `Win+Alt+PrtScn`이 Game Bar 서비스에 도달하기 **전에** 가로챌 수 있음.
훅 콜백에서 `1` 반환 시 해당 키 이벤트가 OS에서 완전히 삭제됨.

```
[공유 버튼 누름]
    ↓
[가상 HID 키보드 → Win+Alt+PrtScn 전송]
    ↓
[WH_KEYBOARD_LL 훅 → 이벤트 삭제 + 앱 자체 캡처 실행]
    ↓
[Game Bar: 이벤트 미수신]
[게임: 키보드 입력 없음 → UI 모드 전환 없음 → 커서 비표시 유지]
```

### 샘플 코드 (Python / ctypes)

```python
import ctypes
import ctypes.wintypes as wintypes

WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
VK_SNAPSHOT    = 0x2C   # PrtScn
VK_LWIN        = 0x5B
VK_MENU        = 0x12   # Alt

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

def install_screenshot_hook(screenshot_callback):
    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )

    def handler(nCode, wParam, lParam):
        if nCode >= 0 and wParam == WM_KEYDOWN:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            win_down = ctypes.windll.user32.GetAsyncKeyState(VK_LWIN) & 0x8000
            alt_down = ctypes.windll.user32.GetAsyncKeyState(VK_MENU) & 0x8000
            if kb.vkCode == VK_SNAPSHOT and win_down and alt_down:
                screenshot_callback()  # 앱 자체 캡처 실행
                return 1               # 이벤트 완전 삭제
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    proc = HOOKPROC(handler)
    hook = ctypes.windll.user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, proc, None, 0
    )
    return hook, proc  # proc은 GC 방지를 위해 반드시 보관
```

### 주의사항

- `Win+L` (화면 잠금) 등 일부 시스템 단축키는 LL 훅으로도 차단 불가
- `Win+Alt+PrtScn`은 보호 목록에 없으므로 차단 가능
- `proc` 참조를 유지하지 않으면 GC가 수거하여 크래시 발생 → 멤버 변수로 보관 필수
- 훅은 메시지 루프가 있는 스레드에서 실행해야 함 (PyQt6 메인 스레드 OK)

---

## 구현 방법 B: XInput Guide 버튼 방식

### 원리

Game Bar를 캡처 단축키 한정으로 비활성화 후, XInput 폴링으로 Guide 버튼 감지.

```
레지스트리 설정:
HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR
  AppCaptureEnabled = 0   (Game Bar 스크린샷 캡처 비활성화)
```

```python
import ctypes

XINPUT_GAMEPAD_GUIDE = 0x0400  # 비공개 확장 (XInputGetStateEx 필요)

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons",      ctypes.c_ushort),
        ("bLeftTrigger",  ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX",      ctypes.c_short),
        ("sThumbLY",      ctypes.c_short),
        ("sThumbRX",      ctypes.c_short),
        ("sThumbRY",      ctypes.c_short),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad",        XINPUT_GAMEPAD),
    ]

# XInputGetStateEx (비공개 ordinal 100) - Guide 버튼 읽기 가능
xinput = ctypes.windll.xinput1_4
XInputGetStateEx = xinput[100]

def poll_guide_button(controller_index=0):
    state = XINPUT_STATE()
    if XInputGetStateEx(controller_index, ctypes.byref(state)) == 0:
        return bool(state.Gamepad.wButtons & XINPUT_GAMEPAD_GUIDE)
    return False
```

### 주의사항

- `XInputGetStateEx`는 비공개 API (ordinal 100) — 안정성 낮음
- Game Bar를 완전히 끄지 않고 캡처 기능만 비활성화할 수 있는지 추가 검증 필요
- Xbox 360 스타일 컨트롤러에서 Guide 버튼이 실제로 공유 버튼과 매핑되는지 확인 필요

---

## 스크린샷 캡처 구현 선택지

| 방법 | 장점 | 단점 | 권장 상황 |
|---|---|---|---|
| `mss` 라이브러리 | pip install, 간단 | 일부 DX 게임 검은 화면 | 프로토타입 |
| DXGI Duplication (`ctypes`) | GPU 렌더링까지 캡처 | 구현 복잡 | 프로덕션 |
| `Windows.Graphics.Capture` (WinRT) | HDR, DirectX 완벽 지원 | `winrt` 패키지 필요 | 최고 품질 |
| Game Bar 폴더 감시 | 구현 0줄 | 제어권 없음 | 최후 수단 |

**권장**: 1단계 `mss`로 기본 동작 확인 → 2단계 DXGI Duplication으로 교체

### 커서 제거 보조 코드 (방법 A 사용 시에도 혹시 모를 경우 대비)

```python
def capture_without_cursor():
    ctypes.windll.user32.ShowCursor(False)
    try:
        import mss
        with mss.mss() as sct:
            return sct.grab(sct.monitors[0])  # 전체 화면
    finally:
        ctypes.windll.user32.ShowCursor(True)
```

---

## 사이드바 통합 UI 구조 (안)

```
사이드바 스크린샷 섹션
├── 버튼: "지금 촬영"         ← 마우스로 직접 트리거
├── 최근 스크린샷 썸네일 목록  ← 클릭 시 파일 탐색기로 열기
└── 설정 (사이드바 설정 다이얼로그에 추가)
    ├── 저장 경로
    ├── 파일명 형식 (날짜/게임명 포함 옵션)
    ├── 게임패드 트리거 ON/OFF
    └── (방법 B의 경우) 버튼 조합 선택
```

---

## 다음 단계 체크리스트

- [ ] 장치관리자에서 패드 연결 시 "HID 키보드 장치" 추가 여부 확인
  - 추가됨 → **방법 A** 진행
  - 추가 안 됨 → XInput Guide 버튼 여부 테스트 후 **방법 B** 진행
- [ ] `mss` 라이브러리로 기본 스크린샷 캡처 동작 확인 (DX 게임에서 검은 화면 여부)
- [ ] 방법 A 선택 시: WH_KEYBOARD_LL 훅 단독 테스트 스크립트 작성
- [ ] 사이드바 스크린샷 섹션 UI 구현
- [ ] 저장 경로 / 파일명 형식 설정 항목 추가
