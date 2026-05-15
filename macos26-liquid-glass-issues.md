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
