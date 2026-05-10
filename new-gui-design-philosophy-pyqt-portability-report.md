# 신규 GUI 디자인 철학의 기존 PyQt6 프레임워크 이식 가능성 검토 보고서

작성일: 2026-05-10  
범위: 신규 Tauri/React/Vite GUI의 디자인 철학을 기존 PyQt6 GUI(`homework_helper.exe`) 프레임워크에 어디까지 이식할 수 있는지 기술 검토  
요구사항: 동일 기능/변화된 기능을 1:1 매칭하여 분석

## 1. 결론 요약

신규 GUI의 디자인 철학은 **대부분 PyQt6 Widgets 프레임워크로 이식 가능**하다. 다만 “웹뷰 자체의 구현 방식”을 그대로 옮기는 것이 아니라, Qt의 `QWidget`, `QFrame`, `QSS`, `QStackedWidget`, `QDialog`, `QPropertyAnimation`, `QGraphicsDropShadowEffect`, `QSystemTrayIcon`, 기존 `SidebarWidget`/`EdgeTriggerWindow` 위에 **동등한 사용자 경험을 재구성**하는 방식이어야 한다.

핵심 판단은 다음과 같다.

| 디자인 철학 | PyQt6 이식성 | 판단 |
| --- | --- | --- |
| 카드형/토큰형 다크 UI | 높음 | QSS, QFrame, QPalette, 공통 style token 모듈로 이식 가능 |
| 상태 텍스트 축소 + 색상/점/행 바 인디케이터 | 높음 | QTableWidget 유지 또는 custom row widget으로 가능 |
| 컴팩트 자동 높이/내용 기반 창 크기 | 높음 | 이미 PyQt에 테이블 행 기반 높이 조정 로직 존재 |
| 상단 툴바 중심 액션 배치 | 높음 | 메뉴바 유지 여부와 별개로 QHBoxLayout/QToolButton으로 가능 |
| 설정/편집 별도 popup 및 단일 설정 탭 구조 | 높음 | QDialog + QStackedWidget/QTabWidget으로 가능 |
| 긴 메시지 요약 + 자세히 보기 | 높음 | QLabel + QToolButton/QTextEdit 접힘 영역으로 가능 |
| 사용자 언어 Beholder incident UX | 높음 | 기존 Beholder dialog에 payload 문구를 반영하면 가능 |
| 스마트 서랍 손잡이/Pin/Escape/갤러리 | 중간~높음 | 기존 PyQt 사이드바가 더 강한 Windows runtime 기반을 갖고 있어, UI만 갱신하면 신규 GUI보다 안정적일 수 있음 |
| Frameless custom chrome | 중간 | 가능하지만 Windows DPI, hit-test, 접근성, resize/drag smoke가 필요 |
| 웹뷰 배경 우클릭 차단 | PyQt에는 해당 없음 | PyQt는 네이티브 위젯이라 기본 웹 브라우저 메뉴 문제가 없다 |
| Tauri sidecar backend 구조 | 낮음/불필요 | 기존 PyQt는 이미 Python 프로세스와 API 서버를 직접 관리하므로 그대로 이식할 대상이 아님 |

따라서 권장 방향은 **“신규 GUI 디자인 언어를 PyQt에 역이식해 기본 GUI의 체감 품질을 먼저 끌어올리고, Tauri preview는 장기 전환 후보로 유지”**하는 것이다. 이 방식은 현재 프로젝트 계약의 “기본 설치 GUI는 PyQt 유지, 새 GUI는 preview shell” 원칙과도 맞다.

## 2. 확인한 근거

### 2.1 마이그레이션 계약

- `docs/migration-feature-inventory.md`
- `tests/migration/feature_matrix.json`
- `docs/migration-smoke-checklist.md`

계약상 기본 설치 GUI는 아직 `homework_helper.exe`/PyQt이며, `homework_helper_gui.exe`는 packaged preview shell이다. 새 GUI의 `partial` 기능은 Windows smoke 및 high-risk 데이터 안전 검증이 남아 있다.

### 2.2 기존 PyQt6 구현

- `src/gui/main_window.py`
  - 기존 메인 창, QTableWidget 목록, 메뉴바, 상태바, 웹 shortcut, 대시보드/GitHub 버튼, 창 위치/크기 저장, 트레이 숨김, 타이머 갱신.
- `src/gui/tray_manager.py`
  - QSystemTrayIcon 기반 show/hide/quit.
- `src/gui/dialogs.py`
  - 게임/웹/전역 설정/HoYoLab 설정 Qt dialog.
- `src/gui/sidebar/sidebar_controller.py`
  - 게임 실행 시 sidebar trigger/widget lifecycle.
- `src/gui/sidebar/edge_trigger_window.py`
  - 투명 edge trigger, cursor polling.
- `src/gui/sidebar/sidebar_widget.py`
  - slide-in sidebar, QPropertyAnimation, 자동 숨김, 볼륨/시계/플레이타임/스크린샷/녹화 썸네일.

### 2.3 신규 React/Tauri 구현

- `src/gui/new_gui/frontend/src/App.tsx`
  - compact shell, row card, custom context menu, popup windows, settings tabs, sidebar drawer, Beholder modal, polling.
- `src/gui/new_gui/frontend/src/style.css`
  - `--hh-*` design token, dark panel, card, row indicator, drawer, message banner.
- `src-tauri/tauri.conf.json`
  - frameless windows, sidebar transparent window, CSP.
- `src-tauri/src/lib.rs`
  - tray, single-instance, backend sidecar spawn/kill.

### 2.4 Qt/PyQt 기술 근거

Qt Widgets/Qt for Python 문서 기준으로 다음 API 계열은 신규 GUI 철학을 PyQt 위젯으로 재현하는 데 사용할 수 있다.

- `QWidget.setStyleSheet()` / application-wide QSS: CSS-like theme token 적용.
- `QFrame`, `QWidget`, `QBoxLayout`, `QGridLayout`: card/list/panel 구조.
- `QStackedWidget`, `QTabWidget`: 설정 탭/단일 popup 전환.
- `QWidget` window flags: frameless/custom window flags.
- `mousePressEvent`, `mouseMoveEvent`: custom titlebar drag.
- `QPropertyAnimation`: sidebar slide-in/out.
- `QGraphicsDropShadowEffect`: card/shadow.

## 3. 신규 GUI 디자인 철학 정의

직전 분석 기준 신규 GUI의 철학은 다음 10개로 정리할 수 있다.

1. **Compact shell**
   - 내용에 맞춰 창 크기를 줄이고, 불필요한 OS chrome/메뉴를 줄인다.
2. **Card/list visual hierarchy**
   - 테이블 격자보다 카드/행/패널로 정보를 묶는다.
3. **Status by visual signal**
   - 상태 텍스트보다 좌측 바, 점, 색상, 진행률로 빠르게 구분한다.
4. **Action-first topbar**
   - 메뉴바 탐색보다 상단 액션 버튼으로 주요 조작을 직접 노출한다.
5. **Popup isolation**
   - 게임/웹/설정 편집을 별도 popup 또는 단일 설정 shell 안에서 처리한다.
6. **Progressive disclosure**
   - 긴 오류/실행 메시지는 요약을 먼저 보여주고 “자세히”로 확장한다.
7. **API/CRUD/Beholder boundary**
   - UI가 직접 DB를 만지지 않고 안전 경계를 통과한다.
8. **User-language safety UX**
   - Beholder/복구/위험 신호를 내부 코드명보다 사용자 언어로 설명한다.
9. **Smart drawer sidebar**
   - 얇은 edge handle, hover/click open, Pin, Escape, auto-hide, gallery를 한 흐름으로 묶는다.
10. **Preview-packaged separation**
    - 새 GUI는 preview shell이고 backend/runtime 계약은 기존 Python/AppData 경계에 둔다.

이 중 PyQt에 이식해야 할 것은 1~9번이다. 10번은 패키징 전략이지 PyQt UI 내부 디자인 철학은 아니다.

## 4. PyQt6 이식성 등급 기준

| 등급 | 의미 | 적용 예 |
| --- | --- | --- |
| A: 즉시 이식 가능 | QSS/레이아웃/기존 widget 교체만으로 가능 | 색상 token, card, toolbar, message banner |
| B: 구조 개선 후 가능 | 기존 코드 일부 분해/위젯화 필요 | QTableWidget → row card, 단일 설정 popup |
| C: 런타임/Windows smoke 필요 | 기능은 가능하지만 window flag, hook, DPI, overlay 위험 있음 | frameless chrome, smart drawer |
| D: PyQt 역이식 부적합 | Tauri/WebView/sidecar 고유 구조라 PyQt에 옮길 필요 없음 | 웹뷰 context menu, Tauri backend child ownership |

## 5. 동일/변경 기능 1:1 매칭 분석

아래 표는 `tests/migration/feature_matrix.json`의 Feature ID 18개를 기준으로 모든 기능을 1:1 매칭한 것이다.

| ID | 기능 | PyQt 현재 | 신규 GUI 변화/철학 | PyQt로 역이식 가능성 | 기술 접근 | 주의/검증 |
| --- | --- | --- | --- | --- | --- | --- |
| APP-001 | 기본 앱 shell + 메인 창 | `QMainWindow`, 메뉴바, 상태바, QTableWidget, OS chrome. | frameless compact shell, topbar, card row, 상태 텍스트 축소, message banner. | B~C | QMainWindow 중앙 위젯을 `ChromeFrame` + `Topbar` + `CardList`로 재구성. OS chrome은 유지하면서 내부만 신규 톤 적용하는 것이 1차 권장. Frameless는 2차. | Frameless 적용 시 위치 이동/작업표시줄/DPI/Alt+F4 smoke 필요. |
| APP-002 | 단일 인스턴스/트레이 | `SingleInstanceApplication`, IPC, `QSystemTrayIcon`으로 complete. | Tauri single-instance/tray hook, close→hide. | A | 기존 PyQt가 이미 더 완성되어 있음. 신규 GUI 철학 중 “닫기=숨김, 종료=트레이 메뉴” 안내 문구만 보강. | 변경 불필요. UI 문구/트레이 메뉴 라벨만 개선 가능. |
| GAME-001 | 게임 CRUD/실행 방식 저장 | `ProcessDialog`, QTableWidget row 우클릭, DataManager/ApiClient. | 별도 popup editor, 런타임 필드 편집 차단, row card context menu. | B | 기존 `ProcessDialog`를 card 스타일 popup으로 재스킨. edit form을 runtime field와 config field로 분리. 우클릭 메뉴는 유지하되 row card에서도 접근. | CRUD/Beholder 경계 유지, 런타임 필드 보존 테스트 필수. |
| GAME-002 | 게임 실행 | 행의 “실행” 버튼, shortcut/direct 중심, status bar 메시지. | icon launch button, launch target/방식 메시지, launcher 우선 명시. | A~B | 실행 버튼을 icon `QToolButton`으로 바꾸고, tooltip/status banner에 launch target 표시. launcher preference 메뉴를 PyQt에도 확장. | 관리자 권한/shortcut/direct/launcher Windows smoke 필요. |
| WEB-001 | 웹 바로가기 | 상단 동적 QPushButton, 색상으로 due/done, 우클릭 QMenu. | shortcut card 영역, due/done/default class, popup editor. | A~B | 웹 버튼을 `ShortcutCardBar` QFrame으로 감싸고 due/done style token 적용. 기존 QMenu 유지 또는 card context menu. | 완료 시각은 runtime 경계에서만 변경. |
| SETTINGS-001 | 전역 설정 | `GlobalSettingsDialog` + 별도 sidebar/HoYoLab dialog, 메뉴바 진입. | 단일 설정 popup 안 탭 전환, 자동 크기, notification/sidebar/screenshot/recording/HoYoLab 통합. | B | `SettingsDialogV2(QDialog)` + `QStackedWidget` 또는 `QTabWidget`. 기존 dialog들의 form section을 page widget으로 이관. | PyQt full settings update가 숨은 필드를 덮지 않는 테스트 유지. |
| SETTINGS-002 | 설정 계약 동기화 | model/schema/runtime/migration complete. | API facade와 patch validation 강화. | A | UI 디자인보다 계약 문제. PyQt도 저장 전 field scope/범위 validation을 API/CRUD 쪽과 맞춘다. | UI 직접 DB commit 금지. |
| SIDEBAR-001 | 사이드바/볼륨/오버레이 | `EdgeTriggerWindow` + `SidebarWidget`, 자동 숨김/외부 클릭/Win32 효과/볼륨/갤러리 일부. | Tauri sidebar window + 12px handle, Pin/Escape, card drawer, screenshot/recording gallery preview. | B~C | 기존 PyQt sidebar가 런타임 기반은 더 강함. 신규 GUI의 handle/Pin/Escape/card gallery 디자인만 `SidebarWidget`에 이식. | high-DPI/전체화면/edge trigger/auto-hide smoke 필수. |
| SESSION-001 | 세션 기록/충돌 복구 | ProcessMonitor와 Beholder 기반 complete. | runtime heartbeat, open session 복구 UX를 modal로 표시. | A~B | 기존 `BeholderIncidentDialog`에 신규 GUI의 추천 액션/결과/위험 문구 구조를 이식. | 세션 종료 스태미나 guard 유지. |
| SCHEDULER-001 | 스케줄러/알림 | Scheduler/Notifier runtime complete. | 설정 popup에 notification preview, 현재 미완료 수/예정 알림/심각도 사용자 언어 표시. | A~B | PyQt 설정 dialog에 `SchedulerPreviewPanel` 추가. `/api/gui/scheduler/preview` 또는 동일 service 함수를 재사용. | 실제 알림 runtime smoke 필요. |
| DASHBOARD-001 | 대시보드 analytics | PyQt 버튼으로 `/dashboard` 열기, dashboard web UI 별도. | 새 GUI v6 tone과 dashboard token 일치. | A | PyQt 대시보드 버튼과 외부 dashboard 자체 스타일 token 공유는 가능. PyQt 내부는 dashboard visual token 일부만 QSS로 반영. | dashboard frontend와 PyQt QSS token drift 관리 필요. |
| HOYOLAB-001 | HoYoLab | 별도 `HoYoLabSettingsDialog`, 종료 후 재동기화 runtime. | 설정 탭 통합, 쿠키 추출/수동 저장/삭제/테스트 조회, row 우클릭 stamina refresh. | B | HoYoLab dialog를 설정 탭 page로 편입. 게임 row context menu에 “스태미나 새로고침” 추가. progress에 resource icon 표시. | token 값 미노출, Beholder actor 허용, 지연 재확인 smoke. |
| SCREENSHOT-001 | 스크린샷 | Sidebar settings dialog, runtime ScreenshotManager, sidebar thumbnails. | 설정 탭, key capture, gallery API thumbnail, copy affordance. | A~B | PyQt는 이미 native thumbnail/clipboard에 강점. 신규 GUI의 gallery grid와 key capture 안내 UI를 QFrame grid로 반영. | Windows capture mode/gamepad smoke 필요. |
| RECORDING-001 | OBS 녹화 | RecordingManager, Sidebar callbacks, OBS settings. | OBS config import, 비밀번호 존재 여부 표시, recording gallery preview. | A~B | 기존 recording UI에 password redaction/status badge/gallery card를 반영. OBS 설정 불러오기 결과를 “평문 없음/존재 여부”로 표시. | 비밀번호 빈 값 덮어쓰기 금지 테스트 유지. |
| BEHOLDER-001 | 데이터 안전 감시 | PyQt incident dialog, Beholder API/CRUD guards. | 사용자 친화 modal, risk label localization, backup preview summary, smart action. | A~B | `BeholderIncidentDialog`를 신규 GUI payload 구조에 맞춰 재디자인. 위험 요인/추천 액션/결과/DB 요약 sections. | 내부 코드명 노출 금지, resolution 상태 검증. |
| BACKUP-001 | DB/설정/row 백업 | backup_database, Beholder restore. | restore preview에 DB 요약/영향 안내. | A | PyQt restore dialog에 preview step 추가. 기존 `get_beholder_backups`/preview API 또는 service 사용. | 실제 restore smoke 필요. |
| BUILD-001 | 패키징 | PyInstaller/Inno complete. | legacy/new_gui 단일 진입점 선택, Tauri shell packaging. | D | PyQt 디자인 역이식 대상이 아님. 다만 “새 UI를 PyQt에 먼저 이식”하면 legacy mode 품질 개선으로 반영됨. | installer mode smoke는 계속 필요. |
| CLIPBOARD-001 | 클립보드 payload | native Qt/Win32 clipboard utility. | API copy-file, sidebar gallery right-click copy. | A | 기존 PyQt가 native clipboard에 더 적합. 신규 GUI의 “우클릭: 복사” affordance와 gallery 상태만 이식. | 탐색기/채팅창 붙여넣기 smoke. |

## 6. 사용자 조작 단위 1:1 매칭

Feature ID와 별개로 사용자가 직접 만지는 UI 요소를 기준으로 다시 매칭하면 다음과 같다.

| 사용자 조작 | 기존 PyQt 구현 | 신규 GUI 구현 | PyQt 이식 판단 |
| --- | --- | --- | --- |
| 앱 실행 | PyQt main + API server multiprocessing | Tauri shell + Python backend sidecar | 기존 유지. sidecar 구조는 역이식 불필요 |
| 창 이동 | OS titlebar | header drag region | OS titlebar 유지 권장. frameless는 선택적 C등급 |
| 창 크기 | 고정폭 + row count height | DOM content measurement | 기존 height adjust 로직 개선으로 충분 |
| 게임 목록 보기 | QTableWidget grid | card row list | QTableWidget cell widget 또는 QListWidget custom item으로 이식 가능 |
| 상태 확인 | 상태 텍스트 column + 배경색 | 좌측 bar/dot/progress color | 상태 텍스트를 보조로 숨기거나 tooltip으로 옮기는 방식 가능 |
| 게임 실행 | “실행” QPushButton | icon launch button | QToolButton으로 가능 |
| 실행 방식 선택 | 실행 버튼 우클릭, shortcut/direct | 실행 버튼 우클릭, shortcut/direct/launcher | PyQt에 launcher 항목 추가 가능 |
| 게임 편집 | row 우클릭 → ProcessDialog | row 우클릭 → popup editor | ProcessDialog QSS/팝업 frame 이식 가능 |
| 웹 shortcut 열기 | 상단 버튼 | shortcut card | QPushButton bar를 QFrame card group으로 변경 가능 |
| 웹 shortcut 편집 | 버튼 우클릭 QMenu | custom context menu | QMenu 유지 권장. 디자인만 QSS 적용 |
| 설정 열기 | 메뉴바/트레이 | topbar gear | 메뉴바 유지 + topbar gear 추가 가능 |
| 설정 탭 전환 | 여러 dialog 분산 | 단일 popup tab | QStackedWidget으로 이식 가치 높음 |
| 항상 위 | 메뉴바 corner checkbox | settings option then setAlwaysOnTop | 두 방식을 병행 가능 |
| 긴 오류 확인 | status bar / message box | banner + details | PyQt banner widget 추가 권장 |
| 대시보드 열기 | 📊 버튼 | 📊 대시보드 버튼 | 현재 버튼 label/tooltip 개선만 필요 |
| GitHub 열기 | GH/fav icon button | favicon image button | Qt icon cache 또는 bundled icon 권장 |
| Beholder incident 처리 | modal dialog | user-friendly modal | PyQt dialog 재디자인 가능 |
| 사이드바 열기 | 투명 edge trigger | visible handle hover/click | 기존 trigger 유지 + visible handle 옵션 추가 가능 |
| 사이드바 고정 | 없음/제한적 | Pin | PyQt sidebar에 pin state 추가 가능 |
| 사이드바 닫기 | auto-hide/outside click | Escape/button/timer | PyQt에 Escape/Pin UI를 추가하면 신규보다 안정적 |
| 스크린샷 갤러리 | PyQt sidebar thumbnails | drawer media grid | 기존 thumbnail cell 스타일 개선 가능 |
| 녹화 갤러리 | PyQt video thumbnail support | HTML video preview | PyQt는 Shell thumbnail/placeholder 방식 유지 권장 |
| 우클릭 빈 배경 | 네이티브 앱이라 웹 메뉴 없음 | WebView 기본 메뉴 문제 | PyQt 해당 없음 |
| 앱 종료 | tray quit sequence | tray quit + child backend kill | 기존 PyQt 종료 sequence 유지 |

## 7. PyQt에 이식할 수 있는 디자인 구성 요소별 기술안

### 7.1 Design token/QSS 계층

신규 GUI의 `--hh-*` CSS token은 PyQt에서도 별도 Python dict 또는 QSS template로 옮길 수 있다.

권장 구조:

- `src/gui/theme_tokens.py`
  - `HH_BG`, `HH_PANEL`, `HH_LINE`, `HH_ACCENT`, `HH_DANGER`, `HH_GOOD`
  - dark/light/system palette 계산
- `src/gui/styles.py`
  - `build_app_qss(theme) -> str`
  - `card_qss()`, `button_qss()`, `row_state_qss(status)`

예상 적용:

- `QApplication.setStyleSheet(build_app_qss(theme))`
- card widget은 objectName으로 선택자 적용: `QFrame#GameRowCard`, `QFrame#ShortcutCard`, `QFrame#MessageBanner`

이식성: A  
위험: 기존 OS native look와 충돌 가능. 단계적으로 objectName 기반 적용 권장.

### 7.2 메인 목록: QTableWidget 유지 vs CardList 전환

선택지 1: `QTableWidget` 유지

- 장점: 기존 로직 변경 최소.
- 행 높이를 키우고 `setCellWidget()`으로 card-like row content를 넣는다.
- 상태 컬럼을 숨기거나 좁히고 좌측 state bar cell을 추가한다.

선택지 2: `QScrollArea + QVBoxLayout + GameRowCard(QWidget)`

- 장점: React row card와 가장 유사.
- 단점: 정렬/가상화/키보드 접근성을 직접 구현해야 한다.

추천:

1차는 QTableWidget 유지 + QSS/card style 이식.  
2차에서 `GameRowCard` 위젯으로 전환.

이식성: B

### 7.3 Topbar

기존 PyQt는 메뉴바와 top button area가 이미 있다. 신규 GUI 철학은 메뉴바를 없애는 것보다 **주요 액션을 보이는 곳으로 끌어올리는 것**이 핵심이다.

권장:

- 메뉴바는 기존 사용자/키보드 접근성을 위해 유지.
- 중앙 위젯 상단에 `TopbarWidget`을 둔다.
- `+ 게임`, `+ 웹`, `대시보드`, `GitHub`, `설정`, `볼륨`, `항상 위`를 한 줄에 배치한다.
- 메뉴바 기능은 중복 제공하되, 장기적으로 “고급 메뉴”로 축소 가능.

이식성: A

### 7.4 단일 설정 popup

가장 이식 가치가 높은 부분이다.

현재 PyQt는 전역 설정, 사이드바 설정, HoYoLab 설정 등이 분리되어 있다. 신규 GUI는 하나의 설정 popup 안에서 일반/알림/사이드바/스크린샷/녹화/HoYoLab 탭을 전환한다.

PyQt 구현안:

- `SettingsDialogV2(QDialog)`
- 좌측 navigation: `QListWidget` 또는 button column
- 우측 page: `QStackedWidget`
- pages:
  - GeneralSettingsPage
  - NotificationSettingsPage
  - SidebarSettingsPage
  - ScreenshotSettingsPage
  - RecordingSettingsPage
  - HoYoLabSettingsPage
- 저장:
  - dirty field tracking
  - 기존 `GlobalSettings.from_dict()`로 full object preserve
  - actor/allowed fields 경계 유지

이식성: B  
주의: settings high-risk. 자동 테스트 유지/추가 필요.

### 7.5 Message banner / details

신규 GUI의 `MessageBanner`는 status bar보다 사용자 친화적이다.

PyQt 구현안:

- `MessageBanner(QFrame)`
  - summary `QLabel`
  - “자세히” `QToolButton`
  - detail `QPlainTextEdit` 또는 read-only `QTextEdit`
  - `setMaximumHeight`로 접힘/펼침
- status bar는 짧은 상태만 유지.

이식성: A

### 7.6 Beholder dialog

신규 GUI의 Beholder 장점은 “내부 코드명이 아닌 사용자 언어”와 “추천 액션/결과/위험 신호” 구조다.

PyQt 구현안:

- 기존 `BeholderIncidentDialog` layout을 다음 section으로 재구성:
  - 제목/요약
  - 현재 상태
  - 제안 변경
  - 사용자 영향
  - 위험 신호 label chips
  - 추천 액션 primary button
  - 기타 액션 secondary/danger button
  - 백업 복구 preview button
- `risk_labels` 우선 사용, 없으면 localized fallback 사용.

이식성: A~B  
주의: action resolution 결과와 process monitor 상태 반영을 유지해야 한다.

### 7.7 Smart drawer/sidebar

기존 PyQt sidebar는 신규 Tauri sidebar보다 runtime 측면이 강하다.

이미 있는 것:

- `EdgeTriggerWindow`: 우측 투명 trigger.
- `SidebarWidget`: slide animation, auto-hide timer, cursor polling, outside click, clock/playtime/volume, screenshot/recording thumbnails.
- `QPropertyAnimation`: slide-in/out.

신규에서 가져올 것:

- 얇은 visible handle option.
- Pin 고정.
- Escape 닫기.
- drawer header action 정리.
- gallery card/chip style.
- “자동숨김 3000ms / 고정됨” footer status.

권장:

- 기존 투명 trigger는 유지한다.
- 설정에 `sidebar_visible_handle_enabled`를 추가할지 검토한다.
- visible handle은 별도 `SidebarHandleWindow`로 만들거나 `EdgeTriggerWindow` opacity/style option으로 확장한다.
- Pin 상태일 때 auto-hide timer를 중지.
- `keyPressEvent`에서 Escape 닫기.

이식성: B~C  
주의: 전체화면 게임 위 topmost, Windows focus, click-through, high-DPI smoke 필요.

### 7.8 Frameless custom chrome

신규 GUI처럼 완전 frameless로 만드는 것은 가능하지만, PyQt 기본 GUI에 바로 적용하는 것은 권장 우선순위가 낮다.

가능 구현:

- `setWindowFlags(Qt.FramelessWindowHint | Qt.Window)`
- custom titlebar `QFrame`
- `mousePressEvent`에서 drag origin 저장
- `mouseMoveEvent`에서 `move(globalPosition - dragOffset)`
- minimize/close buttons 직접 구현

위험:

- Windows shadow/rounded corner 직접 처리 필요.
- resize 불가 앱이라도 hit-test/drag/Alt+Space/접근성 문제가 생길 수 있다.
- 기존 OS chrome이 주는 안정성을 잃는다.

추천:

- 1차 역이식에서는 OS titlebar 유지.
- 내부 card shell만 신규 톤으로 바꾼다.
- frameless는 optional preview branch 또는 설정으로 둔다.

이식성: C

## 8. 이식하지 않는 것이 나은 요소

### 8.1 Tauri sidecar backend ownership

신규 GUI는 웹뷰가 DB를 직접 열지 않기 때문에 Python backend sidecar가 필요하다. 기존 PyQt는 이미 Python 프로세스 내부에서 API server lifecycle을 관리한다.

따라서 PyQt에 sidecar 구조를 역이식할 필요는 없다. 오히려 기존 PyQt에 신규 sidecar 방식을 섞으면 백엔드 중복 실행/종료 혼동이 커진다.

### 8.2 WebView context menu 대응

빈 배경 우클릭 시 브라우저 메뉴가 뜨는 현상은 Tauri/WebView 고유 문제다. PyQt Widgets에는 해당 문제가 없다. PyQt에서는 오히려 필요한 영역에만 `Qt.CustomContextMenu`를 유지하면 된다.

### 8.3 CSS/DOM 기반 layout measurement

React의 `scrollWidth`, `ResizeObserver`, Tauri `setSize` 흐름은 PyQt에 직접 옮길 대상이 아니다. PyQt에서는 `sizeHint()`, `adjustSize()`, row height 계산, `QLayout.activate()`가 더 자연스럽다.

## 9. 단계별 이식 로드맵

### 1단계: 저위험 시각 언어 이식

목표: 기존 기능 동작을 바꾸지 않고 체감 UI만 개선.

- QSS token 도입.
- topbar 버튼 스타일 정리.
- 상태색/진행률 색상 token 정리.
- message banner widget 추가.
- GitHub/대시보드 버튼 label 개선.

검증:

- `python tools/verify_project.py`
- PyQt 기본 앱 smoke: 실행/트레이/설정/게임 실행.

### 2단계: 메인 목록 card화

목표: 신규 GUI의 row card 철학을 PyQt 목록에 이식.

- QTableWidget row style 개선 또는 `GameRowCard` 도입.
- 상태 텍스트 컬럼을 보조 정보로 축소.
- 좌측 state bar/dot 추가.
- 실행 버튼 icon화 + launch target detail banner.

검증:

- 상태 running/done/incomplete 표시 parity.
- 게임 CRUD/실행 방식 우클릭 smoke.
- 실제 DB fixture 표시.

### 3단계: 단일 설정 popup

목표: 분산된 설정 dialog를 신규 GUI식 single settings shell로 통합.

- `SettingsDialogV2` + `QStackedWidget`.
- 일반/알림/사이드바/스크린샷/녹화/HoYoLab page 구성.
- dirty field tracking.
- 저장 시 full settings 보존.

검증:

- `SETTINGS-001`, `SETTINGS-002` 자동 테스트 유지.
- Windows 시작프로그램/관리자 권한 smoke.

### 4단계: Beholder/Backup 사용자 언어 UX

목표: high-risk 데이터 안전 UX를 신규 GUI 수준으로 개선.

- PyQt Beholder dialog에 risk label localization.
- 추천 액션/결과/영향 설명.
- backup restore preview.

검증:

- Beholder tests.
- real AppData clone.
- backup restore smoke.

### 5단계: Sidebar smart drawer 이식

목표: 기존 PyQt sidebar runtime 안정성을 유지하면서 신규 smart drawer 감각을 도입.

- Pin/Escape/footer status.
- visible handle option.
- gallery card 통일.
- recording/screenshot thumbnail structure 정리.

검증:

- Windows full-screen game smoke.
- high-DPI 위치 보정.
- auto-hide/outside click/pin/escape.

### 6단계: Optional frameless PyQt shell

목표: 정말 필요한 경우에만 신규 GUI의 frameless chrome을 PyQt에도 제공.

- 설정 또는 preview flag로만 제공.
- OS titlebar fallback 유지.

검증:

- 창 이동/닫기/최소화/트레이/Alt+Tab/작업표시줄 smoke.

## 10. 자동 테스트/문서 업데이트 필요성

보고서 작성 자체는 사용자-visible 기능 변경이 아니므로 feature matrix를 수정할 필요는 없다. 그러나 실제 이식 구현을 시작하면 다음 계약을 지켜야 한다.

- user-visible 기능 추가/변경 시 `docs/migration-feature-inventory.md`와 `tests/migration/feature_matrix.json` 동시 업데이트.
- high-risk 데이터 기능은 자동 테스트 추가/수정.
- Windows-only 동작은 `docs/migration-smoke-checklist.md` 업데이트.
- `HomeworkHelper.zip`이 있으면 clone 기반 real-data 검증 포함.
- UI/router 직접 DB commit 금지.

## 11. 최종 권고

가장 현실적인 선택은 **신규 GUI의 “시각/조작 철학”을 PyQt에 먼저 이식하고, Tauri GUI는 preview로 계속 검증**하는 것이다.

이유:

1. PyQt는 이미 세션/스케줄러/사이드바/스크린샷/녹화/트레이 runtime이 complete 상태다.
2. 신규 GUI의 강점 대부분은 React 자체가 아니라 정보 구조와 시각 언어다.
3. QSS/QFrame/QStackedWidget/QPropertyAnimation으로 신규 GUI의 핵심 체감은 충분히 재현 가능하다.
4. 반면 Tauri sidecar/frameless/webview context menu 같은 문제는 PyQt로 역이식할 대상이 아니라 신규 GUI 고유의 전환 비용이다.

따라서 이식 우선순위는 다음과 같다.

1. QSS design token + card/button 스타일.
2. 메인 목록 row card/상태 인디케이터.
3. 단일 설정 popup.
4. message banner/details.
5. Beholder/backup 사용자 언어 UX.
6. sidebar smart drawer UI.
7. 선택적 frameless chrome.

이 순서라면 기존 PyQt의 안정적인 runtime과 데이터 안전 계약을 유지하면서도, 신규 GUI가 의도한 현대적이고 compact한 조작 경험을 상당 부분 흡수할 수 있다.

