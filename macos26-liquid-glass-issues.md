# macOS 26 Liquid Glass 전환 중 발생 이슈 기록

작성일: 2026-05-15

## 기록 원칙

작업 중 발생한 문제는 숨기지 않고 이 파일에 남긴다. 해결된 문제도 원인과 조치, 검증 근거를 함께 기록한다.

---

## Issue 1 — 대량 치환 중 SwiftUI body brace 불균형

- 상태: 해결됨
- 발생 시점: `RemoteDashboardView`와 `MenuBarPopoverView`를 `GlassEffectContainer` 기반으로 감싸는 중
- 증상:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 실패
  - 대표 오류:
    - `extraneous '}' at top level`
    - `expected declaration`
- 원인:
  - 기존 `ZStack`/`VStack` body에 `GlassEffectContainer`를 자동 치환으로 삽입하면서 closing brace가 중복 삽입됨.
- 조치:
  - `RemoteDashboardView` body 전체를 수동으로 재작성함.
  - `MenuBarPopoverView` body 전체를 수동으로 재작성함.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.

---

## 현재 보류/미검증 항목

- 실제 GUI 수동 검수는 이 환경에서 앱을 사람이 직접 조작한 결과가 아니므로 보류로 남긴다.
- 특히 아래 항목은 자동/정적 테스트와 빌드로 구조 보전은 확인했지만, 최종 판정에는 사용자의 실기기 수동 확인이 필요하다.
  - Spotlight 반복 focus 시 창 1개 유지
  - Cmd+, / 메뉴바 설정 / sidebar 설정 버튼 실사용 동작
  - Liquid Glass 시각 품질
  - Popover status pill 즉시 반영 체감
  - 아이콘 렌더링 품질 체감
  - 전원 버튼 실제 wake/sleep/restart/shutdown 수행

---

## Issue 2 — image copy 6 기준 glass 테두리 잘림과 click/scroll-through

- 상태: 코드 대응 완료, 수동 검수 필요
- 발생 시점: macOS 26 Liquid Glass 전환 빌드 실기기 검수
- 증상:
  - 일부 섹션 glass 테두리가 창 경계에서 잘림.
  - 앱 창 내부 빈 영역 클릭/스크롤이 뒤에 있는 창으로 전달됨.
  - 창 native 테두리와 root glass 테두리가 모서리에서 이중으로 보임.
  - titlebar 영역에 Liquid Glass 비침 효과가 충분히 적용되지 않음.
- 원인 추정:
  - 투명 window + full glass background 구조에서 빈 영역을 소비하는 hit-test view가 없었음.
  - content가 window bounds에 너무 붙어 glass halo/border가 clipping됨.
  - `NSGlassEffectView` 자체 corner radius와 native rounded window corner가 겹쳐 보임.
  - titlebar를 일반 titlebar로 남겨 native title 영역과 Liquid Glass shell이 분리되어 보임.
- 조치:
  - `RemoteWindowHitTestShield` / `RemoteHitTestShieldView`를 추가해 window 내부 빈 영역 hit-test를 소비하도록 함.
  - `RemoteWindowLayout`에 `glassOuterInset`, `glassHaloAllowance`, `titlebarReserveHeight`를 추가하고 content size 계산에 반영함.
  - dashboard content를 titlebar reserve + glass-safe inset 안쪽에 배치함.
  - window style에 `.fullSizeContentView`, `titleVisibility = .hidden`, `isMovableByWindowBackground = true`를 적용함.
  - AppKit root `NSGlassEffectView` corner radius를 0으로 두어 native window corner와 내부 glass border가 중복되지 않게 함.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.
  - `./.venv/bin/python -m pytest -q tests/test_remote_macos_client_static.py` 통과.
- 남은 확인:
  - 실제 앱에서 빈 영역 click-through/scroll-through가 사라졌는지 수동 검수 필요.
  - titlebar/traffic light 주변 glass 시각 품질 수동 검수 필요.

---

## Issue 3 — image copy 7 기준 vertical scroll/sidebar overflow/titlebar 잔여 문제와 자동 캡처 제한

- 상태: 코드 대응 완료, 자동 캡처 환경 제한 기록
- 발생 시점: image copy 7 실기기 검수 후 Ralph-loop 재개
- 증상:
  - dashboard 내부에서 vertical scrolling이 여전히 발생함.
  - titlebar가 불투명한 단색처럼 보이고 상단 여백이 과도함.
  - 좌측 sidebar의 하단 `설정 열기` 영역이 창 아래로 삐져나가거나 잘림.
  - `/Applications` 설치 없이 임시 `.app`로 검수하려 했으나 현재 자동화 환경에서 `screencapture`가 `could not create image from display`로 실패함.
- 원인 추정:
  - 메인 dashboard에 남아 있던 외부 vertical `ScrollView`가 고정 크기 window 안에서 불필요한 세로 스크롤을 만들었음.
  - titlebar reserve가 56pt로 과도하게 커서 black/opaque titlebar처럼 보이는 빈 영역을 키웠음.
  - sidebar 내부에 다시 `ScrollView`와 nested glass group들이 있어 compact window 높이에서 하단 항목이 잘리기 쉬웠음.
  - Codex 실행 환경은 GUI app launch 자체는 가능했지만, display capture 권한 또는 세션 제약 때문에 화면 이미지를 생성하지 못했음.
- 조치:
  - `RemoteDashboardView` 외부 vertical `ScrollView`와 `.scrollClipDisabled()`를 제거하고 고정 `VStack` 레이아웃으로 전환함.
  - horizontal game card drag scroll은 유지해 게임 목록의 좌우 이동 기능은 보전함.
  - `titlebarReserveHeight`를 56pt에서 18pt로 줄여 traffic light 주변 최소 여백만 남김.
  - sidebar를 `RemoteGlassGroupBox` 3단 구조에서 단일 native-style section 구조로 단순화하고 sidebar 내부 `ScrollView`를 제거함.
  - sidebar가 펼쳐진 상태에서는 `sidebarMinimumHeight`를 window size 계산에 반영해 하단 앱 섹션이 compact height에 잘리지 않게 함.
  - UI 검수 루프용 숨은 실행 인자 `--ui-test-show-window`, `--ui-test-show-sidebar`, `--ui-test-show-summary` 및 대응 환경변수를 추가함. 일반 실행에서는 sidebar hidden-by-default 동작을 유지함.
  - `/Applications` 설치/암호 입력 없이 `/tmp/hh-remote-ralph/HomeworkHelperRemote.app` 임시 번들로 release 패키징 및 실행 검증을 수행함.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.
  - `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_build_release.py -q` 통과.
  - `./.venv/bin/python tools/package_macos_remote_app.py --output-dir /tmp/hh-remote-ralph --version 0.2.0 --build 4 --jobs 4` 통과.
  - 임시 패키지 실행 명령 `open -n /tmp/hh-remote-ralph/HomeworkHelperRemote.app --args --ui-test-show-window --ui-test-show-sidebar --ui-test-show-summary`로 프로세스 실행 확인.
- 남은 확인:
  - 현재 자동화 세션의 display capture 실패로 새 스크린샷의 시각 판정은 완료하지 못함.
  - 동일 세션에서 CoreGraphics window metadata query도 `count=0`을 반환했다. app process 자체는 실행됐으므로, 이 환경에서는 화면/윈도우 관찰 권한 또는 GUI 세션 제약을 blocker로 기록한다.
  - 사용자가 빌드된 앱에서 image copy 7의 세로 스크롤/상단 여백/sidebar clipping이 해소됐는지 실기기 재검수 필요.

---

## Issue 4 — GUI 검수 모드에서도 Keychain/외부 상태 접근으로 암호 프롬프트 발생

- 상태: 코드 대응 완료, 자동 캡처는 여전히 권한 제약
- 발생 시점: `/tmp/hh-remote-ralph/HomeworkHelperRemote.app` 임시 실행으로 Ralph-loop를 재개하는 중
- 증상:
  - `/Applications` 설치를 피했는데도 실행 시 암호 입력 창이 계속 표시됨.
  - 직접 암호를 입력하지 않는 한 자동 GUI loop 진행이 막힘.
- 원인:
  - `RemoteSharedModel.viewModel` 생성 시 기본 `KeychainTokenStore`가 즉시 `SecItemCopyMatching`을 호출함.
  - 이후 bootstrap에서 Tailscale/network/remote 상태 점검도 실행되어 GUI 외부 상태에 접근함.
  - GUI 품질 검수 목적에서는 실제 pairing/token/network 상태가 필요하지 않으므로, 이 접근은 검수 루프에 불필요한 blocker였음.
- 조치:
  - `RemoteUITestFlags`를 추가해 `--ui-test-show-window`, `--ui-test-show-sidebar`, `--ui-test-show-summary`, `--ui-test-no-external-state`와 대응 환경변수를 한 곳에서 관리함.
  - UI test/external-state-skip 모드에서는 `InMemoryTokenStore(initialToken: "ui-test-token")`를 사용해 Keychain read/write를 하지 않게 함.
  - 같은 모드에서는 `bootstrap()`/`refresh()`/`startMirroring()`이 네트워크·Tailscale·Keychain 기반 동기화 대신 `applyUITestSnapshot()` 샘플 데이터만 표시하게 함.
  - `RemoteLoginItemManager.isEnabled` 조회도 UI test/external-state-skip 모드에서는 건너뛰게 함.
  - 중간에 수동 `NSWindow` fallback을 추가했다가 SwiftUI Window와 중복되어 2개의 메인 창이 생기는 것을 확인함.
  - 최종적으로 UI test 모드의 일반 SwiftUI Window scene은 1x1 placeholder를 표시하고, 실제 검수용 dashboard는 수동 `NSWindow` 하나로 열도록 분리해 `mainWindowLikeCount=1`로 안정화함.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.
  - `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_build_release.py -q` 통과.
  - 임시 패키지 실행 시 `artifacts/gui-loop-20260515-233038-windows.txt`에 `mainWindowLikeCount=1` 기록.
  - 각 GUI loop 산출물은 프로젝트 루트 `./artifacts/` 아래에 저장하도록 변경.
- 남은 확인:
  - 현재 세션에서는 `screencapture`가 full display/window capture 모두 실패한다.
    - full display: `could not create image from display`
    - window: `could not create image from window`
  - 따라서 새 PNG 이미지는 생성하지 못했고, 대신 `./artifacts/gui-loop-*-process.txt`, `./artifacts/gui-loop-*-windows.txt`, `./artifacts/gui-loop-*-screencapture.err`를 남겼다.

## Issue 5 — 화면 기록 권한 부여 후 GUI polish Ralph-loop 재개

- 상태: 코드 대응 및 자동 스크린샷 판정 완료
- 발생 시점: 사용자가 IDE 앱에 화면 기록 권한을 부여한 뒤 재개한 GUI 품질 검수
- 기준 스크린샷:
  - `artifacts/gui-loop-20260516-000308.png` — 수정 전 기준: 큰 창, 넓은 상단/titlebar 영역, glass wrapper에 갇힌 sidebar, 과도한 card/summary 여백.
  - `artifacts/gui-loop-20260516-000552.png` — 1차 compact pass: sidebar와 게임 card는 개선됐지만 play summary 하단이 잘림.
  - `artifacts/gui-loop-20260516-000753.png` — play summary compact pass: 요약 잘림 해소, 다만 상단 safe-area 여백이 아직 큼.
  - `artifacts/gui-loop-20260516-001041.png` — 3차 pass: titlebar safe-area를 content가 침범하도록 조정해 상단 불투명/빈 영역을 줄이고 전체 레이아웃을 고정 compact window에 맞춤.
  - `artifacts/gui-loop-20260516-001239.png` — 최종 package build 15 재확인: 테스트/패키징 이후 동일 레이아웃이 유지됨.
- 증상:
  - 창 전체가 실제 정보량 대비 넓고 높게 느껴짐.
  - sidebar가 Apple original sidebar라기보다 별도 glass card처럼 보여 앱 전체 구조가 무거움.
  - sidebar 전원 버튼이 작은 square grid라 native macOS control 느낌이 약함.
  - 게임 section과 play summary section이 동일한 content 폭을 쓰더라도 내부 spacing 때문에 compact하게 느껴지지 않음.
  - titlebar/safe-area가 여전히 불투명한 상단 띠처럼 보여 Liquid Glass shell과 분리되어 보임.
- 조치:
  - `RemoteWindowLayout`의 sidebar, game card, content padding, glass inset/halo, compact height 값을 줄여 고정 window footprint를 축소함.
  - sidebar의 `remoteGlass(.section)` wrapper를 제거하고, native split-view에 가까운 plain sidebar + divider 구조로 회귀함.
  - sidebar 전원 버튼을 `Grid` + `.buttonStyle(.bordered)` 기반 `SidebarPowerButton`으로 바꿔 label+SF Symbol이 있는 macOS 기본 control 형태에 가깝게 정리함.
  - main content padding과 `RemoteGlassGroupBox` padding/spacing/corner radius를 줄여 게임 section과 play summary의 체감 밀도를 높임.
  - game card width/height/icon 크기와 horizontal viewport 높이를 줄여 4개 card가 한 화면에 더 compact하게 들어오도록 조정함.
  - play summary를 4개 metric + 단일 mobile 자연어 row로 압축해 작은 높이에서도 잘리지 않게 함.
  - root dashboard에 아주 약한 highlight overlay를 추가하고, content HStack에 top safe-area ignore를 적용해 titlebar 영역과 glass content가 더 자연스럽게 이어지게 함.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.
  - `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_build_release.py -q` 통과.
  - `/tmp/hh-remote-ralph/HomeworkHelperRemote.app` 임시 package build 15를 실행하고 `artifacts/gui-loop-20260516-001239.png`를 직접 시각 확인함.
- 남은 확인:
  - full-native macOS 26 Liquid Glass API 전환은 별도 계획서(`macos26-liquid-glass-upgrade-plan.md`)의 다음 단계로 유지한다.
  - 현재 단계는 AppKit `NSVisualEffectView`/glass compatibility 기반 polish이며, Apple 최신 native Liquid Glass와 완전히 동일한 시각 언어는 의도적으로 목표에서 제외했다.

## Issue 6 — image copy 8/9 기준 titlebar 착시, 표준 sidebar, 자동 창 크기 재정렬

- 상태: 코드 대응 및 단독 배경 자동 스크린샷 판정 완료
- 발생 시점: `image copy 8.png`, `image copy 9.png`, 사용자 제공 표준 sidebar 참고 이미지 검수 후
- 기준 스크린샷:
  - `image copy 8.png` — 색상 박스로 titlebar 단색 영역, 불필요한 main/sidebar 여백, power button 디자인 파괴 지점 표시.
  - `image copy 9.png` — sidebar hidden 상태에서 titlebar/상단 여백, main section alignment 문제 표시.
  - `artifacts/gui-loop-20260516-085259.png` — borderless 전환 1차 결과: titlebar strip 제거는 성공했지만 power button이 너무 크고 inactive window처럼 보임.
  - `artifacts/gui-loop-20260516-085548.png` — 2차 pass: 단독 배경에서 titlebar strip 제거, 표준 sidebar chrome, content-width alignment, 기존 blue launch button 복구를 확인.
  - `artifacts/gui-loop-20260516-090236.png` — 최종 build 18: sidebar/hidden 상태 공용 traffic controls 반영 후 최종 visual 확인.
- 증상:
  - 이전 검수는 IDE의 어두운 배경 때문에 titlebar가 투명하게 보인다는 착시가 있었음.
  - 실제 단독 배경에서는 native titlebar 영역이 단색 strip처럼 분리되어 보였음.
  - compact plain sidebar는 사용자가 원하는 표준 sidebar UX/Image #1과 거리가 있었음.
  - 2x2 sidebar power button은 기존 4-button compact row 디자인을 파괴했음.
  - 창 크기는 content를 모두 덮어야 하지만 게임 horizontal scroll 외 vertical scroll은 없어야 함.
- 조치:
  - main window를 borderless glass shell로 전환하고, sidebar 상단에 custom traffic-light chrome을 배치해 titlebar 단색 strip을 제거함.
  - `RemoteMainWindow` subclass를 추가해 borderless UI-test window도 key/main window가 되도록 보장함.
  - window/content corner radius를 native widget에 가까운 큰 rounded glass shell로 맞춤.
  - sidebar width와 game card 크기를 d69 계열 기준으로 되돌려 기존 정보 밀도와 card 균형을 복구함.
  - sidebar power control을 기존 compact 4-button row로 복구하고 fixed-size 처리해 glass button style이 폭을 임의 확장하지 못하게 함.
  - main content inset, header/game/summary section height 상수를 명시해 content 기반 자동 window sizing 기준을 재정렬함.
  - 캡처 루프는 `osascript`로 다른 창을 숨긴 뒤 단독 배경에서 수행하도록 바꿈.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.
  - `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_build_release.py -q` 통과.
  - `/tmp/hh-remote-ralph/HomeworkHelperRemote.app` build 18을 단독 배경에서 실행하고 `artifacts/gui-loop-20260516-090236.png`를 직접 시각 확인함.
- 남은 확인:
  - full-native macOS 26 Liquid Glass API로의 더 깊은 전환은 별도 계획서 후속 단계로 유지한다.
  - 실제 실서버 데이터에서 게임 수/문구가 더 많아지는 경우의 최대 화면 높이 fallback은 추가 수동 검수가 필요하다.

---

## Issue 7 — image copy 10 기준 낮은 QA 기준, native titlebar 텍스트, popover 검수 격리/정렬

- 상태: 코드 대응 및 신규 자동 스크린샷 3종 재검수 완료
- 발생 시점: `image copy 10.png` 및 직전 GUI QA 결과 재평가 후
- 기준 스크린샷:
  - `artifacts/gui-qa-visible-20260516-100559.png` — traffic light는 살아났지만 native titlebar에 `HomeworkHelper Remote` 텍스트가 남고, 상단 content reserve가 큼.
  - `artifacts/gui-qa-hidden-20260516-100559.png` — sidebar hidden 상태에서도 native titlebar 텍스트/상단 여백이 남음.
  - `artifacts/gui-qa-popover-20260516-100559.png` — popover 단독 검수는 가능했지만, popover 전용 window 격리/버튼 높이 계약이 정적으로 고정되어 있지 않았음.
  - `artifacts/gui-qa-visible-20260516-101858.png` — 수정 후 sidebar visible 상태 재검수.
  - `artifacts/gui-qa-hidden-20260516-101858.png` — 수정 후 sidebar hidden 상태 재검수.
  - `artifacts/gui-qa-popover-20260516-101858.png` — 수정 후 popover 단독 상태 재검수.
- 증상:
  - [합격] 기준을 “빌드/정적 테스트 통과”에 과도하게 의존하면, 실제 화면에서 보이는 titlebar text, traffic-light 주변 여백, 버튼 정렬 같은 product-level UX 회귀를 놓칠 수 있음.
  - macOS native `.titled + .fullSizeContentView`로 회귀하면서 traffic light clipping은 해결됐지만, window title text가 상단 chrome에 표시되어 liquid glass surface와 정보 hierarchy가 중복됨.
  - popover QA 모드는 SwiftUI placeholder/default window가 늦게 나타나는 경우를 반복적으로 닫는 방어가 부족했고, 하단 3버튼과 전원 버튼 row의 높이/폭 계약이 구조적으로 분리되어 있지 않았음.
- 조치:
  - main window title은 window identifier로만 추적하고, 실제 `NSWindow.title`은 빈 문자열로 설정해 native titlebar 텍스트를 제거함.
  - `titlebarContentInset`을 42pt에서 28pt로 축소해 traffic light 안전 영역은 유지하면서 상단 무의미 여백을 줄임.
  - popover UI-test window에 `settleUITestPopoverWindow` 반복 정리 루프를 추가해 늦게 뜨는 main/placeholder window를 지속적으로 숨김.
  - popover 전원 row는 30pt, footer row는 34pt 높이로 고정하고 `MenuBarFooterButton`을 별도 컴포넌트로 분리해 main sidebar power button 변경이 popover footer alignment를 다시 깨지 않게 함.
  - 정적 테스트를 “title hidden + native traffic light + no custom chrome + popover QA isolation + footer button component” 계약으로 갱신함.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.
  - `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_build_release.py -q` 통과 (`13 passed`).
  - `./.venv/bin/python tools/package_macos_remote_app.py --output-dir /tmp/hh-remote-ralph --version 0.2.0 --build 21 --jobs 4` 통과.
  - 단독 배경 GUI 캡처 3종 생성 및 직접 확인:
    - `artifacts/gui-qa-visible-20260516-101858.png`
    - `artifacts/gui-qa-hidden-20260516-101858.png`
    - `artifacts/gui-qa-popover-20260516-101858.png`
- 판정:
  - 이전 캡처에서 보이던 native titlebar text는 제거됨.
  - traffic light는 잘리지 않고 native 위치에 남음.
  - dashboard vertical scroll은 보이지 않으며, 게임 목록의 invisible horizontal scroll만 남음.
  - sidebar visible/hidden 모두 content clipping은 보이지 않음.
  - popover는 main window 없이 단독으로 캡처되며, power row/footer row의 버튼 간격과 높이가 일관됨.
- 남은 주의:
  - 이 단계는 “현재 NSGlassEffect/SwiftUI glass 기반 GUI를 d69 계열 layout에 최대한 맞추는 안정화”이며, macOS 26 full-native Liquid Glass API 전체 전환의 pixel-diff < 1% 목표는 별도 migration 단계에서 다시 판정해야 한다.
  - 실제 사용 데이터에서 게임명이 더 길거나 incident section이 추가되는 경우는 같은 GUI QA 3종 캡처 루프를 다시 실행해 확인해야 한다.

---

## Issue 8 — main GUI 최종 polish: width alignment, summary clipping, sidebar reference toggle

- 상태: Ralph-loop 3회 반복 후 코드 대응 및 캡처 검수 완료
- 발생 시점: 사용자가 `artifacts/gui-qa-visible-20260516-101858.png`, `artifacts/gui-qa-hidden-20260516-101858.png`에 표시한 오류와 `sidebar_reference_visible.png`/`sidebar_reference_hidden.png` reference 전달 후
- 기준 이미지:
  - 오류 표시 기준: `artifacts/gui-qa-visible-20260516-101858.png`, `artifacts/gui-qa-hidden-20260516-101858.png`
  - reference 기준: `sidebar_reference_visible.png`, `sidebar_reference_hidden.png`, `sidebar_reference.png`
  - 수정 후 검수 캡처:
    - 1차: `artifacts/gui-qa-visible-20260516-112243.png`, `artifacts/gui-qa-hidden-20260516-112243.png`
    - 2차: `artifacts/gui-qa-visible-20260516-113115.png`, `artifacts/gui-qa-hidden-20260516-113115.png`
    - 최종: `artifacts/gui-qa-visible-20260516-113650.png`, `artifacts/gui-qa-hidden-20260516-113650.png`
- 증상:
  - root glass와 native window frame이 동시에 rounded outer line을 만들어 모서리에 이중 외곽선처럼 보임.
  - `게임` section 내부 viewport 폭이 section padding을 고려하지 않아 4번째 card/right button이 잘림.
  - window height 산식이 실제 `RemoteGlassGroupBox` intrinsic height보다 작아 `플레이 요약` 하단 텍스트가 잘림.
  - 우상단 텍스트형 `[패널 보기/숨기기]` 버튼이 reference의 sidebar chrome 구조와 맞지 않음.
- 조치:
  - root `NSGlassEffectView`의 `cornerRadius`를 0으로 고정해 outer rounded outline은 native window frame 한 곳에서만 나오도록 조정함.
  - `RemoteWindowLayout.sectionInset`, `mainColumnWidth(cardCount:)`를 추가해 `게임`과 `플레이 요약`이 같은 outer width를 공유하게 함.
  - `gameSectionHeight`와 `summarySectionHeight`를 실제 group intrinsic height에 맞게 늘려 vertical scroll 없이 content를 모두 포함하게 함.
  - sidebar visible 상태에는 `SidebarChromeRow` 우측 icon-only toggle을, hidden 상태에는 titlebar 좌측 icon-only reveal toggle을 배치함.
  - toggle button은 `.buttonStyle(.glass)` 기본 최소 크기 대신 plain button + 작은 native glass surface로 고정해 reference에 가까운 크기로 줄임.
- 검증:
  - 1차 Ralph-loop: 폭/높이 문제는 개선됐지만 toggle button이 너무 크고 낮게 배치됨.
  - 2차 Ralph-loop: 위치는 개선됐지만 `.glass` 기본 button 크기 때문에 hidden 상태에서 title과 겹침.
  - 3차 Ralph-loop: `artifacts/gui-qa-visible-20260516-113650.png`, `artifacts/gui-qa-hidden-20260516-113650.png` 직접 확인.
- 판정:
  - `게임`과 `플레이 요약` section의 좌우 끝이 정렬됨.
  - 4번째 game card/right edge 및 실행 버튼이 잘리지 않음.
  - `플레이 요약` 하단 mobile summary text가 잘리지 않음.
  - 우상단 text toggle이 사라지고 reference형 icon-only sidebar control로 대체됨.
  - popover는 합격 상태를 유지하기 위해 변경하지 않음.

---

## Issue 8 — sidebar reference visible/hidden 기준 titlebar toggle, section 폭, summary 하단 잘림 마감

- 상태: Ralph-loop 2회 수행 후 코드 대응 및 직접 캡처 판정 완료
- 발생 시점: 사용자가 `sidebar_reference_visible.png`, `sidebar_reference_hidden.png`를 추가하고, 기존 오류 표시 이미지가 `artifacts/gui-qa-visible-20260516-101858.png`, `artifacts/gui-qa-hidden-20260516-101858.png`임을 재확인한 뒤
- 공식 참고:
  - Apple HIG Sidebars: sidebar는 Liquid Glass layer 위에 떠 있는 navigation surface로 다뤄야 한다.
  - Apple HIG Toolbars: sidebar 표시/숨김처럼 현재 view를 제어하는 요소는 toolbar/titlebar leading side에 배치하는 것이 자연스럽다.
  - AppKit `NSTitlebarAccessoryViewController`: titlebar/toolbar 영역에 custom accessory view를 배치하는 공식 표면을 제공한다. 이번 구현은 같은 의도에 맞춰 titlebar/frame 영역의 작은 AppKit overlay로 sidebar toggle을 window chrome에 붙였다.
- 기준 스크린샷:
  - 수정 전 오류 표시: `artifacts/gui-qa-visible-20260516-101858.png`, `artifacts/gui-qa-hidden-20260516-101858.png`
  - reference: `sidebar_reference_visible.png`, `sidebar_reference_hidden.png`, `sidebar_reference.png`
  - 1차 loop: `artifacts/gui-qa-visible-20260516-112243.png`, `artifacts/gui-qa-hidden-20260516-112243.png`
  - 2차 loop: `artifacts/gui-qa-visible-20260516-114537.png`, `artifacts/gui-qa-hidden-20260516-114537.png`
- 증상:
  - 1차 loop에서 section 폭/하단 잘림은 개선됐지만 SwiftUI content 내부 sidebar button이 reference보다 너무 크고 낮았으며, hidden 상태에서는 제목을 침범했다.
  - 게임 section과 플레이 요약 section은 동일 width 기준을 명시하지 않아 향후 padding 변경 시 다시 어긋날 위험이 있었다.
  - root glass corner radius와 native window corner가 동시에 outline을 만들며 모서리 이중 외곽선이 보였다.
- 조치:
  - `RemoteWindowLayout.mainColumnWidth`와 `sectionInset`을 도입해 게임 section과 플레이 요약 section의 outer width 기준을 단일화함.
  - game/summary section height와 window content height 산식을 보정해 4번째 카드 우측 잘림과 summary 하단 잘림을 해소함.
  - root `NSGlassEffectView` corner radius를 0으로 두어 native window frame과 glass background가 각각 외곽선을 그리지 않게 함.
  - SwiftUI 본문 안의 텍스트형/큰 sidebar toggle을 제거하고, `HomeworkHelperRemoteSidebarToggleOverlay` AppKit overlay를 window frame/titlebar 영역에 설치함.
  - visible 상태는 sidebar 오른쪽 위, hidden 상태는 traffic light 오른쪽에 icon-only sidebar button이 오도록 위치를 분리함.
- 검증:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 통과.
  - `/tmp/hh-remote-ralph/HomeworkHelperRemote.app` build 23을 실행하고 다른 창을 최소화한 뒤 visible/hidden 캡처를 생성함.
  - 직접 시각 확인:
    - `artifacts/gui-qa-visible-20260516-114537.png`: sidebar toggle이 sidebar chrome 오른쪽 위에 있으며, 게임/플레이 요약 폭과 우측 카드 잘림이 개선됨.
    - `artifacts/gui-qa-hidden-20260516-114537.png`: reveal toggle이 traffic light 오른쪽 titlebar 영역에 있고 제목을 침범하지 않음.
- 판정:
  - Popover는 이전 합격 상태 유지.
  - 메인 visible/hidden 모두 기존에 표시된 게임 우측 잘림, 플레이 요약 하단 잘림, 우상단 텍스트형 panel button 문제는 해결됨.
  - 모서리 외곽선은 native frame 중심으로 정리됐으며, 내부 section/card outline은 유지됨.

### Issue 8 follow-up — sidebar toggle 중복 제거 최종 확인

- 상태: AppKit titlebar overlay만 남기고 SwiftUI content overlay 제거 후 최종 캡처 검수 완료
- 기준 캡처:
  - `artifacts/gui-qa-visible-20260516-120939.png`
  - `artifacts/gui-qa-hidden-20260516-120939.png`
- 추가 증상:
  - 이전 final 후보 hidden capture에서 SwiftUI overlay button과 AppKit frame overlay button이 동시에 남아 sidebar icon이 이중으로 보일 수 있었다.
- 조치:
  - sidebar 표시/숨김 control은 `HomeworkHelperRemoteSidebarToggleOverlay` AppKit overlay 한 곳에서만 담당하도록 정리했다.
  - SwiftUI 내부 `SidebarChromeRow`/`SidebarToggleChromeButton`과 hidden overlay를 제거했다.
  - visible sidebar content 시작 offset은 유지해 traffic light/titlebar 영역과 본문이 겹치지 않도록 했다.
- 판정:
  - latest visible/hidden capture에서 sidebar button은 각각 1개만 표시된다.
  - 게임 section과 플레이 요약 section의 폭 정렬, 4번째 card 표시, summary 하단 텍스트 표시가 유지된다.
  - popover는 합격 상태를 유지하기 위해 변경하지 않았다.
