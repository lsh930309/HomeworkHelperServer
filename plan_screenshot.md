# screenshot feature — implementation state

> last_updated: 2026-03-30
> branch: dev-20260318 (commit 2bcffb7)

---

## STATUS

| phase | scope | status |
|---|---|---|
| Phase 1 | 게임패드 트리거 + 캡처 + 사이드바 UI + 설정 | COMPLETE |
| Phase 1.5 | 진단 도구 실행 → Method A 확인 | COMPLETE |
| Phase 2 | OBS WebSocket 녹화 기능 | COMPLETE |
| Phase 2.5 | UI/UX 개선 (파일명/썸네일/버튼/순서) | COMPLETE |

---

## ARCHITECTURE

```text
src/screenshot/
  __init__.py              ← exports ScreenshotManager only
  manager.py               ← 중앙 컨트롤러: Method A 고정, game_name_provider
  trigger_dispatcher.py    ← 홀드 시간 기반 분기 (짧게=스크린샷, 길게=녹화토글)
  method_a.py              ← WH_KEYBOARD_LL hook (Win+Alt+PrtScn 가로채기)
  capture.py               ← 캡처 로직 (mss → GDI BitBlt fallback), 파일명 생성
src/recording/
  __init__.py              ← exports RecordingManager only
  manager.py               ← 상태 머신 (idle/recording/connecting/obs_offline), OBS 제어
  obs_client.py            ← obs-websocket 5.x 최소 클라이언트 (websocket-client)
  obs_config_reader.py     ← %APPDATA%\obs-studio 설정 자동 읽기
src/gui/
  main_window.py           ← ScreenshotManager + RecordingManager 수명주기
  sidebar/sidebar_widget.py  ← 스크린샷 섹션 + 녹화 섹션 (볼륨 → 스크린샷 → 녹화 순)
  sidebar_settings_dialog.py ← 스크린샷 + 녹화 설정 UI, [OBS에서 불러오기] 버튼
src/data/
  schemas.py / models.py / database.py / data_models.py
    ← screenshot_* 6개 + recording_*/obs_* 9개 필드, 마이그레이션 완료
```

---

## IMPLEMENTED DETAILS

### GlobalSettings fields

**스크린샷 (schemas.py)**
```python
screenshot_enabled: bool = True
screenshot_save_dir: str = ""              # 비어있으면 ~/Pictures/GameCaptures
screenshot_gamepad_trigger: bool = True
screenshot_disable_gamebar: bool = False
screenshot_capture_mode: str = "fullscreen"   # or "game_window"
screenshot_gamepad_button_index: int = -1     # Method C용, 진단 후 설정
```

**녹화/OBS (schemas.py)**
```python
recording_enabled: bool = False
obs_host: str = "localhost"
obs_port: int = 4455
obs_password: str = ""
obs_exe_path: str = ""
obs_auto_launch: bool = False
obs_launch_hidden: bool = True
obs_watch_output_dir: bool = True
recording_hold_threshold_ms: int = 800
```

### 파일명 형식 (capture.py)
```text
{game_name}_{yyyy-mm-dd} {오전|오후} {H}_{MM}_{SS}.png
예) Minecraft_2026-03-30 오후 2_34_56.png
```
- game_name: 포커스된 등록 게임 프로세스명 (main_window._get_screenshot_game_name())
- 등록 게임 미확인 시 "capture" 폴백
- Windows 금지 문자 자동 제거 (_sanitize_filename), 최대 60자

### 버튼 입력 분기 (trigger_dispatcher.py)
```text
짧게 누름 (< 500ms, release 시):  스크린샷 촬영
홀드 800ms+:                      녹화 토글 즉시 발화
500ms ~ 800ms:                    무시 (오동작 방지)
```

### ScreenshotManager public API (manager.py)
```python
ScreenshotManager(get_target_hwnd: Callable[[], Optional[int]])
.start() / .stop()
.capture_now() -> Optional[str]
.set_save_dir(path: str)
.set_capture_mode(mode: str)          # "fullscreen" or "game_window"
.set_on_captured(fn: Callable[[str], None])
.set_on_long_press(fn: Callable[[], None])   # 녹화 토글 콜백
.set_game_name_provider(fn: Callable[[], str])  # 파일명용 게임명 조회
```

> **Method A 고정**: Gamesir G7 Pro는 `ROOT#FEIZHI_VIRTUAL_KEYBOARD` 가상 HID 키보드 드라이버를
> 통해 Win+Alt+PrtScn 이벤트를 주입함이 진단으로 확인됨. Method B/C/진단 도구 제거.

### RecordingManager public API (recording/manager.py)
```python
RecordingManager()
.apply_settings(settings: GlobalSettings)
.on_recording_toggle()         # TriggerDispatcher long_press에 연결
.start_recording() / .stop_recording()
.get_state() -> "idle"|"recording"|"connecting"|"obs_offline"
.get_elapsed_sec() -> int
.set_on_state_changed(fn)
.shutdown()
```

### OBSClient (recording/obs_client.py)
- obs-websocket 5.x 프로토콜, websocket-client 패키지 사용
- 인증: SHA256(password+salt)→base64→SHA256(+challenge)→base64
- 요청: StartRecord, StopRecord, GetRecordStatus
- 이벤트: RecordStateChanged
- reconnect: 연결 끊길 경우 재시도 루프

### obs_config_reader (recording/obs_config_reader.py)
```python
read_obs_config() -> {port, password, output_dir, exe_path}
# 소스: %APPDATA%\obs-studio\plugin_config\obs-websocket\config.json
#       %APPDATA%\obs-studio\global.ini → CurrentProfile
#       %APPDATA%\obs-studio\basic\profiles\<profile>\basic.ini
#       HKLM\SOFTWARE\OBS Studio (레지스트리)
```

### main_window.py integration
- `_get_screenshot_target_hwnd()`: 포커스된 등록 게임 창 HWND 반환
- `_get_screenshot_game_name()`: 포커스된 등록 게임 프로세스명 반환
- `_on_screenshot_captured(path)`: sidebar.on_screenshot_captured() 호출 (_is_shown 가드 없음)
- `_set_gamebar_capture(enabled)`: HKCU\...\GameDVR\AppCaptureEnabled 레지스트리 제어
- `_restore_gamebar_setting()`: closeEvent 시 원복
- `_on_recording_state_changed(state)`: sidebar.on_recording_state_changed() 호출
- RecordingManager.shutdown(): closeEvent 시 호출

### sidebar layout (sidebar_widget.py)
섹션 순서: 클럭 → 실행중 게임 클러스터 → **볼륨** → **스크린샷** → **녹화**

**스크린샷 섹션**
- "지금 촬영" 버튼: 닫기 버튼 스타일 (28px, rgba(255,255,255,10) 배경)
- 썸네일 그리드: 3열 × 최대 3행, 마지막 셀 = "+NNN" 폴더 단축
- on_screenshot_captured(): QMetaObject.invokeMethod(QueuedConnection)으로 스레드 안전 갱신

**녹화 섹션**
- 상태 레이블: OBS 오프라인 / 연결 중 / OBS 대기 중 / ● REC HH:MM:SS
- "■ 녹화 종료" 버튼: 게임 종료 버튼 스타일 (28px, 빨간 계열), 녹화 중일 때만 표시
- 1초 타이머로 경과 시간 갱신

---

---

## KNOWN ISSUES / RISKS

| 항목 | 내용 | 조치 |
|---|---|---|
| mss 블랙스크린 | DX11/DX12 일부 게임에서 검은 화면 가능 | DXGI Desktop Duplication으로 교체 고려 |
| winrt 미설치 | Method C 시도 시 ImportError | requirements.txt 추가됨, pip install 필요 |
| websocket-client 미설치 | OBS 연동 시 ImportError | requirements.txt 추가됨, pip install 필요 |
| Game Bar 복원 실패 | 강제종료 시 _gamebar_original_value 소실 | 레지스트리 별도 백업 키 저장 미구현 |
| 게임명 미확인 | 게임 미실행/포커스 없으면 파일명이 "capture_..." | 현재 동작 의도적 폴백 |

---

## DEFERRED

### 녹화 일시정지
- 홀드 3단계(짧게/중간/길게) 또는 별도 버튼 할당 방식 미결
- 현재: start/stop only

### 녹화 파일 사이드바 표시
- obs_watch_output_dir 필드 준비됨, 파일 감시 로직 미구현
- OBS 출력 폴더 감시 → 완료 파일 썸네일 표시

### mss → DXGI 교체
- mss 블랙스크린 발생 시 DXGI Desktop Duplication API로 교체

---

## FILE INDEX

```text
[스크린샷 코어]
src/screenshot/manager.py              ← ScreenshotManager, set_game_name_provider (Method A 고정)
src/screenshot/trigger_dispatcher.py   ← 홀드 시간 분기 로직
src/screenshot/method_a.py             ← WH_KEYBOARD_LL (Win+Alt+PrtScn 가로채기)
src/screenshot/capture.py              ← 캡처 + 파일명 생성 (_build_save_path)

[녹화 코어]
src/recording/manager.py
src/recording/obs_client.py
src/recording/obs_config_reader.py

[GUI]
src/gui/main_window.py                 ← _get_screenshot_game_name, 양쪽 manager 수명주기
src/gui/sidebar/sidebar_widget.py      ← 섹션 순서, 버튼 스타일, QueuedConnection 갱신
src/gui/sidebar_settings_dialog.py     ← 스크린샷+녹화 설정, [OBS에서 불러오기]

[데이터]
src/data/schemas.py                    ← screenshot_* + recording_*/obs_* 필드
src/data/models.py / database.py / data_models.py

[진단]
tools/diagnose_gamepad_screenshot.py
```
