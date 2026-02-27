# OS 의존성 분석 — macOS 유니버셜 앱 전환 가능성

> 분석일: 2026-02-22
> 목적: 현재 Windows 전용으로 개발된 앱을 macOS에서도 동작하는 유니버셜 앱으로 개선하기 위한 사전 조사

---

## 핵심 결론

**전환은 가능하지만 상당한 작업량이 필요하다.**

코드 곳곳에 `if os.name == 'nt':` 분기가 존재하고, 핵심 비즈니스 로직(프로세스 모니터링, API 서버, DB, HoYoLab 연동)은 이미 크로스플랫폼으로 설계되어 있다. 그러나 `pywin32`, `Windows-Toasts`, `ctypes.windll` 등 Windows 전용 라이브러리 의존도가 높아 일부 기능은 macOS 대안으로 재구현이 필요하다.

---

## Windows 전용 의존성 목록

### 1. `pywin32` 패키지 — 가장 큰 장벽

| 사용 모듈 | 파일 | 용도 | macOS 대안 |
|---|---|---|---|
| `winreg` | `src/utils/windows.py` | 레지스트리 기반 자동 시작 등록 | `~/Library/LaunchAgents/` plist (LaunchAgent) |
| `winshell` | `src/utils/windows.py` | 시작 프로그램 폴더 경로 조회 | 불필요 (LaunchAgent로 대체) |
| `win32crypt` | `src/utils/browser_cookie_extractor.py` | Chrome 쿠키 DPAPI 복호화 | macOS Keychain API (`pyobjc-framework-Security`) |
| `win32api`, `win32security` | `src/core/launcher.py`, `homework_helper.pyw` | 프로세스 권한 수준 검사 | `os.getuid()`, POSIX API |
| `win32event` | `homework_helper.pyw` | Named Mutex (단일 인스턴스 보장) | PID 파일 fallback 이미 존재 |
| `win32com.client` | `src/core/launcher.py`, `src/utils/windows.py` | `.lnk` 바로가기 생성/파싱 | macOS는 `.webloc` / `.app` 번들 사용 |
| `win32process`, `win32con` | `src/core/launcher.py` | 프로세스 토큰 권한 확인 | POSIX `os.getuid()` / `subprocess` |

### 2. `Windows-Toasts` — 완전 교체 필요

**파일**: `src/core/notifier.py`

`InteractableWindowsToaster`에 100% 의존하며 macOS에서 실행 불가. 버튼 상호작용(Toast 클릭 시 콜백)이 핵심 기능으로 사용되고 있어 단순 대체 시 기능 제한이 발생할 수 있다.

- **가능한 대안**: `plyer` (단순 알림), `pync` (macOS 전용), `PyObjC`의 `NSUserNotification` / `UNUserNotificationCenter`

### 3. `ctypes.windll` 직접 호출

| 파일 | 사용 위치 | 용도 |
|---|---|---|
| `src/utils/admin.py` | `IsUserAnAdmin()`, `ShellExecuteW("runas", ...)` | 관리자 권한 확인 및 UAC 재시작 |
| `src/core/launcher.py` | `ShellExecuteW("open"/"runas", ...)` | 게임/앱 실행 |
| `homework_helper.pyw` | `IsUserAnAdmin()` | 실행 권한 상태 확인 |

`ctypes.windll` 자체가 macOS에 존재하지 않으므로 OS 분기 처리가 필요하다.

### 4. `.lnk` / `.url` 파일 처리 — `src/core/launcher.py` 전체

`launch_process()` 메서드가 Windows 전용 파일 형식과 실행 방식에 강하게 결합되어 있다.

- `.lnk` (Windows 바로가기) — macOS에는 `.app` 번들 / Alias 방식
- `.url` (인터넷 바로가기) — macOS에는 `.webloc` 방식
- `steam://`, `epic://` 프로토콜 URL — macOS에서도 존재하나 앱 경로 다름
- `os.startfile()` — Windows 전용 (macOS 불가)

macOS에서 게임 실행은 `open -a "Steam"` 또는 `subprocess.Popen(["open", url])` 방식으로 대체 가능.

### 5. Windows 환경 변수 하드코딩

| 환경 변수 | 사용 파일 | macOS 대안 |
|---|---|---|
| `APPDATA` | `admin.py`, `browser_cookie_extractor.py` | `~/Library/Application Support/` |
| `LOCALAPPDATA` | `lsh_installer.py` | `~/Library/Application Support/` |
| `USERPROFILE` | `browser_cookie_extractor.py` | `os.path.expanduser('~')` |
| `PROGRAMFILES`, `PROGRAMFILES(X86)` | `launcher.py` | `/Applications/` |
| `WINDIR`, `SYSTEMROOT` | `launcher.py` | `/System/` |
| `TEMP` | `launcher.py` | `tempfile.gettempdir()` (이미 크로스플랫폼) |

### 6. `subprocess` Windows 전용 플래그

**파일**: `src/utils/admin.py`, `src/utils/lsh_installer.py`

```python
subprocess.Popen(args, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
```

macOS/Linux에서는 `creationflags` 인자가 지원되지 않으므로 OS 분기 처리 필요.

### 7. `signal.SIGBREAK`

**파일**: `homework_helper.pyw`

Windows 전용 신호로 macOS에 존재하지 않음. `if os.name == 'nt':` 분기 내에서만 등록하도록 처리 필요 (이미 일부 처리되어 있음).

### 8. `homework_helper.spec` / `installer.iss` — 빌드 시스템

- `homework_helper.spec`: PyInstaller spec (Windows 전용 옵션 포함)
- `installer.iss`: Inno Setup (Windows 전용 설치 프로그램)
- macOS에서는 `py2app` 또는 PyInstaller macOS 옵션 + `create-dmg` 등으로 대체 가능

---

## 이미 크로스플랫폼인 부분 (변경 불필요)

| 파일/기능 | 비고 |
|---|---|
| `src/gui/` (PyQt6 전체) | Qt는 macOS 완전 지원 |
| `src/api/` (FastAPI + uvicorn) | 완전 크로스플랫폼 |
| `src/data/` (SQLAlchemy + SQLite) | 완전 크로스플랫폼 |
| `src/core/process_monitor.py` | `psutil` 크로스플랫폼 |
| `src/utils/launcher_utils.py` | `psutil` 크로스플랫폼 |
| `src/services/hoyolab.py` | 완전 크로스플랫폼 |
| `src/core/instance_manager.py` | `QSharedMemory` + `QLocalServer` macOS 지원 (`removeServer` fallback 존재) |
| `src/core/scheduler.py` | 크로스플랫폼 |
| `homework_helper.pyw`의 `get_app_data_dir()` | 이미 `os.name != 'nt'` 분기 처리됨 |
| `homework_helper.pyw`의 `is_server_running_pid_fallback()` | 이미 크로스플랫폼 fallback 존재 |
| `src/utils/browser_cookie_extractor.py`의 Firefox 추출 | Firefox 쿠키 경로만 수정하면 macOS 지원 가능 |

---

## 파일별 전환 작업 난이도

| 파일 | 난이도 | 주요 작업 |
|---|---|---|
| `src/utils/lsh_installer.py` | 🟢 쉬움 | `.exe` → 스크립트/`.app`, `LOCALAPPDATA` 경로, `creationflags` 분기 |
| `homework_helper.pyw` | 🟢 쉬움 | Windows signal 분기 정리, 환경변수 교체 |
| `src/gui/tray_manager.py` | 🟢 쉬움 | macOS는 트레이 아이콘 동작 방식이 약간 다름 (메뉴바 앱 스타일) |
| `src/utils/windows.py` | 🟡 중간 | LaunchAgent plist 방식 macOS 구현 추가 |
| `src/utils/admin.py` | 🟡 중간 | `ctypes.windll` → `os.getuid()` / AppleScript `do shell script with administrator privileges` |
| `src/core/notifier.py` | 🟡 중간 | `Windows-Toasts` → `plyer` 또는 `PyObjC` NSUserNotification |
| `src/core/launcher.py` | 🔴 어려움 | `.lnk`/`.url` macOS 대안, `os.startfile` 대체, 게임 런처 경로 macOS 매핑 |
| `src/utils/browser_cookie_extractor.py` | 🔴 어려움 | Chrome macOS Keychain API 연동 (`pyobjc-framework-Security`) |

---

## 전환 전략 제안

### 단계 1: 플랫폼 추상화 레이어 도입

`src/utils/platform_utils.py` 신규 생성 — OS별 구현을 단일 인터페이스로 추상화:

```
platform_utils.py
├── get_app_data_dir()          # APPDATA vs ~/Library/Application Support
├── get_autostart_status()      # 레지스트리 vs LaunchAgent plist
├── set_autostart(enable)       # 레지스트리 vs LaunchAgent plist
├── is_admin()                  # windll vs os.getuid()
├── run_as_admin()              # ShellExecuteW vs AppleScript/sudo
└── send_notification(...)      # Windows-Toasts vs plyer/PyObjC
```

### 단계 2: 의존성 정리

`requirements.txt`를 플랫폼별로 분리:

```
requirements-common.txt  # PyQt6, fastapi, psutil, genshin 등
requirements-windows.txt # pywin32, winshell, Windows-Toasts
requirements-macos.txt   # pyobjc-framework-Security, plyer 등
```

### 단계 3: 핵심 기능 macOS 구현

1. **알림**: `plyer` 통합 (Windows/macOS 단일 API) — Windows Toast 버튼 상호작용은 별도 처리
2. **자동 시작**: `~/Library/LaunchAgents/{bundle_id}.plist` 방식 구현
3. **게임 실행**: `open` 명령어 또는 `subprocess.Popen(["open", url])` 로 대체
4. **Chrome 쿠키**: macOS Keychain에서 AES 키 추출 후 동일 AES-GCM 복호화 로직 재사용 가능

### 단계 4: 빌드 파이프라인

- macOS: PyInstaller `--target-arch universal2` (Apple Silicon + Intel 동시 지원) + `create-dmg`
- GitHub Actions에 macOS 빌드 job 추가

---

## 참고: macOS Chrome 쿠키 복호화

Windows DPAPI와 달리 macOS Chrome은 **Keychain**에 암호화 키를 저장한다. 복호화 흐름은 유사하다:

1. Keychain에서 `Chrome Safe Storage` 키 추출 (`security find-generic-password` 또는 `pyobjc`)
2. PBKDF2로 AES 키 파생
3. AES-CBC로 쿠키 복호화

`browser_cookie_extractor.py`의 AES-GCM 복호화 로직 일부를 재활용할 수 있으나, 키 추출 방식과 암호화 모드(CBC vs GCM)가 다르므로 주의가 필요하다.
