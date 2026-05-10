# 신규 React/Vite/Tauri GUI 기술 검토 및 개선 제안 보고서

작성일: 2026-05-10  
범위: 신규 GUI의 창 테두리, 창 이동, 사이드바, 백엔드 다중 실행/종료, 웹뷰 컨텍스트 메뉴, 로딩 지연 원인 분석과 개선안

## 1. 결론 요약

| 항목 | 판단 | 신뢰도 |
| --- | --- | --- |
| 창 테두리 | 현재는 frameless 창 위에 CSS `border/radius/shadow`를 얹은 구조다. 더 깔끔하게 하려면 Tauri main window를 transparent로 두고 외곽 wrapper만 그리거나, 현재 1px 외곽선을 더 약하게 조정하는 방식이 적합하다. | 높음 |
| 메인 창 이동 불가 | 코드에는 `data-tauri-drag-region`이 있으나 수동 `startDragging()` 구현과 CSS `app-region` 보강이 없다. 또한 `data-tauri-drag-region="false"`는 “속성 존재 여부” 기반 구현에서 오히려 drag region으로 해석될 위험이 있다. | 중간~높음 |
| 사이드바 자동 닫힘 | 신규 사이드바는 PyQt처럼 전역 커서 폴링/외부 클릭 감지가 아니라 React `onMouseLeave`와 타이머에 의존한다. `autoHideMs=0`도 즉시 숨김이 아니라 숨김 비활성처럼 동작한다. | 높음 |
| 서랍 손잡이 항상 노출 | 의도된 구조다. 닫힘 상태에서도 Tauri sidebar window를 12px 보이는 위치에 배치하고 `.drawer-handle`을 항상 렌더링한다. | 높음 |
| 사이드바 테두리 | CSS `.drawer-panel`의 `border-left`가 직접 원인이다. 제거 가능하다. | 높음 |
| 신규 GUI 빌드/업데이트 후 백엔드 여러 개 | 신규 GUI에는 Python backend sidecar 1개가 필요하지만 여러 개는 필수가 아니다. 중복은 구버전/기존 실행 경로/시작프로그램/기존 backend adoption 부재/강제 종료 시 cleanup 누락에서 발생할 수 있다. | 중간 |
| 앱 종료 시 backend 미종료 | X 버튼은 종료가 아니라 hide-to-tray다. 이 상태에서 backend가 남는 것은 의도된 동작이다. 실제 tray “종료” 후에도 남으면 shell이 소유하지 않은 기존 backend를 사용했거나 강제 종료/업데이트 경로가 cleanup을 우회한 것이다. | 높음 |
| 빈 배경 우클릭 웹 메뉴 | React 앱에 전역 `contextmenu` 방지가 없다. 특정 요소만 커스텀 메뉴를 처리하므로 나머지 배경은 웹뷰 기본 메뉴가 뜬다. | 높음 |
| 로딩 지연 | Tauri shell이 Python backend 준비를 최대 10초 기다리고, Python backend가 DB 백업/마이그레이션/무결성 검사/WAL checkpoint/static mount를 수행한 뒤, React가 `/api/gui/main-state`를 불러오는 순서라 느려질 수 있다. | 높음 |

## 2. 필수 근거

프로젝트 마이그레이션 계약상 GUI/런타임/패키징을 다루기 때문에 다음 문서를 확인했다.

- `docs/migration-feature-inventory.md`
- `tests/migration/feature_matrix.json`
- `docs/migration-smoke-checklist.md`

관련 현재 상태:

- `APP-001`, `APP-002`, `SIDEBAR-001`은 신규 GUI에서 `partial`.
- `BUILD-001`은 `complete`이나 Windows installer/update smoke는 별도 확인 대상.
- `SIDEBAR-001`은 high-risk이며 Windows runtime smoke가 필요하다.

Tauri 공식 문서도 확인했다.

- Tauri v2 window customization 문서: frameless 창은 `decorations: false`, `data-tauri-drag-region`, `startDragging()`, `app-region: drag` 방식으로 커스텀 titlebar drag를 구현할 수 있다.
- Tauri single-instance plugin 문서: `tauri_plugin_single_instance::init()`로 두 번째 실행을 기존 인스턴스로 전달한다.
- Tauri shell plugin 문서: child/sidecar process는 spawn 후 필요 시 kill할 수 있다.

## 3. 창 테두리를 더 깔끔하게 처리하는 방안

### 3.1 현재 구조

근거:

- `src-tauri/tauri.conf.json`의 main window는 `decorations: false`, `backgroundColor: "#0b1120"`이다.
- `src/gui/new_gui/frontend/src/style.css`의 `.shell`은 `border: 1px solid var(--hh-line)`, `border-radius: 20px`, 큰 `box-shadow`를 갖는다.
- `body`도 `background: var(--hh-bg)`를 가진다.

즉 현재 신규 GUI는 OS 테두리를 제거하고, 웹뷰 내부의 `.shell`이 테두리/둥근 모서리/그림자를 그리는 구조다.

### 3.2 문제 가능성

1. Tauri window 자체 배경과 `.shell` 배경이 모두 어두워서 외곽 경계가 이중으로 보일 수 있다.
2. main window가 transparent가 아니므로 둥근 모서리 바깥의 웹뷰 배경이 사각형 느낌을 남길 수 있다.
3. `.shell`의 1px border + 큰 shadow가 Windows DWM 그림자와 합쳐지면 테두리가 “두껍게” 느껴질 수 있다.

### 3.3 개선안

#### 개선안 A: 투명 Tauri window + 단일 shell chrome

- `tauri.conf.json` main window에 `transparent: true`를 추가한다.
- `body`는 `background: transparent`로 둔다.
- `.shell`만 실제 배경, 둥근 모서리, 아주 약한 outline을 그린다.

장점:

- 가장 깔끔한 frameless 앱 외곽을 만들 수 있다.

주의:

- Windows 투명 창/그림자/클릭 영역 smoke가 필요하다.
- 성능과 hit-test 문제가 생기면 fallback이 필요하다.

#### 개선안 B: 현재 opaque window 유지 + border 약화

- `.shell`의 `border`를 제거하거나 `box-shadow: inset 0 0 0 1px rgba(...)`로 대체한다.
- 외곽 shadow를 줄인다.
- `body`와 `.shell`의 색 차이를 줄인다.

장점:

- 위험도가 낮고 구현이 쉽다.

권장 CSS 방향:

```css
.shell {
  border: 0;
  box-shadow:
    inset 0 0 0 1px rgba(148, 163, 184, 0.10),
    0 18px 46px rgba(0, 0, 0, 0.36);
}
```

#### 개선안 C: 창 chrome wrapper 분리

- `.shell`은 콘텐츠 레이아웃만 담당하게 하고, `.app-chrome` wrapper가 border/radius/shadow를 담당한다.
- 드래그 영역과 콘텐츠 영역의 hit-test를 더 명확히 나눌 수 있다.

## 4. 메인 창 위치 이동 기능이 작동하지 않는 원인 분석

### 4.1 현재 코드 증거

- `src-tauri/tauri.conf.json`: main/settings/editor window 모두 `decorations: false`.
- `src/gui/new_gui/frontend/src/App.tsx`
  - main header: `<header className="topbar" data-tauri-drag-region>`
  - popup header: `<header className="popup-head" data-tauri-drag-region>`
  - modal header: `<header className="modal-head" data-tauri-drag-region>`
  - controls/actions: `data-tauri-drag-region="false"`
- `src/gui/new_gui/frontend/src/App.tsx`의 `useWindowPlacement`는 이동 이벤트를 저장/복원하지만, 이동을 시작하는 로직은 아니다.
- `src/gui/new_gui/frontend/src/style.css`는 cursor만 `grab/grabbing`으로 바꾸며 `app-region: drag` 또는 `startDragging()` 호출은 없다.

### 4.2 가장 가능성 높은 원인

#### 원인 1: `data-tauri-drag-region`만으로 충분하지 않은 환경/버전 조합

Tauri 문서는 `data-tauri-drag-region` 또는 수동 `appWindow.startDragging()` 방식을 안내한다. 현재 코드는 attribute에만 의존한다. 실제 Windows WebView2/Tauri 빌드에서 attribute 처리가 기대대로 주입되지 않거나, 특정 요소 hit-test가 막히면 사용자는 드래그할 수 없다.

#### 원인 2: `data-tauri-drag-region="false"` 사용 방식

현재 controls/actions/button에 `data-tauri-drag-region="false"`가 들어가 있다. 만약 Tauri/wry 쪽이 값이 아니라 “속성 존재 여부”로 drag region을 판단하면, 이 요소도 drag region으로 해석될 수 있다. 그러면 버튼 조작과 드래그 영역이 충돌할 수 있다.

정적 테스트(`tests/test_dashboard_static_build.py`)는 이 문자열의 존재만 확인하므로, 실제 런타임 동작까지 보장하지 않는다.

#### 원인 3: 명시적 drag handler 부재

`useWindowPlacement`는 이동 후 위치 저장만 한다. 사용자가 마우스를 눌렀을 때 `getCurrentWindow().startDragging()`을 호출하는 코드가 없다.

### 4.3 권장 해결 방향

가장 안정적인 방식은 **수동 drag handler + interactive element 필터**다.

구상:

```tsx
function isInteractive(target: EventTarget | null) {
  return target instanceof HTMLElement
    && Boolean(target.closest('button, input, select, textarea, a, [data-no-drag="true"]'));
}

function useHeaderDrag(enabled: boolean) {
  return React.useCallback((event: React.MouseEvent) => {
    if (!enabled) return;
    if (event.button !== 0) return;
    if (isInteractive(event.target)) return;
    if (event.detail === 2) return;
    getCurrentWindow().startDragging().catch(() => undefined);
  }, [enabled]);
}
```

추가 CSS 보강:

```css
[data-tauri-drag-region] {
  app-region: drag;
}

button,
input,
select,
textarea,
a,
[data-no-drag="true"] {
  app-region: no-drag;
}
```

주의:

- `data-tauri-drag-region="false"` 대신 `data-no-drag="true"`처럼 앱 자체 속성으로 바꾸는 것이 더 안전하다.
- Windows smoke checklist의 `APP-001: 새 GUI frameless 메인/설정/편집 창을 header drag로 이동` 항목을 실제로 확인해야 한다.

## 5. 사이드바가 자동으로 닫히지 않는 이유

### 5.1 현재 신규 GUI 구조

근거:

- `src-tauri/tauri.conf.json`에는 별도 `sidebar` window가 있고 `transparent: true`, `alwaysOnTop: true`, `skipTaskbar: true`, `decorations: false`다.
- `src/gui/new_gui/frontend/src/App.tsx`의 `SidebarApp`은 `open`, `pinned`, `hoveringControls` 상태를 사용한다.
- `useSidebarDrawerWindow(settings, open || pinned, isTauri)`는 닫힘 상태에서도 window 위치를 우측 edge에 맞추고, visible width를 handle 폭인 12px로 계산한다.
- `.drawer-handle`은 항상 렌더링된다.

### 5.2 자동 닫힘이 기존 PyQt와 다른 이유

기존 PyQt 사이드바:

- `EdgeTriggerWindow`가 화면 우측 투명 트리거 창에서 커서를 폴링한다.
- `SidebarWidget`은 `_cursor_poll_timer`로 커서가 사이드바 밖에 있는지 계속 검사한다.
- 밖이면 auto-hide timer를 재시작하거나 즉시 `slide_out()`한다.
- 외부 좌클릭도 감지해 닫는다.

신규 React 사이드바:

- `onMouseEnter={reveal}`로 열림.
- `onMouseLeave={scheduleHide}`로 숨김 예약.
- `open && autoHideMs > 0`일 때만 timer가 `setOpen(false)`를 호출.
- `pinned` 또는 `hoveringControls`이면 타이머를 중지.

따라서 다음 경우에 “자동으로 닫히지 않는다”고 느낄 수 있다.

1. `autoHideMs`가 0이면 현재 코드상 즉시 숨김이 아니라 숨김 예약 자체가 동작하지 않는다.
2. 커서가 패널 안 또는 볼륨 카드 위에 있으면 `hoveringControls` 때문에 타이머가 중지된다.
3. PyQt처럼 전역 커서 위치/외부 클릭을 폴링하지 않으므로, WebView/Tauri 경계에서 `mouseleave`가 누락되면 닫힘 트리거가 약하다.
4. `pinned`가 켜져 있으면 자동 숨김은 의도적으로 일시정지된다.

### 5.3 개선안

1. `autoHideMs === 0`을 “즉시 닫기”로 해석할지 “자동 숨김 끔”으로 해석할지 명확히 분리한다.
   - 예: `sidebar_auto_hide_ms=0`은 PyQt 설명처럼 즉시 숨김.
   - 자동 숨김 끔은 별도 boolean `sidebar_auto_hide_enabled`로 분리.
2. PyQt parity를 원하면 Tauri/Rust에서 커서 위치 polling 또는 global mouse hook에 가까운 native helper를 둔다.
3. React 레벨에서는 `window.blur`, `pointerleave`, `visibilitychange`, `Escape`, panel outside click을 모두 닫힘 후보로 묶는다.
4. timer 상태를 footer에 “자동숨김 일시정지/고정됨/즉시 닫힘/3초 후 닫힘”처럼 명확히 보여준다.

## 6. 서랍 손잡이가 항상 노출되는 이유

### 6.1 직접 원인

현재 신규 사이드바는 닫힘 상태가 “완전 숨김”이 아니라 “peek mode”다.

근거:

- `SIDEBAR_HANDLE_WIDTH = 12`
- 닫힘 상태에서 `visibleWidth = SIDEBAR_HANDLE_WIDTH`
- sidebar window 위치를 `screen.right - 12px`로 옮긴다.
- JSX에서 `.drawer-handle` button은 항상 렌더링된다.
- CSS `.drawer-handle`은 `width: 12px`, `opacity: 0.28`이다.

즉 손잡이 상시 노출은 버그라기보다, edge trigger를 “투명 1~2px 감지창” 대신 “얇은 UI 손잡이”로 표현한 설계다.

### 6.2 기존 PyQt와의 차이

기존 PyQt는 사용자가 항상 보는 손잡이가 아니라, 투명 `EdgeTriggerWindow`가 우측 엣지 진입을 감지한다. 신규 GUI는 사용자에게 보이는 버튼형 손잡이를 둔다.

### 6.3 개선 선택지

1. **현재 설계 유지**
   - 장점: 사용자가 열 수 있는 위치를 즉시 알 수 있다.
   - 단점: 항상 떠 있는 요소가 거슬릴 수 있다.
2. **완전 숨김 모드 추가**
   - 닫힘 상태에서는 `win.hide()`하고, 별도 Tauri/Rust edge trigger 또는 단축키/트레이 메뉴로 연다.
3. **초저시인성 손잡이**
   - 기본 opacity를 0.08 이하로 줄이고 hover 시만 0.8 이상.
   - `pointer-events`는 유지.
4. **게임 실행 중에만 손잡이 표시**
   - active process가 없으면 sidebar window를 숨기고, 게임 실행 중에만 peek.

## 7. 사이드바 테두리를 없앨 수 있는지

가능하다.

직접 원인:

```css
.drawer-panel {
  border-left: 1px solid rgba(147, 197, 253, 0.24);
}
```

제거안:

```css
.drawer-panel {
  border-left: 0;
  box-shadow: -18px 0 42px rgba(0, 0, 0, 0.36);
}
```

더 깔끔한 대안:

```css
.drawer-panel {
  border-left: 0;
  background:
    linear-gradient(90deg, rgba(96, 165, 250, 0.08), transparent 18px),
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.20), transparent 32%),
    linear-gradient(160deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.94));
}
```

주의:

- 카드 내부의 `.drawer-card`, `.drawer-chip`, `.media-thumb`에도 border가 있으므로 “전체적으로 테두리가 많다”는 인상을 줄이려면 이들 border도 opacity를 낮춰야 한다.

## 8. 신규 GUI 빌드/업데이트 후 백엔드가 여러 개 실행되는 원인

### 8.1 현재 구조

신규 GUI 빌드 모드에서는 다음이 설치 폴더에 함께 존재한다.

- `homework_helper_gui.exe`: Tauri/React shell
- `homework_helper.exe`: Python FastAPI backend sidecar 겸 기존 PyQt entrypoint

Tauri shell은 시작 시:

1. `GET /api/gui/health`로 기존 backend가 준비됐는지 확인한다.
2. 준비되지 않았으면 설치 폴더의 `homework_helper.exe --run-server`를 실행한다.
3. spawn한 child는 `PackagedBackend`에 저장한다.
4. `PackagedBackend.Drop`에서 child를 `kill()`/`wait()`한다.

Python backend는:

- `--run-server`일 때 `run_server_main()`으로 uvicorn을 실행한다.
- Windows Named Mutex `Local\HomeworkHelperDBServerMutex`와 PID file을 사용해 중복을 막으려 한다.

### 8.2 “여러 개”가 필수인가?

아니다.

- 신규 GUI가 DB를 직접 열지 않기 때문에 **backend 1개는 필수**다.
- 하지만 같은 AppData DB를 대상으로 backend가 여러 개 떠 있는 것은 필수가 아니며, 오히려 포트 충돌/DB lock/업데이트 실패의 원인이 될 수 있다.

### 8.3 가능한 원인

#### 원인 A: 신규 GUI가 기존 backend를 “사용”하지만 “소유”하지는 않음

`spawn_packaged_backend_if_needed()`는 `backend_is_ready()`가 true이면 child를 spawn하지 않고 `None`을 반환한다. 이 경우 Tauri shell은 기존 backend를 사용하지만 그 backend를 종료할 권한/핸들을 갖고 있지 않다.

결과:

- 기존 backend가 살아 있으면 신규 GUI는 그 backend를 그냥 사용한다.
- 앱 종료 시 Tauri가 죽일 수 있는 child가 없으므로 기존 backend는 남을 수 있다.

#### 원인 B: X 버튼은 종료가 아니라 숨김

`src-tauri/src/lib.rs`는 모든 window close request를 막고 `window.hide()`만 수행한다.

따라서 사용자가 X를 누르면:

- shell은 종료되지 않는다.
- tray 앱 상태가 유지된다.
- backend도 계속 필요하므로 남는다.

이 경우는 정상 동작이다. 실제 종료는 tray 메뉴의 `종료`여야 한다.

#### 원인 C: 업데이트/설치 경로가 기존 backend를 완전히 종료하지 못함

`installer.iss`는 설치 전 `taskkill /F /IM homework_helper.exe`와 `taskkill /F /IM homework_helper_gui.exe`를 호출한다.

위험 지점:

- 강제 종료는 graceful shutdown handler를 우회할 수 있다.
- PID 파일/Mutex/port 상태가 순간적으로 불일치할 수 있다.
- 이전 버전 backend가 `/api/gui/health`를 제공하지 않으면 readiness 판단이 실패한다.

#### 원인 D: 기존 시작프로그램/예약 작업/핀 고정 아이콘이 `homework_helper.exe`를 계속 실행

`installer.iss`의 예약 작업 등록은 `homework_helper.exe`를 기준으로 한다. `src/utils/windows.py`의 시작프로그램 바로가기 생성도 현재 실행 경로를 기준으로 한다.

신규 GUI 모드에서 사용자가 새 바로가기 대신 기존 pinned shortcut, 시작프로그램, 관리자 예약 작업을 통해 `homework_helper.exe`를 실행하면 PyQt entrypoint가 API 서버를 별도로 시작하려고 한다.

결과:

- `homework_helper_gui.exe`가 띄운 sidecar backend
- 기존 `homework_helper.exe` 경로로 시작된 PyQt/서버

가 혼재할 수 있다.

#### 원인 E: PID fallback 또는 signal 종료 실패

Windows에서는 Named Mutex가 핵심 방어선이다. 하지만 pywin32 부재, PID 파일 stale, `os.kill(SIGTERM)` 실패 등이 있으면 기존 서버를 제대로 종료하지 못하고 새 서버 시작을 시도할 수 있다.

### 8.4 개선안

1. **backend 전용 실행 파일명 분리**
   - 예: `homework_helper_backend.exe`
   - PyQt entrypoint와 backend sidecar를 분리하면 작업 관리자/installer/taskkill/shortcut 혼동이 줄어든다.
2. **신규 GUI 모드의 모든 자동 실행 경로를 `homework_helper_gui.exe`로 갱신**
   - 시작프로그램 shortcut
   - 관리자 예약 작업
   - installer run entry
   - desktop/start menu shortcut
3. **기존 backend adoption 정책 명시**
   - 기존 backend가 ready이면 사용만 할지, 종료까지 관리할지 정책을 정한다.
   - “내가 띄운 backend만 종료”가 안전하지만, 사용자에게 남는 프로세스처럼 보일 수 있다.
4. **backend health에 버전/모드/owner_pid 추가**
   - `/api/gui/health`가 `{ pid, version, started_by, owner_pid }`를 반환하면 신규 GUI가 stale/구버전 backend를 구분할 수 있다.
5. **graceful shutdown endpoint 또는 IPC**
   - 설치/업데이트 전에는 `taskkill /F`보다 backend shutdown API 또는 named event로 우아하게 종료한다.
6. **Windows smoke 추가/강화**
   - new GUI 설치 후 작업 관리자에 backend가 정확히 1개인지 확인.
   - tray 종료 후 backend가 사라지는지 확인.
   - X 버튼 후에는 shell/backend가 남는 것이 의도인지 UI 문구로 확인.

## 9. backend가 앱 종료 시 함께 종료되지 않는 원인

### 9.1 정상인 경우

다음은 정상이다.

- 사용자가 main window X 버튼을 누름.
- Tauri close event가 prevent_close 후 hide.
- tray에는 앱이 남음.
- backend도 계속 남음.

이유: tray에서 다시 열 때 API가 필요하기 때문이다.

### 9.2 문제가 되는 경우

다음은 문제다.

- tray 메뉴 `종료`를 눌렀다.
- `homework_helper_gui.exe`가 종료됐다.
- 그런데 `homework_helper.exe --run-server`가 계속 남아 있다.

가능한 원인:

1. Tauri shell이 직접 spawn한 child가 아니라 기존 backend를 사용하고 있었다.
2. 강제 종료/installer update/taskkill로 `Drop`이 정상 실행되지 않았다.
3. backend process가 child process tree 밖으로 분리됐다.
4. Windows signal/handler가 cleanup 전에 종료됐다.

### 9.3 필수 여부

- **backend 1개 유지:** 신규 GUI가 동작하려면 필수.
- **X 버튼 후 backend 유지:** tray 앱 설계라면 필수에 가깝다.
- **진짜 종료 후 backend 유지:** 필수 아님. 제거해야 할 문제다.
- **backend 여러 개:** 필수 아님. 방지해야 한다.

## 10. 빈 배경 우클릭 시 웹 브라우저 메뉴가 뜨는 현상 방지

### 10.1 원인

신규 React 앱은 특정 영역에서만 우클릭을 처리한다.

- 게임 행: `onContextMenu={(event) => openContextMenu(...)}`
- 웹 shortcut: `onContextMenu={(event) => openContextMenu(...)}`
- 실행 버튼: `onContextMenu={(event) => openContextMenu(...)}`
- 커스텀 메뉴 자체: `onContextMenu={(event) => event.preventDefault()}`

하지만 root/main/body/document 전체에 대한 `contextmenu` 차단이 없다. 그래서 빈 배경에서는 WebView의 기본 브라우저 메뉴가 뜬다.

### 10.2 권장 구현안

기본 정책:

- 앱 내부 빈 영역의 기본 웹뷰 메뉴는 차단한다.
- 텍스트 입력, textarea, 사용자가 선택/복사해야 하는 영역은 예외로 둔다.
- 앱이 제공하는 우클릭 메뉴가 있는 요소는 기존 핸들러가 먼저 처리한다.

예상 hook:

```tsx
function useDisableDefaultContextMenu(enabled: boolean) {
  React.useEffect(() => {
    if (!enabled) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"], [data-allow-native-context-menu="true"]')) {
        return;
      }
      event.preventDefault();
    };
    document.addEventListener('contextmenu', handler, { capture: true });
    return () => document.removeEventListener('contextmenu', handler, { capture: true });
  }, [enabled]);
}
```

적용:

```tsx
function MainApp() {
  const isTauri = isTauriRuntime();
  useDisableDefaultContextMenu(isTauri);
  ...
}
```

주의:

- capture 단계에서 막으면 행/버튼의 custom context menu도 막을 수 있으므로, 실제 구현 시에는 `event.defaultPrevented` 처리와 custom menu 영역 예외를 테스트해야 한다.
- 개발 중 devtools가 필요한 경우 `import.meta.env.DEV`에서는 허용하거나 modifier key 예외를 둘 수 있다.

## 11. 신규 GUI 로딩이 오래 걸리는 원인 분석

### 11.1 현재 로딩 경로

1. 사용자가 `homework_helper_gui.exe` 실행.
2. Tauri setup에서 `spawn_packaged_backend_if_needed()` 실행.
3. 기존 backend readiness 확인.
4. 없으면 `homework_helper.exe --run-server` spawn.
5. 최대 10초 동안 `/api/gui/health` 준비 대기.
6. Python backend는 서버 시작 전에 DB 백업, 자동 마이그레이션, 테이블 생성, WAL recovery checkpoint, integrity check, schema 보정을 수행.
7. React main app은 `/api/gui/main-state`를 fetch.
8. `/api/gui/main-state`는 DB에서 processes/shortcuts/settings를 읽고, `psutil.process_iter(["exe"])`로 실행 중 프로세스를 스냅샷한다.
9. 각 게임 아이콘 이미지는 `/api/dashboard/icons/{id}?size=128`로 추가 요청된다.

### 11.2 지연 원인 후보

#### 원인 1: backend cold start

Tauri shell은 backend가 준비될 때까지 최대 10초 대기한다. Python/PyInstaller one-dir 앱이 cold start하고 DB 초기화까지 수행하면 사용자는 이 시간을 로딩으로 체감한다.

#### 원인 2: backend 시작 전 DB 작업이 동기 실행

`run_server_main()`은 `backup_database()`, `auto_migrate_database()`, `create_all()`, WAL checkpoint, integrity check를 uvicorn 시작 전에 수행한다. 실사용 DB나 느린 디스크에서는 첫 화면 전 대기 시간이 증가한다.

#### 원인 3: main-state가 OS 프로세스 전체를 매초 스캔

`/api/gui/main-state`는 `_running_process_ids()`에서 `psutil.process_iter(["exe"])`를 돈다. React main app은 이 endpoint를 1초마다 호출한다. 초기 로딩뿐 아니라 평상시 CPU/응답 지연에도 영향을 줄 수 있다.

#### 원인 4: 아이콘 요청/캐시 miss

메인 목록 각 행은 `/api/dashboard/icons/{id}?size=128` 이미지를 로드한다. 캐시가 없거나 실행 파일 아이콘 추출이 필요하면 추가 지연이 생길 수 있다.

#### 원인 5: React/Tauri 창 크기 재측정

`useContentSizedWindow()`는 DOM 크기를 측정하고 `setSize`, `setResizable`, `setPosition`을 수행한다. 데이터 도착 전/후 layout이 바뀌면 resize가 반복될 수 있다.

#### 원인 6: Sidebar window도 자체 polling을 시작할 수 있음

sidebar app도 `/api/gui/main-state`를 1초마다 fetch한다. main window와 sidebar가 동시에 열려 있으면 같은 endpoint polling이 중복된다.

### 11.3 개선안

#### 개선안 A: 로딩 단계 표시

현재 “메인 GUI 상태를 불러오는 중…” 하나로 보인다. 다음처럼 분리하면 체감이 좋아진다.

- backend 확인 중
- backend 시작 중
- DB 점검 중
- 앱 상태 불러오는 중
- 아이콘/갤러리 불러오는 중

#### 개선안 B: backend bootstrap 최소화

- 매 실행마다 전체 integrity check를 하지 않고, 업데이트 직후/비정상 종료 감지 시에만 수행한다.
- DB backup은 빠르게 하되, 무거운 검증은 background task로 넘긴다.
- health endpoint를 가능한 빨리 띄우고, readiness detail을 별도 status로 제공한다.

#### 개선안 C: main-state 경량화

- `_running_process_ids()`를 매 요청마다 전체 process scan하지 않고 backend 내부 캐시/주기 작업으로 분리한다.
- main-state는 cached running ids만 읽는다.
- 초기 화면은 DB 정보만 먼저 보여주고 실행중 상태는 후속 업데이트로 채운다.

#### 개선안 D: polling 주기 조정

- 메인 app의 1초 polling은 실행중 게임이 있을 때만 유지한다.
- 평상시 5~10초로 늦추거나, backend event/SSE/WebSocket으로 전환한다.
- sidebar와 main이 같은 데이터를 각각 polling하지 않도록 공유 event 또는 backend cache를 둔다.

#### 개선안 E: 아이콘 사전 캐시/지연 로딩

- build/update 또는 process 등록 시 아이콘 캐시를 생성한다.
- 첫 화면에서는 placeholder를 먼저 보여주고 아이콘은 lazy load한다.
- 캐시 miss 시 API 응답을 막지 않도록 별도 background job으로 생성한다.

#### 개선안 F: sidecar backend 분리

장기적으로 `homework_helper.pyw`를 PyQt GUI entrypoint와 backend entrypoint로 분리한다. `docs/new-gui-migration.md`에도 후속 후보로 entrypoint 분리가 적혀 있다. 이 분리는 cold start, 중복 실행, 종료 정책을 모두 단순화한다.

## 12. 우선순위별 실행 제안

1. **전역 contextmenu 방지 hook 추가**
   - UX 효과 큼, 위험 낮음.
2. **frameless drag를 수동 `startDragging()` 방식으로 보강**
   - 창 이동 불가 문제의 직접 대응.
3. **사이드바 auto-hide semantics 수정**
   - `0ms` 의미 재정의, pinned/hover 상태 표시, outside leave 보강.
4. **sidebar border/handle visual tuning**
   - CSS만으로 빠르게 개선 가능.
5. **backend health에 owner/version 추가**
   - 다중 backend 원인 추적과 update smoke에 유용.
6. **backend entrypoint 분리**
   - 구조 개선 효과가 크지만 packaging/installer 테스트 범위가 넓다.
7. **loading path 계측**
   - Tauri setup spawn 시간, backend bootstrap 단계, main-state 응답 시간, icon 요청 시간을 로그로 분리한다.

## 13. 검증 필요 항목

Windows에서 다음 smoke를 수행해야 최종 판단할 수 있다.

- 새 GUI main/settings/editor header drag가 실제로 창을 이동하는지.
- 버튼/input/select가 drag로 오작동하지 않는지.
- X 버튼 후 tray 상태와 backend 유지가 의도대로 안내되는지.
- tray “종료” 후 `homework_helper_gui.exe`와 `homework_helper.exe --run-server`가 모두 사라지는지.
- 설치/업데이트 후 backend가 정확히 1개인지.
- 기존 pinned shortcut/startup/admin scheduled task가 신규 GUI 모드와 충돌하지 않는지.
- sidebar 자동 숨김, Pin, Escape, handle hover/click, high-DPI 위치 보정이 실제 Windows 환경에서 동작하는지.

