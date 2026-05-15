# macOS 클라이언트 기반 기능 회귀 테스트 체크리스트

작성일: 2026-05-15  
목적: macOS 26+ full-native Liquid Glass 전환 작업 중 **기존 기반 기능 회귀를 빠짐없이 검증**하기 위한 체크리스트다.  
적용 대상: `remote_clients/macos/HomeworkHelperRemote`  
연계 계획서: `macos26-liquid-glass-upgrade-plan.md`

---

## 0. 사용 규칙 — 각 항목은 근거를 반드시 남긴다

Liquid Glass 전환 PR/커밋 검수자는 아래 모든 체크 항목에 대해 `테스트 방법`, `테스트 결과`, `통과 판정 근거`를 채워야 한다. 단순히 체크박스만 표시하는 것은 통과로 인정하지 않는다.

각 항목 작성 형식:

```md
- [ ] 기능명
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:
```

작성 원칙:

1. 자동 테스트로 검증한 경우 테스트 명령과 관련 테스트 파일/함수명을 적는다.
2. 수동 테스트로 검증한 경우 실행 환경, 조작 순서, 관찰 결과를 적는다.
3. 스크린샷으로 검증한 경우 파일명과 관찰 포인트를 적는다.
4. 해당 기능이 이번 변경과 무관해도 “변경 영향 없음”만 적지 말고, 최소한 정적 계약 또는 수동 관찰 근거를 적는다.
5. 실패/미검증 항목은 “통과” 처리하지 않는다. `미통과` 또는 `보류`로 남기고 이유를 쓴다.

---

## 1. 현재 구현 조사 근거

조사한 주요 파일:

- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/HomeworkHelperRemoteApp.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteDashboardViewModel.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteAPIClient.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteModels.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteClientCache.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteWindowAccessor.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/KeychainTokenStore.swift`
- `remote_clients/macos/HomeworkHelperRemote/Sources/HomeworkHelperRemote/RemoteLoginItemManager.swift`
- `tests/test_remote_macos_client_static.py`
- `tests/test_remote_routes.py`

기준 자동 테스트:

```bash
./.venv/bin/python -m pytest -q
swift build --package-path remote_clients/macos/HomeworkHelperRemote
```

주의:
- `./.venv/bin/python -m pytest -q`는 remote logging 테스트가 사용자 config backup 디렉터리에 쓸 수 있으므로 sandbox 밖 실행이 필요할 수 있다.
- Liquid Glass 전환 후 `swift build`는 Xcode 26/macOS 26 SDK 기준으로 수행해야 한다.

---

## 2. 앱 생명주기 / 창 관리 / 메뉴바 상주

- [ ] 메인 창은 항상 단일 인스턴스만 존재한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Spotlight로 앱 focus 전환을 5회 이상 반복해도 새 메인 창이 추가 생성되지 않는다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Dock 아이콘 클릭 또는 앱 reopen 경로는 popover toggle이 아니라 메인 창 focus/복원만 수행한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 메뉴바 아이콘 단일 클릭은 popover 표시/닫기만 수행한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 메뉴바 아이콘 click count 또는 더블클릭 분기 로직이 없다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] ESC 키 입력 시 메인 창이 숨겨지고 앱은 메뉴바 상주 상태로 남는다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Cmd+W 또는 메뉴바 > 원격 > 창 숨기기 동작이 메인 창을 숨긴다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 마지막 창이 닫혀도 앱이 종료되지 않는다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 로그인 자동 실행 설정이 유지되고, `로그인 자동 실행 시 창 표시` off 상태에서는 창 없이 메뉴바 상주로 시작한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `RemoteWindowAccessor`가 dashboard 메인 창에만 붙고 Settings 창과 popover는 메인 창 dedupe 대상이 아니다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 3. 메뉴 명령 / 키보드 단축키 / Settings 진입

- [ ] 메뉴바 > 원격 메뉴가 존재한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Cmd+R이 새로고침을 실행한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Cmd+Shift+S가 사이드바 표시/숨김을 토글한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 메뉴바 > 원격 > 창 열기가 메인 창을 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Cmd+,가 Settings 창을 연다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 메뉴바 > 원격 > 설정이 Settings 창을 연다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 사이드바 `[설정 열기]` 버튼이 Settings 창을 연다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Settings 진입은 `SettingsLink` 우선, AppKit fallback selector(`showSettingsWindow:`, `showPreferencesWindow:`) 보조 구조를 유지한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 4. Dashboard 레이아웃 / 핵심 시각 요소

- [ ] 앱 시작 시 사이드바는 기본 숨김 상태다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 창을 숨겼다가 다시 표시해도 사이드바는 숨김 상태로 재등장한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 사이드바를 표시했을 때 모든 항목, 특히 `[설정 열기]` 버튼에 좌측 padding이 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 메인 화면 상단 header에 연결 상태, host 상태, 사이드바 toggle, refresh action이 정상 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 게임 섹션 우측 상단 refresh 버튼은 icon-only로 유지되고 클릭 가능하다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 게임 horizontal scroll은 스크롤바 없이 마우스 드래그로 이동한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 게임 카드에는 게임 아이콘, 게임명, 실행/대기 상태, 오늘 실행 여부 indicator가 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 긴 게임명은 말줄임 없이 가능한 범위에서 자동 축소되어 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 게임 카드 실행 버튼이 `/remote/processes/{id}/launch` 경로를 통해 실행하고 이후 refresh한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 진행률이 있는 게임은 resource icon, progress bar, progress text를 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 진행률이 없는 게임은 “진행률 없음” 또는 상태 fallback을 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `플레이 요약 표시` off 상태에서는 Play Summary가 숨겨지고 창 높이가 compact하게 줄어든다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `플레이 요약 표시` on 상태에서는 총 플레이/일평균/세션/플레이 일수/모바일 요약이 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Beholder incident가 있을 때 Beholder 알림 섹션이 표시되고, 없을 때 빈 공간이 생기지 않는다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 5. 메뉴바 Popover

- [ ] Popover 상단에 “HomeworkHelper” 제목과 `HostStatusPill`이 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 페어링 완료 직후 popover 상태 pill이 즉시 `페어링됨` 등 현재 상태로 갱신된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 미페어링 상태에서는 `페어링 해제됨` 또는 적절한 상태가 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 호스트 offline 상태에서는 `오프라인/꺼져 있음` 상태가 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 로딩/refresh 중에는 `동기화 중` 상태가 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Popover에는 최대 5개 게임 row가 compact하게 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 게임이 5개 초과이면 “외 N개” 요약이 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Popover 게임 row에는 게임 아이콘, 이름, 실행/오늘 실행 indicator, 진행률 정보가 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Popover 원격 전원 관리 버튼 4개가 표시되고 enabled/disabled 상태가 power readiness와 일치한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Popover 하단 `[창 열기] [새로고침] [앱 종료]` 3개 버튼이 동일 spacing으로 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Popover `[창 열기]`는 메인 창을 표시하되 새 중복 창을 만들지 않는다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Popover `[새로고침]`은 refresh를 실행한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Popover `[앱 종료]`는 앱을 종료한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 6. Settings 화면 / 환경설정 persistence

- [ ] Settings 창은 탭 구조를 유지한다: 연결, 전원, 기기, Android, 앱.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 연결 탭에 Base URL, bearer token, 디바이스 이름, 6자리 코드, 페어링 및 자동 설정 버튼이 있다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 연결 탭에 자동 설정 점검, 서버 Tailscale 확인/복구, 페어링 토큰 복구, 로컬 토큰 삭제가 있다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 연결 탭의 원격 진단 로그 toggle이 클라이언트 preference와 host logging config 동기화를 수행한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Tailscale 섹션은 local snapshot, suggested Base URL, server Tailscale ensure 결과를 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 전원 탭에 SmartThings device id, SmartThings CLI path, SSH host/user/key/port, timeout 설정이 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 전원 탭 버튼: SSH host 채우기, 준비 상태 확인, SSH key 생성/전송, SmartThings 기기 확인, 전원 설정 저장이 동작한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 기기 탭에서 디바이스 새로고침, 폐기된 기기 정리, 현재 토큰 갱신이 동작한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 기기 목록에서 개별 디바이스 폐기 버튼과 폐기됨 상태가 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Android 탭에서 PC process ID와 Android package mapping을 저장할 수 있다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Android 탭에서 모바일 세션 시작/종료 버튼이 active session 상태에 맞게 전환된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 앱 탭에서 로그인 시 실행 toggle이 `SMAppService`를 통해 반영된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 앱 탭에서 로그인 자동 실행 시 창 표시 preference가 저장/복원된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 앱 탭에서 플레이 요약 표시 toggle이 저장/복원되고 dashboard에 즉시 반영된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 앱 탭에서 비 HoYoLab 진행률 표시 mode(`잔여 시간`/`완료 예정 시각`)가 저장/복원된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 앱 탭에서 메뉴바 아이콘 SF Symbol 선택이 저장되고 status item 이미지가 즉시 변경된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 7. 페어링 / Keychain token / 자동 복구

- [ ] 앱 시작 시 Keychain의 `dev.homeworkhelper.remote` / `remote-api-token` 토큰을 읽어 `tokenText`에 반영한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `tokenText` 변경 시 Keychain에 저장되고, 빈 문자열이면 Keychain에서 삭제된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 6자리 페어링 코드 confirm 성공 시 token이 저장되고 pairingCode가 비워진다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 페어링 성공 후 `completePairingOnboarding`이 Tailscale, power setup, SSH key, SmartThings 후보, power config를 가능한 범위에서 자동 설정한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 앱/호스트 재실행 후 기존 token이 사라지지 않고 자동 연결 상태가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `recoverPairing`은 401/403 실패 시 로컬 토큰을 삭제하지 않고 복구 안내만 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `refreshToken`은 새 token을 Keychain에 저장하고 디바이스 목록을 갱신한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `clearLocalPairing`은 로컬 token만 삭제하고 서버 등록 삭제는 별도 안내로 유지한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 8. Remote API / 상태 동기화 / cache fallback

- [ ] `RemoteAPIClient`가 status, capabilities, readiness, processes, summary, incidents, game links, mobile sessions, devices, power, pairing endpoints를 유지한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] bearer token이 있을 때 Authorization header가 모든 보호 endpoint request에 포함된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] process launch path segment는 `/`와 `?`가 안전하게 percent-encoding된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] HTTP error는 status code와 endpoint path를 포함한 `RemoteAPIError.http`로 표시된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] bootstrap은 mirroring을 한 번만 시작하고 Tailscale 후보/Base URL 자동 적용/remote logging config 로드를 수행한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] foreground polling은 5초, background/menu-only polling은 15초, 실패 후 backoff는 60초다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `state_revision`이 변하지 않으면 processes/summary/incidents 전체 sync를 생략한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `state_revision`이 바뀌면 dashboardSummary, beholderIncidents, processes, icon cache가 동기화된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] refresh는 registry race를 피하기 위해 순차 request 구조를 유지한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] network/offline 실패 시 `hostConnectionState = offline`이 되고 cached processes fallback을 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 9. 아이콘 / 프로세스 캐시 / 표시 품질

- [ ] processes snapshot은 Application Support `HomeworkHelperRemote/cache/processes.json`에 저장/복원된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] game icon은 `icon_urls` variant 중 preferred size 256을 우선 선택하고 fallback으로 `icon_url`을 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] resource icon은 `resource_icon_urls` variant 중 preferred size 128을 우선 선택하고 fallback으로 `resource_icon_url`을 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] icon URL은 absolute URL과 relative path/query 모두 올바르게 baseURL에 결합된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] icon download는 HTTP 2xx, `image/png`, 최소 pixel dimension 조건을 만족할 때만 cache한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] cache file name은 process id safe 문자열, cache version, preferred size를 포함한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 표시용 thumbnail은 display point size와 backing scale을 반영해 별도 cache되고 high interpolation으로 렌더링된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] game card icon과 popover icon이 흐리거나 jagged하지 않고 최신 cached thumbnail을 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] icon diagnostics log(`icon-diagnostics.log`)에 download/thumbnail 생성 이벤트가 기록된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 10. Progress 표시 / 자연어 완료 예정 시각

- [ ] 기본 mode `잔여 시간`에서는 host가 준 `progress.displayText`를 그대로 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `완료 예정 시각` mode에서는 cycle progress의 `readyAt`을 자연어 완료 시각으로 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 자연어 날짜 범위는 어제/오늘/내일을 우선 사용하고 그 외는 `n일 전/후`를 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 시간대 표현은 아침/낮/저녁/밤 + 12시간제 시각으로 표시하고 분은 표시하지 않는다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] cycle progress가 아니거나 `readyAt`이 없으면 host display text fallback을 유지한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 11. 전원 제어 / SSH / SmartThings

- [ ] `isPowerActionEnabled`는 local wake, local SSH, remote power capability/readiness를 모두 반영한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] wake action은 local SmartThings config가 있으면 local wake를 우선 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] shutdown/sleep/restart는 local SSH config가 있으면 local SSH를 우선 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] local config가 없고 remote power가 configured이면 `/remote/power/{action}`을 호출한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] unsupported power action은 실행하지 않고 안내 메시지를 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] power config save는 host-safe payload를 저장하고 local SmartThings CLI path는 클라이언트 local 값으로 보존한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] SSH host 채우기는 Base URL host를 power config sshHost에 적용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] SSH key 생성/전송은 local private key path를 채우고 public key를 host에 등록한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] SmartThings probe는 local CLI path일 때 local probe를 사용하고, 아니면 host endpoint를 사용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] SmartThings 후보 클릭 시 device id가 power config에 적용된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] remote desktop logging enabled 시 power click/local wake/local ssh/local SmartThings probe 이벤트가 로그에 기록된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 12. Tailscale / onboarding / readiness

- [ ] local Tailscale 상태 확인은 installed/running/self IP/suggested Base URL을 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Base URL이 localhost/127.0.0.1/빈 값이면 Tailscale suggested URL을 자동 적용한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 자동 설정 점검은 Mac Tailscale, Windows 서버, 페어링, 전원 관리, 서버 Tailscale checklist를 갱신한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 서버 Tailscale 확인/복구는 페어링 후에만 실행 가능하고 status/readiness를 갱신한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] connection guidance는 401/403, 연결 실패, timeout을 사용자 친화적 메시지로 변환한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 13. Android-PC 연결 / 모바일 세션

- [ ] game link 목록을 host에서 읽어 Settings Android 탭에 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] PC process ID + Android package 저장 시 `/remote/game-links`에 mapping을 생성한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] active mobile session이 있으면 “모바일 종료”, 없으면 “모바일 시작” 버튼을 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 모바일 시작은 `/remote/mobile-sessions/start`, 종료는 `/remote/mobile-sessions/end`를 호출하고 목록을 갱신한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] dashboard summary의 모바일 플레이/모바일 세션/활성 모바일/Top 모바일 정보가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 14. 기기 관리 / token lifecycle

- [ ] device 목록 refresh가 `/remote/devices` 결과를 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] 개별 device revoke가 `/remote/devices/{id}` delete를 호출하고 목록을 갱신한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] revoked device purge가 `/remote/devices/revoked` delete를 호출하고 제거 개수를 메시지로 표시한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] token refresh 후 기존 token은 거부되고 새 token만 accepted 되는 host contract가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 15. Host API contract와 Python 회귀 테스트

- [ ] `/remote/status`가 counts, capabilities, power, `state_revision`, `updated_at`를 반환한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `/remote/capabilities`가 status capability contract와 revision을 맞춘다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `/remote/processes`가 icon/card/progress/resource icon payload를 반환한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `/remote/dashboard/summary`가 read-only analytics를 auth boundary 아래 노출한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `/remote/beholder/incidents`가 pending incidents를 resolve 없이 노출한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] pairing start/confirm/revoke/refresh token host contract가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] power config/setup/command/smartthings/ssh-key host contract가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] game links/mobile sessions host contract가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] full pytest가 통과한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 16. Liquid Glass 전환 전용 추가 회귀 항목

- [ ] `NSVisualEffectView`가 제거되어도 메인 창 투명/배경 처리가 깨지지 않는다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `.thinMaterial` 제거 후에도 card/section/pill 구분이 명확하다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] `GlassEffectContainer`와 `glassEffect` 적용 후 click/drag/scroll hit testing이 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] glass button style 적용 후 모든 Button disabled/enabled 상태가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] popover Liquid Glass 적용 후 row text/readability와 icon quality가 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] settings Liquid Glass 적용 후 각 tab의 form control 입력/selection/toggle이 정상 동작한다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

- [ ] Liquid Glass 전환 후 main GUI screenshot과 popover screenshot이 기존보다 native glass에 가까워졌고, 동시에 compact함이 유지된다.
  - 테스트 방법:
  - 테스트 결과:
  - 통과 판정 근거:

---

## 17. 최종 완료 승인 블록

아래 블록은 Liquid Glass 전환 작업 완료 전 반드시 채운다.

```md
## 최종 회귀 테스트 요약

- 테스트 일시:
- 테스트 환경:
  - macOS:
  - Xcode/Swift:
  - Host app 버전/commit:
  - Client app commit:
- 자동 테스트:
  - `./.venv/bin/python -m pytest -q` 결과:
  - `swift build --package-path remote_clients/macos/HomeworkHelperRemote` 결과:
- 수동 테스트 요약:
  - 메인 창 단일성:
  - Settings 진입:
  - Popover 상태 반영:
  - Pairing/token 유지:
  - Icon 품질:
  - Power controls:
  - Android/mobile session:
- 스크린샷 근거:
  - 메인 GUI:
  - Popover:
  - Settings:
- 미검증/리스크:
- 최종 판정: 통과 / 보류 / 실패
- 판정 이유:
```
