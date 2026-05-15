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
