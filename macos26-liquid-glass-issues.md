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
