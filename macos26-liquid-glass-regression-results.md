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

---

## 10. image copy 8/9 및 표준 sidebar 재정렬 검증 기록

- [x] titlebar 단색 strip 제거
  - 테스트 방법: 다른 창을 숨긴 단독 배경에서 GUI loop를 실행하고 최종 스크린샷을 판독.
  - 테스트 결과: `artifacts/gui-loop-20260516-090236.png`에서 native titlebar strip 없이 custom traffic-light chrome이 glass shell 내부에 표시됨.
  - 통과 판정 근거: 어두운 IDE 배경 착시 없이도 상단 영역이 별도 단색 titlebar가 아니라 app glass surface 일부로 이어진다.

- [x] 표준 sidebar 방향 전환
  - 테스트 방법: sidebar visible UI-test 상태에서 Image #1의 기준인 상단 traffic-light chrome + 독립 sidebar panel + divider 구조를 시각 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: sidebar는 별도 card wrapper가 아니라 window shell 내부의 왼쪽 column으로 정리됐고, 상단에 macOS chrome control과 panel icon이 배치됐다.

- [x] 기존 power button 디자인 복구
  - 테스트 방법: `image copy 8.png`의 빨간 영역과 비교해 2x2 expanded button이 아닌 4개 compact button row가 표시되는지 확인.
  - 테스트 결과: 통과.
  - 통과 판정 근거: `PowerSquareButton` row를 복원하고 `.fixedSize`로 glass style의 과확장을 막았다.

- [x] section alignment 및 자동 창 크기
  - 테스트 방법: 최종 스크린샷에서 game section과 play summary section의 leading/trailing이 동일 grid에 맞는지 확인하고, static test에서 explicit layout constants와 vertical ScrollView 부재를 검증.
  - 테스트 결과: 통과.
  - 통과 판정 근거: main content inset과 section width가 공통 산식을 사용하며, game horizontal scroll 외 메인/sidebar vertical ScrollView가 없다.

- [x] no-external-state GUI loop 유지
  - 테스트 방법: build 18 app을 `--ui-test-show-window --ui-test-show-sidebar --ui-test-show-summary --ui-test-no-external-state`로 실행.
  - 테스트 결과: 통과.
  - 통과 판정 근거: Keychain/password prompt 없이 sample snapshot이 표시됐고 `artifacts/gui-loop-20260516-090236.png`가 생성됐다.

---

## 8. product-level GUI QA 기준 상향 및 image copy 10 후속 검증 기록

작성일: 2026-05-16

### 8.1 합격 기준 재정의

이번 항목부터 GUI 품질 판정은 다음 조건을 모두 만족해야 “통과”로 기록한다.

- [x] 빌드/정적 테스트만으로 GUI 품질을 통과 처리하지 않는다.
  - 테스트 방법: 실제 패키지 `.app`을 실행하고 sidebar visible, sidebar hidden, popover 단독 3종 스크린샷을 매번 `artifacts/`에 저장한다.
  - 테스트 결과: `artifacts/gui-qa-visible-20260516-101858.png`, `artifacts/gui-qa-hidden-20260516-101858.png`, `artifacts/gui-qa-popover-20260516-101858.png` 생성.
  - 통과 판정 근거: 세 캡처를 직접 확인해 traffic light, titlebar, sidebar, section alignment, popover footer alignment를 별도로 판정했다.

- [x] native traffic light는 잘리거나 custom clone으로 대체되지 않아야 한다.
  - 테스트 방법: `RemoteWindowAccessor`가 native `.titled/.fullSizeContentView`를 사용하고 `SidebarChromeRow`/`WindowChromeButton` custom chrome이 없는지 정적 확인. 실제 visible/hidden 캡처에서 좌상단 traffic light 확인.
  - 테스트 결과: 정적 테스트 통과, 최신 캡처 2종에서 traffic light 3개가 모두 안전하게 표시됨.
  - 통과 판정 근거: custom traffic light로 인한 clipping 회귀를 제거했고, native window control이 창 모서리 안쪽에 위치한다.

- [x] titlebar에는 중복 window title text가 없어야 한다.
  - 테스트 방법: `RemoteWindowAccessor`와 `prepareMainWindow`가 `window.title = ""`를 적용하는지 정적 확인. 최신 캡처에서 상단 title text 부재 확인.
  - 테스트 결과: 정적 테스트 통과, `gui-qa-visible-20260516-101858.png`/`gui-qa-hidden-20260516-101858.png`에서 native titlebar title text가 보이지 않음.
  - 통과 판정 근거: 앱 내부 header의 `HomeworkHelper Remote`만 정보 hierarchy를 담당하고 native chrome에는 중복 텍스트가 없다.

- [x] dashboard는 게임 horizontal invisible scroll 외 vertical scroll이 없어야 한다.
  - 테스트 방법: `RemoteDashboardView`와 `RemoteSidebarView` 범위에 vertical `ScrollView`가 없는지 정적 확인. 최신 visible/hidden 캡처에서 content clipping/vertical scrollbar 부재 확인.
  - 테스트 결과: 정적 테스트 통과, 최신 캡처에서 vertical scrollbar가 보이지 않음.
  - 통과 판정 근거: 창 크기는 content size 산식으로 결정되고, 세로 overflow를 ScrollView로 숨기지 않는다.

- [x] sidebar visible/hidden 양쪽 모두 content가 잘리지 않아야 한다.
  - 테스트 방법: sidebar visible 캡처에서 설정 버튼/전원 버튼/연결 섹션 확인, hidden 캡처에서 game + summary section 확인.
  - 테스트 결과: `gui-qa-visible-20260516-101858.png`에서 sidebar 하단 설정 버튼이 잘리지 않고, `gui-qa-hidden-20260516-101858.png`에서 play summary 하단 텍스트가 창 안에 들어옴.
  - 통과 판정 근거: `sidebarMinimumHeight`, `titlebarContentInset`, section height 산식이 현재 샘플 데이터 전체를 포함한다.

- [x] popover는 main window 없이 단독 검수 가능해야 하며 footer 버튼 정렬이 보존되어야 한다.
  - 테스트 방법: `--ui-test-show-popover`로 popover 전용 window를 띄우고 `settleUITestPopoverWindow`가 다른 large window를 반복적으로 `orderOut`하는지 확인. 최신 popover 캡처에서 main window 부재/버튼 row 정렬 확인.
  - 테스트 결과: `gui-qa-popover-20260516-101858.png`에서 main window 없이 popover만 표시됨. power row/footer row가 각각 고정 높이와 동일 spacing을 사용함.
  - 통과 판정 근거: popover QA가 main dashboard 상태에 오염되지 않고, `MenuBarFooterButton` 분리로 footer alignment가 main/sidebar 컴포넌트 변경에 종속되지 않는다.

### 8.2 자동 검증

- [x] Swift build
  - 테스트 방법: `swift build --package-path remote_clients/macos/HomeworkHelperRemote`
  - 테스트 결과: 통과.
  - 통과 판정 근거: native titled glass shell, title hiding, popover QA window, footer component 변경이 모두 컴파일됨.

- [x] targeted pytest
  - 테스트 방법: `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py tests/test_build_release.py -q`
  - 테스트 결과: `13 passed`.
  - 통과 판정 근거: macOS static GUI contract와 packaging contract가 함께 통과함.

- [x] release packaging smoke
  - 테스트 방법: `./.venv/bin/python tools/package_macos_remote_app.py --output-dir /tmp/hh-remote-ralph --version 0.2.0 --build 21 --jobs 4`
  - 테스트 결과: 통과.
  - 통과 판정 근거: 실제 검수용 `.app` bundle 생성과 icon resource packaging이 정상 완료됨.

---

## 9. main GUI 최종 polish Ralph-loop 결과

작성일: 2026-05-16

- [x] 오류 표시 기준 이미지 확인
  - 테스트 방법: 사용자가 표시한 오류 기준이 프로젝트 루트 이미지가 아니라 `artifacts/gui-qa-visible-20260516-101858.png`, `artifacts/gui-qa-hidden-20260516-101858.png`임을 확인하고 기준으로 삼음.
  - 테스트 결과: 확인 완료.
  - 통과 판정 근거: 수정 전/후 비교 대상을 artifacts 내 캡처로 고정했다.

- [x] sidebar reference 반영
  - 테스트 방법: `sidebar_reference_visible.png`, `sidebar_reference_hidden.png`, `sidebar_reference.png`를 직접 확인하고 sidebar toggle 배치를 조정.
  - 테스트 결과: visible 상태는 sidebar chrome 우측 icon-only hide button, hidden 상태는 titlebar 좌측 icon-only reveal button으로 변경.
  - 통과 판정 근거: 우상단 텍스트형 panel button이 제거되고 reference와 같은 icon-only 동작 구조가 됐다.

- [x] 게임/플레이 요약 폭 정렬
  - 테스트 방법: `mainColumnWidth(cardCount:)` 공통 산식을 도입하고 최종 캡처를 확인.
  - 테스트 결과: `artifacts/gui-qa-visible-20260516-113650.png`, `artifacts/gui-qa-hidden-20260516-113650.png`에서 section 좌우 끝이 정렬됨.
  - 통과 판정 근거: game viewport에 section padding을 포함한 window width 산식을 사용한다.

- [x] 플레이 요약 하단 잘림 해소
  - 테스트 방법: summary section height/window height 산식을 보정하고 최종 캡처 확인.
  - 테스트 결과: 최종 visible/hidden 캡처 모두 mobile summary text가 창 안에 표시됨.
  - 통과 판정 근거: vertical scroll 없이 content가 모두 들어간다.

- [x] Ralph-loop 수행
  - 테스트 방법: 수정 후 매회 다른 창 최소화 → 앱 실행 → `artifacts/` 캡처 저장 → 직접 시각 확인 → 재수정 루프 수행.
  - 테스트 결과: 3회 반복 후 최종 캡처 `gui-qa-visible-20260516-113650.png`, `gui-qa-hidden-20260516-113650.png` 확보.
  - 통과 판정 근거: 사용자가 요청한 수정/캡처/시각 피드백 루프를 따랐다.

---

## 9. sidebar reference visible/hidden 반영 후 Ralph-loop 검증 기록

작성일: 2026-05-16

- [x] sidebar visible 기준 반영
  - 테스트 방법: `sidebar_reference_visible.png`를 기준으로 visible 상태를 실행하고 `artifacts/gui-qa-visible-20260516-114537.png`를 직접 확인.
  - 테스트 결과: sidebar hide control이 우상단 텍스트 버튼이 아니라 sidebar chrome의 icon-only control로 이동했다.
  - 통과 판정 근거: reference처럼 traffic light row와 같은 window chrome 영역에서 sidebar control이 보이며, main header 우상단에는 더 이상 패널 텍스트 버튼이 없다.

- [x] sidebar hidden 기준 반영
  - 테스트 방법: `sidebar_reference_hidden.png`를 기준으로 hidden 상태를 실행하고 `artifacts/gui-qa-hidden-20260516-114537.png`를 직접 확인.
  - 테스트 결과: reveal control이 traffic light 오른쪽 titlebar 영역에 배치되고 title text를 침범하지 않는다.
  - 통과 판정 근거: hidden 상태에서도 버튼이 본문 header 위에 떠서 제목을 가리는 문제가 사라졌다.

- [x] 게임/플레이 요약 폭 정렬
  - 테스트 방법: `RemoteWindowLayout.mainColumnWidth`/`sectionInset` 정적 계약과 최신 visible/hidden 캡처를 확인.
  - 테스트 결과: 두 section은 같은 main column 산식을 사용하고, 최신 캡처에서 오른쪽 끝 정렬과 4번째 카드 표시가 안정적이다.
  - 통과 판정 근거: width 산식이 분리되어 다시 어긋나는 회귀 위험을 줄였다.

- [x] 플레이 요약 하단 잘림 해소
  - 테스트 방법: 최신 visible/hidden 캡처에서 summary 하단 line을 확인.
  - 테스트 결과: `모바일 40분...` 하단 텍스트가 창 안에서 온전히 표시된다.
  - 통과 판정 근거: `summarySectionHeight`와 window height 산식을 보정했다.

- [x] 모서리 이중 외곽선 완화
  - 테스트 방법: root `NSGlassEffectView` corner radius 0 계약과 최신 캡처 모서리를 확인.
  - 테스트 결과: native window frame과 root glass rounded border가 동시에 겹치는 현상이 완화됐다.
  - 통과 판정 근거: root glass는 배경만 담당하고, 외곽 rounding은 native window frame에 맡긴다.

### 9.1 sidebar toggle 중복 제거 최종 확인

- [x] visible 상태 sidebar chrome button 단일화
  - 테스트 방법: `/tmp/hh-remote-ralph/HomeworkHelperRemote.app` build 26을 `--ui-test-show-window --ui-test-show-sidebar --ui-test-show-summary`로 실행하고 다른 창을 최소화한 뒤 `artifacts/gui-qa-visible-20260516-120939.png`를 직접 확인.
  - 테스트 결과: sidebar 우상단 titlebar/frame 영역에 icon-only sidebar button이 1개만 표시된다.
  - 통과 판정 근거: SwiftUI content overlay를 제거하고 AppKit overlay만 유지해 reference형 window chrome control로 단일화했다.

- [x] hidden 상태 reveal button 단일화
  - 테스트 방법: 같은 build 26을 `--ui-test-show-window --ui-test-show-summary`로 실행하고 `artifacts/gui-qa-hidden-20260516-120939.png`를 직접 확인.
  - 테스트 결과: traffic light 오른쪽 titlebar 영역에 reveal button이 1개만 표시되며 제목 텍스트와 겹치지 않는다.
  - 통과 판정 근거: sidebar hidden overlay가 SwiftUI 본문과 AppKit frame에 중복 설치되지 않는다.

- [x] 최종 main GUI visual contract 유지
  - 테스트 방법: latest visible/hidden capture에서 section 폭, 4번째 game card, summary bottom line, outer frame을 확인.
  - 테스트 결과: 게임/플레이 요약 폭 정렬과 summary 하단 표시가 유지되고, popover 합격 영역은 변경하지 않았다.
  - 통과 판정 근거: 변경 범위를 sidebar toggle 중복 제거와 static contract 갱신으로 제한했다.

---

## 10. 재개 후 Apple sidebar/titlebar guidance 반영 검증 기록

작성일: 2026-05-16

- [x] SwiftUI content 내부 sidebar toggle 제거
  - 테스트 방법: `RemoteDashboardView`와 `RemoteSidebarView`에서 `SidebarChromeRow`/`SidebarToggleChromeButton`이 제거됐는지 정적 테스트로 확인.
  - 테스트 결과: targeted pytest에서 해당 문자열 부재 계약이 통과했다.
  - 통과 판정 근거: sidebar 표시/숨김 control이 content layout을 밀거나 header/title과 겹치는 구조를 제거했다.

- [x] AppKit titlebar/frame overlay 단일화
  - 테스트 방법: `RemoteWindowAccessor`가 `HomeworkHelperRemoteSidebarToggleOverlay`를 설치하고 `RemoteSidebarToggleTarget`으로 `.homeworkHelperRemoteToggleSidebar`를 post하는지 확인.
  - 테스트 결과: 정적 테스트 통과 및 최종 GUI 캡처에서 visible/hidden 양쪽 toggle 표시 확인.
  - 통과 판정 근거: 버튼 배치가 SwiftUI 본문이 아니라 window chrome 계층에서 수행되어 reference형 sidebar control에 더 가깝다.

- [x] hidden reveal button z-order 회귀 방지
  - 테스트 방법: 1차 캡처 `artifacts/gui-qa-hidden-20260516-121010.png`에서 reveal button 부재를 확인한 뒤, overlay `.above`/`zPosition` 보정 후 `artifacts/gui-qa-hidden-20260516-121437.png`를 재촬영.
  - 테스트 결과: 최종 hidden 캡처에서 traffic-light 오른쪽에 icon-only reveal button이 표시된다.
  - 통과 판정 근거: 실제 앱 실행/화면 캡처로 AppKit subview ordering 문제가 해결됐음을 확인했다.

- [x] main GUI section 폭/하단 clipping 유지
  - 테스트 방법: 최종 visible/hidden 캡처에서 게임 section 우측 카드, 플레이 요약 section 우측/하단, vertical scrollbar 부재를 직접 확인.
  - 테스트 결과: `artifacts/gui-qa-visible-20260516-121437.png`, `artifacts/gui-qa-hidden-20260516-121437.png` 모두 section 폭이 유지되고 하단 텍스트가 표시된다.
  - 통과 판정 근거: sidebar toggle 구조 변경이 이전에 해결한 section alignment와 summary clipping을 재발시키지 않았다.

---

## 11. Native NavigationSplitView/sidebar 전환 회귀 검증 기록

작성일: 2026-05-16

- [x] Native split-view shell 전환
  - 테스트 방법: `RemoteDashboardView`가 `NavigationSplitView(columnVisibility:)`를 사용하고, 수동 `HStack` sidebar overlay가 제거됐는지 정적 테스트로 확인.
  - 테스트 결과: targeted pytest 통과.
  - 통과 판정 근거: visible/hidden state가 native split-view column visibility로 관리된다.

- [x] Native source-list sidebar 구조
  - 테스트 방법: `RemoteSidebarView`가 `List` + `.listStyle(.sidebar)` + `Section("연결"/"PC 전원"/"앱")`로 구성됐는지 확인하고 최종 visible 캡처를 직접 확인.
  - 테스트 결과: `artifacts/gui-native-visible-20260516-195446.png`에서 sidebar가 Finder/사진 계열 source-list 구조로 표시된다.
  - 통과 판정 근거: custom glass card/sidebar wrapper 대신 native list row hierarchy를 사용한다.

- [x] Sidebar toggle continuity
  - 테스트 방법: visible/hidden 패키지 앱 캡처를 같은 loop에서 생성해 titlebar/sidebar toggle 위치 흐름을 비교.
  - 테스트 결과: `artifacts/gui-native-visible-20260516-195446.png`, `artifacts/gui-native-hidden-20260516-195446.png`에서 native sidebar toggle이 유지된다.
  - 통과 판정 근거: manual overlay button이 제거되어 상태별 버튼 디자인 차이와 수동 좌표 drift가 사라졌다.

- [x] Titlebar translucency regression
  - 테스트 방법: 패키지된 `.app` build 29를 직접 실행하고 titlebar가 불투명 단색으로 보이는지 확인.
  - 테스트 결과: 최종 visible/hidden 캡처에서 titlebar가 content glass와 이어지는 translucent surface로 표시된다.
  - 통과 판정 근거: root glass button style 전파를 제거하고 `window.toolbarStyle = .unified`로 조정했다.

- [x] 기존 기능/레이아웃 보존
  - 테스트 방법: targeted pytest, Swift build, 패키지 앱 캡처에서 게임 section, refresh, summary, sidebar hidden default, window sizing을 확인.
  - 테스트 결과: 게임/플레이 요약 폭 정렬과 summary 하단 표시가 유지되고, sidebar 전환 후에도 4번째 card가 잘리지 않는다.
  - 통과 판정 근거: main content 산식과 popover 컴포넌트는 유지하면서 shell/sidebar 구조만 native로 교체했다.
