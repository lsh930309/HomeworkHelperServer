# screenshot feature — implementation state

> last_updated: 2026-03-30
> branch: dev-20260318 (commit bef5a15)

---

## STATUS

| phase | scope | status |
|---|---|---|
| Phase 1 | 게임패드 트리거 + 캡처 + 사이드바 UI + 설정 | COMPLETE (committed) |
| Phase 1.5 | 진단 도구 실행 → _method.txt 갱신 | PENDING (user action needed) |
| Phase 2 | 녹화 (DXGI+WASAPI+ffmpeg or OBS WebSocket) | DEFERRED |

---

## ARCHITECTURE

```
tools/diagnose_gamepad_screenshot.py   ← 1회성 진단, _method.txt 기록
src/screenshot/
  __init__.py         ← exports ScreenshotManager only
  manager.py          ← 중앙 컨트롤러: _method.txt 읽어 impl 선택
  method_a.py         ← WH_KEYBOARD_LL hook (Win+Alt+PrtScn 가로채기)
  method_c.py         ← WinRT RawGameController polling (Xbox 라이센스 패드)
  capture.py          ← 실제 캡처 로직 (mss → GDI BitBlt fallback)
  _method.txt         ← "A" or "C:<button_index>" (gitignore됨, 진단 후 생성)
src/gui/
  main_window.py      ← ScreenshotManager 수명주기, Game Bar 레지스트리 제어
  sidebar/sidebar_widget.py  ← 사이드바 스크린샷 섹션 + 썸네일 그리드
  sidebar_settings_dialog.py ← 저장경로/트리거/GameBar/캡처모드 설정 UI
src/data/
  schemas.py          ← GlobalSettings에 screenshot_* 6개 필드
  models.py / database.py / data_models.py  ← DB 컬럼 + 마이그레이션 완료
```

---

## IMPLEMENTED DETAILS

### GlobalSettings fields (schemas.py)
```python
screenshot_enabled: bool = True
screenshot_save_dir: str = ""              # 비어있으면 ~/Pictures/GameCaptures
screenshot_gamepad_trigger: bool = True
screenshot_disable_gamebar: bool = False
screenshot_capture_mode: str = "fullscreen"   # or "game_window"
screenshot_gamepad_button_index: int = -1     # Method C용, 진단 후 설정
```

### _method.txt format
- `"A"` → method_a.py (WH_KEYBOARD_LL hook)
- `"C:3"` → method_c.py with button_index=3 (숫자는 진단 결과에 따라 다름)
- 파일 없음 → manager.py가 "A"로 fallback

### ScreenshotManager public API (manager.py)
```python
ScreenshotManager(get_target_hwnd: Callable[[], Optional[int]])
.start() / .stop()
.capture_now()
.set_save_dir(path: str)
.set_capture_mode(mode: str)  # "fullscreen" or "game_window"
.set_on_captured(callback: Callable[[str], None])
```

### capture.py key functions
```python
take_screenshot(save_dir: str) -> Optional[str]
take_screenshot_window(hwnd: int, save_dir: str) -> Optional[str]
# window 캡처: GetClientRect + ClientToScreen → mss region or GDI BitBlt
# filename: capture_YYYYMMDD_HHMMSS_mmm.png
```

### method_a.py
- SetWindowsHookExW(WH_KEYBOARD_LL) on daemon thread with message loop
- Win+Alt+PrtScn 감지 → return 1 (이벤트 삭제) → callback 호출
- stop(): PostThreadMessage(WM_QUIT)

### method_c.py
- winrt.windows.gaming.input.RawGameController 50ms 폴링
- edge detection: curr[idx] and not prev[idx]
- discover_button_index(timeout_sec=10.0) → 진단 도구에서 사용

### main_window.py integration
- _start_screenshot_manager(): app 시작 시 enabled 확인 후 start()
- _get_screenshot_target_hwnd(): 마지막 포커스된 등록 게임 창 HWND 반환
- _on_screenshot_captured(path): sidebar_widget.on_screenshot_captured() 호출
- _set_gamebar_capture(enabled): HKCU\...\GameDVR\AppCaptureEnabled 레지스트리 제어
- _restore_gamebar_setting(): closeEvent 시 원복
- _gamebar_original_value: Optional[int] (최초 비활성화 시점에 원본값 저장)

### sidebar screenshot section (sidebar_widget.py)
- _build_screenshot_section(): "스크린샷" 그룹박스, "지금 촬영" 버튼
- _refresh_screenshot_thumbnails(): screenshot_save_dir에서 PNG/BMP 최대 8개 로드
- 썸네일 그리드: 3열 × 최대 3행 = 9셀, 마지막 셀 = "+NNN" 폴더 단축 버튼
- 각 썸네일 클릭 → QDesktopServices.openUrl(파일경로)
- on_screenshot_captured(path): 새 캡처 후 썸네일 갱신 슬롯

---

## PENDING: Phase 1.5 — 진단 실행

### 목적
Gamesir G7 Pro 공유 버튼이 Method A(WH_KEYBOARD_LL)로 잡히는지, Method C(WinRT)가 필요한지 확인.
3가지 진단 단계 모두 이전 세션에서 실패했음 → WinRT Method C 추가 후 재진단 필요.

### 실행 방법
```bash
python tools/diagnose_gamepad_screenshot.py
```
게임패드 연결 상태에서 실행. 각 단계마다 프롬프트에 따라 공유 버튼을 누름.

### 예상 결과
| 시나리오 | _method.txt 내용 | 비고 |
|---|---|---|
| Method A 성공 | `A` | WH_KEYBOARD_LL이 Win+Alt+PrtScn을 잡음 |
| Method C 성공 | `C:<idx>` | WinRT가 버튼 인식, manager 자동 선택 |
| 둘 다 실패 | `A` (fallback) | 추가 조사 필요 |

### 진단 후 후속 작업
1. `_method.txt` 내용 확인
2. Method C 결과인 경우: 설정 다이얼로그에서 "감지된 버튼 인덱스" 읽기 전용 필드에 표시됨
3. 앱 실행 후 실제 게임에서 공유 버튼 눌러 캡처 동작 확인
4. mss 블랙스크린 여부 확인 (DX11/12 게임에서)

---

## KNOWN ISSUES / RISKS

| 항목 | 내용 | 조치 |
|---|---|---|
| mss 블랙스크린 | DX11/DX12 일부 게임에서 검은 화면 가능 | 발생 시 DXGI Desktop Duplication으로 교체 (Phase 2) |
| winrt 미설치 | Method C 시도 시 ImportError | requirements.txt 추가됨, .venv 설치 필요 |
| Game Bar 복원 실패 | 강제종료 시 _gamebar_original_value 소실 | 레지스트리 별도 백업 키 저장 미구현 |
| 다중 게임 실행 | _get_screenshot_target_hwnd()가 마지막 포커스 창 반환 | 동작 확인 필요 |

---

## DEFERRED: Phase 2

### 녹화 기능
- 방법 후보: DXGI+WASAPI+ffmpeg pipe (self-hosted), OBS WebSocket 연동
- 미결 사항: 인코더 선택, 세그먼트 저장 방식, 진행 표시 UI

### OBS WebSocket 연동
- OBS → 앱: 녹화/스크린샷 이벤트 수신 → 사이드바 갱신
- 앱 → OBS: 게임패드 트리거로 OBS 제어
- 미결 사항: OBS 선택적 설치, 포트/비밀번호 설정 UI

---

## FILE INDEX

```
src/screenshot/manager.py
src/screenshot/method_a.py
src/screenshot/method_c.py
src/screenshot/capture.py
src/gui/main_window.py              ← _start_screenshot_manager, _on_screenshot_captured
src/gui/sidebar/sidebar_widget.py   ← on_screenshot_captured, _build_screenshot_section
src/gui/sidebar_settings_dialog.py  ← screenshot settings group
src/data/schemas.py                 ← screenshot_* fields
tools/diagnose_gamepad_screenshot.py
```
