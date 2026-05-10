# Qt6 GUI와 React/Vite 신규 GUI UX/UI 조작 차이 보고서

작성일: 2026-05-10  
범위: 기존 PyQt6 기본 GUI(`homework_helper.exe`)와 신규 Tauri/React/Vite 미리보기 GUI(`homework_helper_gui.exe`)의 **사용자 조작 관점** 차이

## 1. 결론 요약

신규 GUI는 기존 Qt6 GUI의 기능을 그대로 “화면 구성만 바꾼” 수준이 아니라, 조작 모델이 다음처럼 바뀌었다.

1. **네이티브 데스크톱 앱 조작 → 웹뷰 기반 커스텀 셸 조작**
   - Qt6는 OS 기본 창, 메뉴바, 상태바, QTableWidget, 네이티브 컨텍스트 메뉴를 사용한다.
   - 신규 GUI는 frameless Tauri 창 안의 React 컴포넌트와 CSS 카드/버튼/커스텀 컨텍스트 메뉴를 사용한다.
2. **상태 텍스트 중심 → 색상/인디케이터 중심**
   - Qt6는 테이블의 `상태` 컬럼에 “실행중/미완료/완료” 텍스트와 배경색을 함께 보여준다.
   - 신규 GUI는 상태 텍스트 컬럼을 없애고 행 좌측 색상 바, 점 인디케이터, 진행률 색으로 상태를 표현한다.
3. **상단 메뉴 + 별도 다이얼로그 → 상단 툴바 + 팝업/탭형 설정**
   - Qt6는 메뉴바의 `파일`, `설정` 메뉴와 여러 Qt 다이얼로그를 중심으로 조작한다.
   - 신규 GUI는 헤더 버튼(`+ 게임`, `+ 웹`, 대시보드, GitHub, 설정)과 Tauri 팝업 창/React 탭을 중심으로 조작한다.
4. **사이드바는 기능 parity가 아직 “partial”**
   - 마이그레이션 인벤토리상 `SIDEBAR-001`은 신규 GUI에서 `partial`이며, 자동 숨김/엣지 트리거/볼륨/갤러리/Windows smoke 검증이 남아 있다.
5. **사용자는 더 현대적인 compact UI를 얻지만, 네이티브 앱 기대와 웹뷰 앱 특성이 섞이는 지점이 있다**
   - 예: frameless 창 이동, 빈 배경 우클릭 시 웹뷰 메뉴, 닫기 버튼이 실제 종료가 아니라 트레이 숨김으로 보이는 동작 등.

## 2. 근거 파일

- 마이그레이션 계약: `docs/migration-feature-inventory.md`, `tests/migration/feature_matrix.json`, `docs/migration-smoke-checklist.md`
- 기존 Qt6 GUI:
  - `src/gui/main_window.py`
  - `src/gui/tray_manager.py`
  - `src/gui/sidebar/sidebar_controller.py`
  - `src/gui/sidebar/sidebar_widget.py`
  - `src/gui/dialogs.py`
- 신규 React/Vite/Tauri GUI:
  - `src/gui/new_gui/frontend/src/App.tsx`
  - `src/gui/new_gui/frontend/src/style.css`
  - `src-tauri/tauri.conf.json`
  - `src-tauri/src/lib.rs`
- 배포/업데이트 관련:
  - `build.py`
  - `installer.iss`
  - `homework_helper.pyw`

## 3. 조작 영역별 UX/UI 차이

| 조작 영역 | 기존 Qt6 GUI | 신규 React/Vite GUI | 사용자 관점 차이 |
| --- | --- | --- | --- |
| 창 형태 | OS 기본 장식이 있는 `QMainWindow`. 제목 표시줄/프레임 이동은 OS가 담당. | `decorations: false`인 frameless Tauri 창 + React 헤더. | 창이 더 앱 고유 스타일로 보이지만, 이동/닫기/최소화가 커스텀 구현 의존으로 바뀐다. |
| 창 크기 | 고정 폭, 테이블 행 수에 맞춰 높이 조정. | React DOM 크기를 측정해 Tauri 창 크기를 `setSize`로 조정. | compact 의도는 같지만 신규 GUI는 렌더링 후 측정/resize 단계가 있어 초기 로딩 때 더 “웹앱처럼” 보일 수 있다. |
| 메인 목록 | `QTableWidget` 5컬럼: 아이콘, 이름, 진행률, 실행, 상태. | 카드형 행: 아이콘, 이름/실행 방식, 진행률, 실행 아이콘 버튼. 상태 텍스트 컬럼 없음. | 정보 밀도는 줄고 시각적 구분은 강해진다. 상태를 텍스트로 확인하던 사용자는 색상/점/진행률을 학습해야 한다. |
| 실행 버튼 | 행마다 “실행” 텍스트 버튼. | 재생 아이콘 형태의 버튼. | 공간은 줄지만, 초보 사용자는 아이콘 의미를 툴팁/라벨로 확인해야 한다. |
| 실행 방식 선택 | 실행 버튼 우클릭 메뉴. 기존 구현은 `shortcut/direct` 중심. | 실행 버튼 우클릭 메뉴에서 `바로가기/프로세스/런처 우선` 선택. | 신규 GUI가 런처 우선까지 더 명시적으로 노출한다. |
| 게임 편집/삭제 | 테이블 행 우클릭 → Qt 네이티브 메뉴. | 행 우클릭 → React 커스텀 컨텍스트 메뉴. | 메뉴 디자인은 신규 GUI 톤에 맞지만, 빈 영역 우클릭은 아직 웹뷰 기본 메뉴가 뜰 수 있다. |
| 웹 바로가기 | 상단의 동적 Qt 버튼. 색상으로 due/done 표시. | 별도 shortcut card 안의 버튼. `due/done/default` 클래스. | 웹 바로가기 영역이 메인 게임 목록과 시각적으로 더 분리된다. |
| 웹 바로가기 편집/삭제 | 웹 버튼 우클릭 → Qt 네이티브 메뉴. | 웹 shortcut 우클릭 → React 커스텀 메뉴. | 조작 의도는 동일하지만 메뉴 구현 방식이 웹 컴포넌트로 바뀐다. |
| 설정 진입 | 메뉴바 `설정` 메뉴, 트레이 메뉴, 별도 Qt 다이얼로그들. | 헤더의 ⚙ 버튼, 신규 GUI 설정 팝업/탭. | 설정 접근이 상단 아이콘 중심으로 단순화된다. 메뉴바를 찾는 사용자는 위치가 달라진다. |
| 항상 위 | 메뉴바 우측 체크박스. | 설정 저장 후 Tauri window `setAlwaysOnTop` 반영. | Qt는 즉시 보이는 체크박스, 신규 GUI는 설정 화면 안의 옵션 중심이다. |
| 대시보드 | 상단 `📊` Qt 버튼으로 브라우저/대시보드 열기. | 헤더 `📊 대시보드` 버튼. | 신규 GUI에서는 주요 액션 버튼으로 더 명확하게 표시된다. |
| GitHub 버튼 | Qt 버튼, favicon 다운로드 후 아이콘 설정. | GitHub favicon 이미지 버튼. | 신규 GUI는 외부 이미지/CSP 허용에 의존한다. |
| 상태 메시지 | Qt status bar. | 배너 + `자세히` details. | 긴 실행/오류 메시지는 신규 GUI에서 창을 과도하게 키우지 않고 접어 보여주는 구조다. |
| 트레이/닫기 | 닫기/최소화 시 트레이 숨김, 트레이 메뉴에서 종료. | Tauri close event도 기본적으로 hide 처리, tray 메뉴 열기/숨기기/종료. | 둘 다 트레이 앱 성격이지만, 신규 GUI에서는 “X를 눌렀는데 백엔드가 남아 있음”이 웹뷰/sidecar 구조 때문에 더 눈에 띌 수 있다. |
| 사이드바 | 게임 실행 시 PyQt `EdgeTriggerWindow` + `SidebarWidget`으로 우측 엣지 트리거/자동 숨김. | Tauri `sidebar` window + React `SidebarApp`, 손잡이/패널 구조. | 신규 GUI는 “스마트 서랍” 미리보기 성격이며, 손잡이 노출/자동 숨김/테두리 등 조작 감각이 기존과 아직 다르다. |
| 볼륨/스크린샷/녹화 | PyQt 사이드바 안에서 Windows runtime 기능과 연결. | 신규 사이드바는 설정/갤러리/상태 일부를 API로 보여주며 실제 Windows runtime smoke가 필요. | 신규 GUI는 보조 UI가 구현되어 있으나 실제 제어 parity는 남아 있다. |
| Beholder incident | PyQt dialog. | React modal. | 신규 GUI는 사용자 친화 문구/추천 액션 표시를 목표로 하며, API/CRUD 경계 유지가 핵심이다. |

## 4. 사용자가 체감할 주요 변경점

### 4.1 상태 확인 방식 변화

기존 Qt6 GUI는 상태를 글자로 직접 읽는 방식이다.

- `src/gui/main_window.py`는 테이블 헤더를 `["", "이름", "진행률", "실행", "상태"]`로 구성한다.
- 상태 컬럼은 `실행중`, `미완료`, `완료`에 따라 배경색도 바뀐다.

신규 GUI는 상태 텍스트 컬럼을 제거하고 다음 UI로 대체한다.

- 행 class가 `running/done/incomplete`로 나뉜다.
- CSS에서 좌측 색상 바와 점 인디케이터를 표시한다.
- footer에도 “상태는 행 색상/인디케이터로 표시”라고 안내한다.

**조작 영향:**  
색상 구분이 빠르고 깔끔하지만, 상태 텍스트를 직접 확인하던 사용자는 초기 학습 비용이 있다. 접근성 관점에서는 `aria-label`이 있지만 실제 화면에도 상태 텍스트를 보조적으로 노출할지 검토할 수 있다.

### 4.2 메뉴바 제거와 액션 위치 변화

기존 Qt6 GUI는 메뉴바가 핵심 조작 표면이다.

- `파일(&F)`: 종료, 재시작
- `설정(&S)`: 전역 설정, HoYoLab 설정, 사이드바 설정
- 메뉴바 우측: 항상 위 체크박스, 볼륨 버튼

신규 GUI는 메뉴바가 없고 헤더 액션으로 이동한다.

- `+ 게임`
- `+ 웹`
- `📊 대시보드`
- GitHub favicon
- `⚙`
- 커스텀 window controls

**조작 영향:**  
초기 진입은 단순하지만, “메뉴에서 설정을 찾는” 기존 습관과 다르다. 특히 종료/숨김은 OS 창 버튼과 트레이 메뉴로 분산된다.

### 4.3 편집 화면의 형태 변화

기존 Qt6는 `ProcessDialog`, `WebShortcutDialog`, `GlobalSettingsDialog`, `SidebarSettingsDialog`, `HoYoLabSettingsDialog` 등 여러 Qt 다이얼로그를 사용한다.

신규 GUI는 Tauri runtime에서는 `settings-*`, `process-editor`, `shortcut-editor` 라벨의 별도 frameless popup window를 열고, 브라우저 preview에서는 React modal fallback을 사용한다.

**조작 영향:**  
새 GUI에서는 편집/설정이 메인 창 내부 modal보다 별도 popup처럼 동작한다. 다만 여러 설정 탭이 “하나의 popup 안에서 전환”되는 parity 요구가 있으므로, 창 재생성 없이 탭 전환되는 느낌이 중요하다.

### 4.4 컨텍스트 메뉴 변화

기존 Qt6:

- `QMenu`가 OS 네이티브 메뉴로 표시된다.
- 빈 테이블 영역에서는 별도 메뉴가 뜨지 않는다.

신규 GUI:

- 행/웹 shortcut/실행 버튼은 React 커스텀 메뉴를 띄운다.
- 하지만 전역 `contextmenu` 차단이 없어 빈 배경을 우클릭하면 웹뷰 기본 메뉴가 뜰 수 있다.

**조작 영향:**  
일관된 앱 메뉴와 웹 브라우저 메뉴가 혼재되어 사용자가 “앱이 아니라 브라우저를 보는 느낌”을 받을 수 있다. 이 문제의 상세 원인과 방지 방안은 `new-gui-technical-review-report.md`에 별도로 정리했다.

### 4.5 트레이와 종료 감각 변화

기존 Qt6는 `QApplication.setQuitOnLastWindowClosed(False)`와 `TrayManager`로 트레이 앱처럼 동작한다. 닫기는 숨김이고, 실제 종료는 트레이 메뉴의 종료 또는 앱 종료 시퀀스를 통해 수행된다.

신규 GUI도 Tauri tray를 만들고 close requested 이벤트에서 `prevent_close()` 후 hide한다.

**조작 영향:**  
두 GUI 모두 닫기 버튼이 즉시 프로세스 종료가 아니다. 다만 신규 GUI는 별도 Python backend sidecar를 띄우므로, 사용자는 작업 관리자에서 `homework_helper_gui.exe`와 `homework_helper.exe --run-server`가 함께 남는 것을 볼 수 있다. 이것은 “트레이에 남아 있는 상태”에서는 정상 동작이지만, 실제 종료 후에도 남으면 문제다.

## 5. 마이그레이션 상태상 주의할 부분

`docs/migration-feature-inventory.md`와 `tests/migration/feature_matrix.json` 기준으로 다음 영역은 신규 GUI가 아직 `partial`이다.

- `APP-001`: 기본 앱 shell + 새 GUI 패키징
- `APP-002`: 단일 인스턴스/트레이
- `GAME-001`: 게임 CRUD/실행 방식
- `SIDEBAR-001`: 사이드바/볼륨/오버레이
- `SESSION-001`: 세션 기록/충돌 복구
- `SCHEDULER-001`: 스케줄러/알림
- `HOYOLAB-001`: HoYoLab 스태미나
- `SCREENSHOT-001`: 스크린샷
- `RECORDING-001`: OBS 녹화
- `BEHOLDER-001`: 데이터 안전 감시
- `BACKUP-001`: 백업/복구
- `CLIPBOARD-001`: 클립보드 payload

따라서 신규 GUI는 “기본 GUI 대체 완료본”이 아니라 **패키징 가능한 preview shell**로 보는 것이 안전하다. 사용자에게 기본 설치 GUI를 바꾸려면 Windows smoke checklist, 특히 사이드바/트레이/런타임/종료/백엔드 항목을 먼저 통과해야 한다.

## 6. UX 관점 권장 개선 우선순위

1. **빈 배경 우클릭 기본 웹뷰 메뉴 차단**
   - 앱 몰입감을 크게 해치는 문제이며 구현 난도가 낮다.
2. **frameless 창 이동을 정적 attribute 의존에서 명시적 drag API로 보강**
   - 사용자가 창을 이동하지 못하면 앱 기본 조작이 막힌다.
3. **사이드바 닫힘/손잡이 노출 정책 명확화**
   - “항상 보이는 얇은 손잡이”가 의도라면 설정/도움말에 명시하고, 기존 Qt6처럼 완전히 숨기는 모드도 제공한다.
4. **종료/트레이/백엔드 상태를 사용자 언어로 안내**
   - X 버튼은 숨김, 트레이 종료는 실제 종료, backend는 신규 GUI API를 위한 필수 sidecar라는 차이를 명확히 해야 한다.
5. **초기 로딩 단계별 상태 표시**
   - “백엔드 시작 중”, “DB 점검 중”, “상태 불러오는 중”처럼 구분하면 체감 대기 시간이 줄어든다.

