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
