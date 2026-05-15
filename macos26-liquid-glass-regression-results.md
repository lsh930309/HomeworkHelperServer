# macOS 26 Liquid Glass 전환 회귀 테스트 결과

작성일: 2026-05-15  
대상 변경: macOS 클라이언트 GUI를 macOS 26+ Liquid Glass API 기반으로 전환  
연계 문서:
- `macos26-liquid-glass-upgrade-plan.md`
- `macos-client-regression-checklist.md`
- `macos26-liquid-glass-issues.md`

---

## 1. 자동 검증 결과

- [x] Swift build
  - 테스트 방법: `swift build --package-path remote_clients/macos/HomeworkHelperRemote`
  - 테스트 결과: 통과. macOS SDK 26.5 / Swift 6.3.2 환경에서 build complete.
  - 통과 판정 근거: Swift compiler가 `glassEffect`, `GlassEffectContainer`, `NSGlassEffectView`, `NSGlassEffectContainerView`, `.buttonStyle(.glass)`, `.buttonStyle(.glassProminent)` 사용을 모두 수용했고 executable link까지 완료했다.

- [x] Python 전체 회귀 테스트
  - 테스트 방법: `./.venv/bin/python -m pytest -q`
  - 테스트 결과: `199 passed, 6 warnings`.
  - 통과 판정 근거: remote host API contract, pairing/token registry, power, icon payload, state revision, macOS static contract 등 기존 테스트 suite가 모두 통과했다.

- [x] macOS client 정적 계약 테스트
  - 테스트 방법: `./.venv/bin/python -m pytest -q tests/test_remote_macos_client_static.py`
  - 테스트 결과: `5 passed`.
  - 통과 판정 근거: macOS 26 deployment target, 단일 Window scene, single-window dedupe, Settings command, popover contract, icon/cache markers, Liquid Glass API markers, legacy `NSVisualEffectView`/`.thinMaterial` 제거 계약을 확인했다.

- [x] diff whitespace 검사
  - 테스트 방법: `git diff --check`
  - 테스트 결과: 통과.
  - 통과 판정 근거: trailing whitespace 또는 patch whitespace error가 없다.

---

## 2. Liquid Glass 전환 항목

- [x] macOS 26 이상 전용 target 전환
  - 테스트 방법: `Package.swift`와 정적 테스트 확인.
  - 테스트 결과: `platforms: [.macOS("26.0")]`로 변경됨.
  - 통과 판정 근거: `tests/test_remote_macos_client_static.py`가 `.macOS("26.0")` 존재와 `.macOS(.v13)` 부재를 검증한다.

- [x] SwiftUI Liquid Glass surface 도입
  - 테스트 방법: `RemoteLiquidGlass.swift`, `HomeworkHelperRemoteApp.swift` 정적 확인 및 Swift build.
  - 테스트 결과: `glassEffect`, `GlassEffectContainer`, `Glass.regular.tint(...).interactive(...)` 사용.
  - 통과 판정 근거: build 통과 및 정적 테스트가 `glassEffect`/`GlassEffectContainer` marker를 검증한다.

- [x] AppKit Liquid Glass host 도입
  - 테스트 방법: `RemoteLiquidGlass.swift` 정적 확인 및 Swift build.
  - 테스트 결과: `RemoteAppKitLiquidGlassBackground`가 `NSGlassEffectContainerView`와 `NSGlassEffectView`를 사용한다.
  - 통과 판정 근거: build 통과 및 정적 테스트가 `NSGlassEffectView`, `NSGlassEffectContainerView` marker를 검증한다.

- [x] legacy glass 제거
  - 테스트 방법: source grep / 정적 테스트.
  - 테스트 결과: `RemoteWindowAccessor.swift`에서 `NSVisualEffectView` 기반 `RemoteGlassBackground` 제거. 앱 코드에서 `.thinMaterial` 제거.
  - 통과 판정 근거: 정적 테스트가 `NSVisualEffectView` 부재, `RemoteGlassBackground` 부재, `.thinMaterial` 부재를 검증한다.

- [x] dashboard/sidebar/popover/settings section glass 적용
  - 테스트 방법: `RemoteGlassGroupBox`, `RemoteGameCard`, `HostStatusPill`, `MenuBarPopoverView`, `RemoteSettingsView` 정적 확인 및 build.
  - 테스트 결과: 기존 `GroupBox` 사용을 `RemoteGlassGroupBox`로 교체하고 주요 card/pill/popover/settings root에 glass surface 적용.
  - 통과 판정 근거: 정적 테스트가 실제 `GroupBox(` 부재와 `RemoteGlassGroupBox("연결")` 존재를 검증한다.

- [x] button glass style 적용
  - 테스트 방법: source grep / 정적 테스트 / build.
  - 테스트 결과: dashboard/settings/popover root와 주요 버튼에 `.buttonStyle(.glass)`, launch button에 `.buttonStyle(.glassProminent)` 적용.
  - 통과 판정 근거: 정적 테스트가 `.buttonStyle(.glass)`와 `.buttonStyle(.glassProminent)` 존재를 검증하고 build가 통과한다.

---

## 3. 기능 보전 회귀 항목 요약

- [x] 단일 메인 창 계약
  - 테스트 방법: macOS 정적 테스트에서 `Window(RemoteAppDelegate.mainWindowTitle, id: RemoteAppDelegate.mainWindowIdentifier)`, `WindowGroup(` 부재, `deduplicateMainWindows`, `prepareMainWindow`, `orderOut(nil)`, `.close()` 부재 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: Liquid Glass 전환 중 window scene/dedupe 코드는 유지됐고 정적 계약이 통과했다.

- [x] 메뉴바 / popover 계약
  - 테스트 방법: macOS 정적 테스트에서 `NSStatusItem`, `MenuBarPopoverView`, `popover.performClose(nil)`, clickCount 부재, popover buttons/spacing markers 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: status item과 popover toggle 구조가 유지되고 double-click 분기가 없다.

- [x] Settings 진입 계약
  - 테스트 방법: macOS 정적 테스트에서 `Settings`, `SettingsLink`, `showSettingsWindow:`, `showPreferencesWindow:`, Cmd+, shortcut 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: Settings scene과 메뉴 command fallback 구조가 유지됐다.

- [x] 키보드 shortcut 계약
  - 테스트 방법: macOS 정적 테스트에서 Cmd+R, Cmd+Shift+S, Cmd+W, Cmd+, marker 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: command menu와 shortcut source marker가 유지됐다.

- [x] sidebar 기본 숨김 / 재표시 숨김 계약
  - 테스트 방법: macOS 정적 테스트에서 `@State private var sidebarVisible = false`, `.onAppear { sidebarVisible = false }`, main window show notification handling 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: Liquid Glass 전환 중 상태 제어 로직이 유지됐다.

- [x] pairing/token robust contract
  - 테스트 방법: `./.venv/bin/python -m pytest -q` 및 macOS 정적 테스트에서 Keychain store, confirm/recover/refresh markers 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: host pairing/token registry tests와 macOS Keychain/recover source contract가 모두 통과했다.

- [x] status revision 기반 mirroring contract
  - 테스트 방법: full pytest의 remote status revision test, macOS 정적 테스트의 polling/revision markers 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: `state_revision` host contract와 client `latestStatus.stateRevision != lastStateRevision` marker가 유지됐다.

- [x] icon 품질/cache contract
  - 테스트 방법: full pytest의 `/remote/processes` icon variant tests, macOS 정적 테스트의 cache/display thumbnail markers 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: host icon payload와 client `displayThumbnailImage`, `decodedPixelDimension`, `icon.diagnostic` source contract가 유지됐다.

- [x] power/SSH/SmartThings contract
  - 테스트 방법: full pytest의 remote power tests, macOS 정적 테스트의 localWake/localSSH/SmartThings markers 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: host power endpoints와 client power gating/local fallback source contract가 유지됐다.

- [x] Android-PC/mobile session contract
  - 테스트 방법: full pytest의 game link/mobile session tests, macOS 정적 테스트의 Android settings markers 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: host API contract와 client view model methods/source markers가 유지됐다.

- [x] play summary / Beholder / natural ready-at text contract
  - 테스트 방법: full pytest의 dashboard/beholder tests, macOS 정적 테스트의 summary/progress natural language markers 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: dashboard summary, Beholder incidents, progress text conversion markers가 유지됐다.

---

## 4. 수동 검증 필요 항목

아래는 자동/정적 테스트로 구조 보전은 확인했지만 실제 사용감과 시각 품질은 수동 검증이 필요하다.

- [ ] Spotlight 반복 focus 전환 후 창이 실제로 1개만 보이는지
  - 테스트 방법: 앱 실행 후 Spotlight로 앱 focus 전환 5회 반복.
  - 테스트 결과: 미실행.
  - 통과 판정 근거: 미검증. 정적 계약은 통과했지만 수동 관찰 필요.

- [ ] Liquid Glass 시각 품질이 기대한 native glass에 가까운지
  - 테스트 방법: 메인 GUI, popover, Settings 스크린샷 비교.
  - 테스트 결과: 미실행.
  - 통과 판정 근거: 미검증. 실제 화면 검수 필요.

- [ ] Cmd+, / 메뉴바 설정 / sidebar 설정 버튼 실사용 동작
  - 테스트 방법: 빌드된 앱에서 각 진입 경로 직접 클릭/입력.
  - 테스트 결과: 미실행.
  - 통과 판정 근거: 미검증. 정적 계약은 통과했지만 UI event 수동 확인 필요.

- [ ] 페어링 완료 직후 popover status pill 즉시 반영
  - 테스트 방법: fresh pairing 후 popover를 열어 status label 확인.
  - 테스트 결과: 미실행.
  - 통과 판정 근거: 미검증. view model/source 계약은 유지됨.

- [ ] 실제 전원 버튼 wake/sleep/restart/shutdown 수행
  - 테스트 방법: 실제 host 환경에서 power config 후 각 버튼 실행.
  - 테스트 결과: 미실행.
  - 통과 판정 근거: 미검증. host/client contract tests는 통과.

---

## 5. 최종 판정

- 자동/정적 회귀: 통과
- Swift build: 통과
- 알려진 구현 중 문제: `macos26-liquid-glass-issues.md`에 기록, 현재 해결됨
- 수동 GUI 검수: 보류 항목 있음

최종 결론: 코드와 자동 회귀 기준에서는 Liquid Glass 전환이 완료되었으나, 실제 시각 품질 및 실기기 interaction은 사용자의 빌드 검수로 추가 확인이 필요하다.

---

## 6. image copy 6 피드백 대응 검증 기록

- [x] 섹션 테두리 잘림 대응
  - 테스트 방법: `RemoteWindowLayout`에 glass-safe inset/titlebar reserve/halo allowance가 content size에 포함되는지 정적 확인하고 Swift build 수행.
  - 테스트 결과: `glassOuterInset`, `glassHaloAllowance`, `titlebarReserveHeight`, `shellHorizontalInset`, `shellVerticalInset` 추가. Swift build 통과.
  - 통과 판정 근거: content가 창 경계에 붙지 않도록 window size와 내부 padding이 함께 조정됐고, 정적 테스트가 관련 marker를 검증한다. 실제 시각 품질은 수동 검수 필요.

- [x] click-through / scroll-through 대응
  - 테스트 방법: `RemoteWindowHitTestShield`와 `RemoteHitTestShieldView.hitTest` 구현을 정적 확인하고 Swift build 수행.
  - 테스트 결과: window bounds 내부 hit-test를 shield view가 소비하도록 구현. Swift build 통과.
  - 통과 판정 근거: 빈 영역에서 뒤 창으로 이벤트가 통과하던 원인을 차단하는 전용 AppKit hit-test layer가 root ZStack에 추가됐다. 실제 이벤트 체감은 수동 검수 필요.

- [x] 창 테두리와 glass 테두리 중복 대응
  - 테스트 방법: AppKit root `NSGlassEffectView` corner radius와 window shell 설정을 정적 확인.
  - 테스트 결과: root glass background corner radius를 0으로 변경하고 window native rounded corner에 맡김.
  - 통과 판정 근거: 내부 root glass border/radius와 native window corner가 이중으로 겹칠 가능성을 제거했다. 실제 모서리 시각 품질은 수동 검수 필요.

- [x] titlebar Liquid Glass 대응
  - 테스트 방법: `RemoteWindowAccessor` 정적 확인 및 Swift build 수행.
  - 테스트 결과: `.fullSizeContentView`, `titlebarAppearsTransparent`, `titleVisibility = .hidden`, `isMovableByWindowBackground = true` 적용.
  - 통과 판정 근거: native title text를 숨기고 content/glass가 titlebar 영역까지 확장될 수 있는 window shell로 전환했다. 실제 traffic light 주변 비침은 수동 검수 필요.

---

## 7. image copy 7 Ralph-loop 대응 검증 기록

- [x] dashboard vertical scroll 제거
  - 테스트 방법: macOS 정적 테스트에서 `RemoteDashboardView` 범위에 `ScrollView {` 및 `.scrollClipDisabled`가 없는지 확인하고 Swift build 수행.
  - 테스트 결과: 통과.
  - 통과 판정 근거: 메인 dashboard는 고정 `VStack` 레이아웃으로 전환됐고, horizontal game card scroll만 별도 `DraggableHorizontalScrollView`로 유지됐다.

- [x] sidebar overflow/clipping 완화
  - 테스트 방법: macOS 정적 테스트에서 `RemoteSidebarView` 범위의 `ScrollView` 부재, native-style `sidebarConnectionSection/sidebarPowerSection/sidebarAppSection`, nested `RemoteGlassGroupBox` 부재, `sidebarMinimumHeight` 기반 window height 산식을 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: sidebar는 단일 section 구조로 줄었고, 펼침 상태의 최소 높이가 window content size에 반영되어 하단 설정 버튼이 잘릴 위험을 줄였다.

- [x] titlebar 과도 여백 축소
  - 테스트 방법: `RemoteWindowAccessor.swift`에서 `titlebarReserveHeight`가 18pt로 줄었고 frame-level glass background가 유지되는지 확인한 뒤 Swift build 수행.
  - 테스트 결과: 통과.
  - 통과 판정 근거: 기존 56pt reserve로 생기던 넓은 불투명 상단 영역을 줄이고 full-size transparent titlebar 계약은 유지했다.

- [x] 암호 없는 GUI 검수 루프 기반 추가
  - 테스트 방법: release packaging을 `/tmp/hh-remote-ralph`에 수행하고 hidden UI-test launch arguments marker 및 package plist `LSMinimumSystemVersion=26.0`을 테스트로 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: `/Applications` 설치 없이 임시 app bundle을 실행할 수 있고, `--ui-test-show-window/sidebar/summary`로 수동 조작 없이 검수 상태를 요청할 수 있다. 일반 실행의 sidebar hidden-by-default는 `if !Self.showsSidebarForUITest` guard로 유지된다.

- [ ] 자동 스크린샷 기반 시각 판정
  - 테스트 방법: `screencapture -x /tmp/hh-remote-ralph/artifacts/iteration-*.png` 실행.
  - 테스트 결과: 실패 — `could not create image from display`; CoreGraphics window metadata query도 `count=0`.
  - 통과 판정 근거: 미통과. 코드/패키지 실행 검증은 완료했지만 현재 Codex GUI 세션의 display/window observation 제약 때문에 새 화면을 직접 판독하지 못했다.

---

## 8. GUI 검수 no-external-state 모드 검증 기록

- [x] GUI 검수 모드에서 Keychain 암호 프롬프트 회피
  - 테스트 방법: 정적 테스트에서 `RemoteUITestFlags.skipExternalState`, `InMemoryTokenStore(initialToken: "ui-test-token")`, `bootstrapEnabled: !RemoteUITestFlags.skipExternalState`, `guard bootstrapEnabled` marker를 확인하고 Swift build 수행.
  - 테스트 결과: 통과.
  - 통과 판정 근거: `--ui-test-*` 실행에서는 `KeychainTokenStore`를 쓰지 않고 샘플 snapshot을 표시하므로 GUI 품질 검수에 불필요한 Keychain/네트워크 접근을 차단한다.

- [x] GUI 검수 모드에서도 메인 창 1개 유지
  - 테스트 방법: 임시 packaged app을 `--ui-test-show-window --ui-test-show-sidebar --ui-test-show-summary --ui-test-no-external-state`로 실행하고 CoreGraphics window metadata를 `./artifacts/gui-loop-20260515-232134-windows.txt`에 기록.
  - 테스트 결과: `mainWindowLikeCount=1`.
  - 통과 판정 근거: UI test 모드에서 일반 SwiftUI Window를 1x1 placeholder로 축소하고 검수용 dashboard NSWindow만 main-like window로 남겨 중복 생성을 제거했다.

- [x] GUI loop artifact 저장 위치
  - 테스트 방법: GUI loop command가 `mkdir -p artifacts` 후 process/window/screencapture 결과를 `./artifacts/gui-loop-*`에 저장하는지 확인.
  - 테스트 결과: 통과. `artifacts/gui-loop-20260515-233038-*` 파일 생성.
  - 통과 판정 근거: 사용자가 요청한 프로젝트 루트 `./artifacts`에 loop별 증거 파일이 남는다. PNG 캡처는 현재 세션 권한 문제로 생성 실패했다.

- [ ] 자동 PNG 스크린샷
  - 테스트 방법: full display와 specific window ID 대상으로 `screencapture` 실행.
  - 테스트 결과: 실패 — `could not create image from display`, `could not create image from window`.
  - 통과 판정 근거: 미통과. 앱 실행과 창 1개 생성은 확인했지만, 현재 Codex/macOS 세션의 화면 캡처 권한 또는 display session 제약으로 PNG 생성은 불가했다.

---

## 9. 2026-05-16 GUI polish Ralph-loop 검증 기록

- [x] 화면 기록 권한 기반 자동 PNG 캡처
  - 테스트 방법: 임시 packaged app을 `--ui-test-show-window --ui-test-show-sidebar --ui-test-show-summary --ui-test-no-external-state`로 실행하고 `screencapture -x artifacts/gui-loop-*.png`를 수행한 뒤 이미지를 직접 판독.
  - 테스트 결과: `artifacts/gui-loop-20260516-000308.png`, `artifacts/gui-loop-20260516-000552.png`, `artifacts/gui-loop-20260516-000753.png`, `artifacts/gui-loop-20260516-001041.png`, `artifacts/gui-loop-20260516-001239.png` 생성 및 시각 확인 완료.
  - 통과 판정 근거: 이전 세션 blocker였던 `could not create image from display/window`가 해소됐고, loop별 시각 증거가 프로젝트 루트 `./artifacts`에 남았다.

- [x] sidebar Apple-original 방향 회귀
  - 테스트 방법: 최종 스크린샷에서 sidebar가 독립 glass card wrapper 없이 plain sidebar와 vertical divider로 보이는지 확인하고, 정적 테스트에서 `SidebarPowerButton` 및 `.buttonStyle(.bordered)` marker를 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: sidebar wrapper 제거로 좌측 panel이 native split-view에 가까워졌고, 전원 control은 label+symbol이 있는 bordered button grid로 바뀌어 square icon-only 느낌을 줄였다.

- [x] 고정 레이아웃 compactness와 section 폭 정렬
  - 테스트 방법: 최종 스크린샷에서 게임 section과 play summary section의 left/right edge가 같은 main content grid에 맞는지 확인하고, `RemoteWindowLayout.mainContentWidth/cardViewportWidth` 기반 산식과 static test marker를 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: content padding, card width/spacing, section padding이 줄었고 play summary는 동일한 main content width 안에서 하단 clipping 없이 표시된다.

- [x] play summary clipping 제거
  - 테스트 방법: `artifacts/gui-loop-20260516-000552.png`에서 보이던 하단 잘림을 기준으로 compact summary pass 후 `artifacts/gui-loop-20260516-000753.png` 및 최종 이미지를 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: mobile metrics를 한 줄 자연어 row로 접고 `summaryHeight`를 실제 compact content에 맞춰 조정해 섹션 하단 border와 텍스트가 잘리지 않는다.

- [x] titlebar/top safe-area 여백 축소
  - 테스트 방법: `RemoteWindowLayout.titlebarReserveHeight = 0`, `.fullSizeContentView`, `titlebarAppearsTransparent`, `.ignoresSafeArea(.container, edges: .top)` marker를 확인하고 최종 스크린샷에서 traffic light 주변과 content top gap을 시각 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: 별도 opaque titlebar reserve를 제거하고 content shell이 titlebar safe-area 위쪽까지 확장되어 이전보다 상단의 무의미한 검은 띠가 줄었다.

- [x] 기존 GUI 검수 no-external-state 회귀 방지
  - 테스트 방법: package build 15를 `--ui-test-no-external-state`로 실행하여 Keychain/password prompt 없이 sample snapshot으로 표시되는지 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: 최종 GUI loop가 암호 프롬프트 없이 진행됐고, 테스트용 샘플 데이터가 표시된 스크린샷이 생성됐다.
