# Remote Controller 작업 보고서

현재 통합 브랜치: `main`
작업 브랜치 이력: `dev-remote`에서 개발 후 `main`에 squash merge, 브랜치 삭제 완료
최초 작성: 2026-05-11

## 보고서 운영 방식

매 커밋 직전에 아래 항목을 추가한다.

- 작업 범위
- 자체 코드 리뷰 요약
- 동작 테스트/기초 테스트벤치 결과
- 기존 앱 영향 검토
- Korean Lore 커밋 메시지
- 남은 리스크/다음 작업

---

## 2026-05-11 — Remote Android-PC game links를 원격 매칭 계약으로 추가

### 작업 범위

- `game_platform_links` 테이블/스키마/자동 생성 migration을 추가해 PC process와 Android package mapping을 저장할 수 있게 했다.
- Remote API에 `GET /remote/game-links`, `POST /remote/game-links`를 추가하고 create 명령은 `game_link.create` 감사 이벤트를 남기도록 했다.
- macOS `RemoteAPIClient`/DTO/SwiftUI에 game-links 조회/생성 계약과 `Android-PC 연결` read-only 카드를 추가했다.
- Android `RemoteApiClient`/DTO/Compose UI에 동일한 game-links 계약을 전파하고, 등록된 Android package를 launcher Intent로 실행하는 `Android-PC 연결` 카드를 추가했다.
- macOS API client smoke가 실제 Remote Agent와 통신해 game-links DTO를 decode하도록 확장했다.

### 자체 코드 리뷰 메모

- 이번 단계는 Android-PC 게임 매칭의 기반 계약만 추가하고, 모바일 세션 start/end 및 analytics 병합은 별도 후속 범위로 남겼다.
- `/remote/game-links` create는 기존 PC process 존재를 확인한 뒤 저장하며, 임의 Android package 실행은 Android 앱의 package manager launcher Intent 경계로 제한한다.
- Android는 APK compile 전이므로 정적 계약/UI 전파까지 검증하고, 실제 package launch는 SDK License 승인 후 APK smoke에서 확인한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py` → 35 passed, 5 warnings
- `./.venv/bin/python tools/smoke_macos_remote_api_client.py` → `macOS RemoteAPIClient smoke passed: 0.1.5, devices=1, capabilities=ok, dashboard_sessions=0, beholder_incidents=0, game_links=0`
- `swift build` → Build complete (1.16s)
- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker` → remote routes 16 passed, full pytest 144 passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
Remote Android-PC game links를 원격 매칭 계약으로 추가한다

Constraint: Android APK License blocker가 남아 있어 실기기 세션 sync 전에도 PC process와 Android package mapping 계약은 서버/macOS/Android 정적 경계에서 먼저 고정해야 함
Rejected: 모바일 세션 analytics 병합까지 한 번에 구현 | Usage Access 실기기 검증과 APK compile이 막힌 상태에서 데이터 모델 확장을 과도하게 넓히면 검증 공백이 커짐
Confidence: high
Scope-risk: moderate
Directive: `/remote/mobile-sessions`를 추가할 때는 game-links FK/매칭 정책, UsageStats 권한 gate, analytics 병합 테스트, Android 실기기 smoke를 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py (35 passed); ./.venv/bin/python tools/smoke_macos_remote_api_client.py; swift build; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker (144 passed, Android SDK License blocker acknowledged); git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator game-link package launch 및 UsageStats session sync
```

## 2026-05-11 — Remote device token refresh를 회전 가능한 인증 경계로 추가

### 작업 범위

- `RemoteDeviceRegistry.refresh_token()`을 추가해 현재 device Bearer token을 즉시 회전하고 이전 token을 무효화한다.
- Remote API에 `POST /remote/tokens/refresh` endpoint를 추가하고 `token.refresh` 감사 이벤트를 남기도록 했다.
- macOS `RemoteAPIClient`/DTO/SwiftUI에 현재 토큰 갱신 흐름을 추가하고 Keychain token을 새 token으로 교체하도록 했다.
- Android `RemoteApiClient`/DTO/Compose UI에 동일한 token refresh 흐름을 전파하고 Keystore token을 새 token으로 교체하도록 했다.
- macOS API client smoke가 실제 Remote Agent와 통신해 token refresh 후 새 token으로 후속 API를 호출하도록 확장했다.
- TODO, setup guide, completion audit에 token refresh/rotation 범위와 evidence를 갱신했다.

### 자체 코드 리뷰 메모

- 정적 `HH_REMOTE_TOKEN`은 device-bound가 아니므로 refresh 대상에서 제외하고, pairing으로 등록된 device token만 회전한다.
- refresh endpoint는 기존 Bearer token 인증 경계 안에서 동작하며, 성공 직후 old token은 사용할 수 없도록 hash를 교체한다.
- Android는 APK compile 전이므로 정적 계약/DTO/UI 전파까지 검증하고, 실제 Keystore token 교체는 SDK License 승인 후 APK smoke로 확인한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py` → 33 passed, 4 warnings
- `./.venv/bin/python tools/smoke_macos_remote_api_client.py` → `macOS RemoteAPIClient smoke passed: 0.1.4, devices=1, capabilities=ok, dashboard_sessions=0, beholder_incidents=0`
- `swift build` → Build complete (0.08s)
- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker` → remote routes 14 passed, full pytest 142 passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
Remote device token refresh를 회전 가능한 인증 경계로 추가한다

Constraint: 외부망 노출 전 device token은 폐기뿐 아니라 현재 기기에서 안전하게 회전할 수 있어야 함
Rejected: 재페어링만으로 token 교체 | 사용자가 PC 로컬 pairing code를 다시 발급해야 해 유출 의심 시 빠른 회전 UX가 약함
Confidence: high
Scope-risk: moderate
Directive: token 수명/refresh token 분리를 도입할 때는 HH_REMOTE_TOKEN과 device token 경계를 섞지 말고 rotation audit와 old-token rejection 테스트를 유지할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py (33 passed); ./.venv/bin/python tools/smoke_macos_remote_api_client.py; swift build; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker (142 passed, Android SDK License blocker acknowledged); git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator Keystore token refresh smoke
```

## 2026-05-11 — Remote capabilities를 독립 기능 협상 endpoint로 분리

### 작업 범위

- Remote API에 `GET /remote/capabilities` endpoint를 추가했다.
- `/remote/status`와 `/remote/capabilities`가 같은 capability helper를 사용하도록 해 기능 drift를 줄였다.
- macOS `RemoteAPIClient`/DTO에 capabilities 응답 모델과 client method를 추가하고, 실제 Remote Agent smoke에서 status와 capabilities endpoint가 일치하는지 검증했다.
- Android `RemoteApiClient`/DTO에 capabilities 응답 모델과 client method를 전파했다.
- TODO, setup guide, completion audit에 독립 capabilities endpoint와 evidence를 갱신했다.

### 자체 코드 리뷰 메모

- 기술 검토서 초안의 `/remote/capabilities`를 status의 하위 필드만으로 대체하지 않고 가벼운 기능 협상 endpoint로 분리했다.
- endpoint는 상태/설정 조회만 수행하고 명령 side effect가 없으므로 사용자 승인이나 외부 장비가 필요 없는 로컬 보강 범위다.
- Android는 APK compile 전이므로 정적 계약/DTO 전파까지 검증하고, 실제 runtime은 SDK License 승인 후 APK smoke로 확인한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py` → 32 passed, 4 warnings
- `./.venv/bin/python tools/smoke_macos_remote_api_client.py` → `macOS RemoteAPIClient smoke passed: 0.1.3, devices=1, capabilities=ok, dashboard_sessions=0, beholder_incidents=0`
- `swift build` → Build complete (1.25s)
- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker` → remote routes 13 passed, full pytest 141 passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
Remote capabilities를 독립 기능 협상 endpoint로 분리한다

Constraint: 네이티브 클라이언트는 전체 status payload 없이도 Remote API 기능 지원 여부를 가볍게 협상할 수 있어야 함
Rejected: status.capabilities만 계속 재사용 | capabilities drift를 테스트하기 어렵고 기술 검토서의 독립 endpoint 계약이 남아 있음
Confidence: high
Scope-risk: narrow
Directive: 새 Remote capability를 추가할 때는 status와 /remote/capabilities helper, macOS smoke, Android 정적 계약을 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py (32 passed); ./.venv/bin/python tools/smoke_macos_remote_api_client.py; swift build; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker (141 passed, Android SDK License blocker acknowledged); git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator capabilities client smoke
```

## 2026-05-11 — Remote Beholder incidents를 네이티브 read-only 알림으로 노출

### 작업 범위

- Remote API에 read-only `GET /remote/beholder/incidents` endpoint를 추가했다.
- pending Beholder incident만 `/remote/*` 인증/페어링 경계 안에서 조회하도록 하고 resolve/override side effect는 포함하지 않았다.
- macOS `RemoteAPIClient`/DTO/SwiftUI에 `RemoteBeholderIncident`와 `Beholder 알림` 카드를 추가했다.
- Android `RemoteApiClient`/DTO/Compose UI에 동일한 Beholder incident 모델과 알림 카드를 전파했다.
- macOS API client smoke가 실제 Remote Agent와 통신해 Beholder incident DTO까지 decode하도록 확장했다.
- TODO, setup guide, Android README, completion audit에 Beholder read-only 범위와 evidence를 갱신했다.

### 자체 코드 리뷰 메모

- 기술 검토서의 Beholder incident list 요구를 resolve flow까지 확대하지 않고 read-only 관찰로 시작했다.
- incident resolve는 세션/설정/삭제 등 side effect를 만들 수 있으므로 후속 allowlist 명령과 별도 테스트가 필요하다.
- Android는 APK compile 전이므로 정적 계약/DTO/UI 전파까지 검증하고, 실제 Compose runtime은 SDK License 승인 후 APK smoke로 확인한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py` → 31 passed, 4 warnings
- `./.venv/bin/python tools/smoke_macos_remote_api_client.py` → `macOS RemoteAPIClient smoke passed: 0.1.2, devices=1, dashboard_sessions=0, beholder_incidents=0`
- `swift build` → Build complete (1.05s)
- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker` → remote routes 12 passed, full pytest 140 passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
Remote Beholder incidents를 네이티브 read-only 알림으로 노출한다

Constraint: Beholder resolve는 데이터 수정 side effect가 있으므로 이번 단계는 pending incident read-only 조회로 제한해야 함
Rejected: resolve flow까지 한 번에 원격화 | 세션 복구/삭제/override side effect를 원격 명령으로 허용하기 전 별도 allowlist와 테스트가 필요함
Confidence: high
Scope-risk: moderate
Directive: Beholder resolve를 추가할 때는 action allowlist, audit log, 실패 복구 테스트, macOS smoke, Android 정적 계약을 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py (31 passed); ./.venv/bin/python tools/smoke_macos_remote_api_client.py; swift build; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker (140 passed, Android SDK License blocker acknowledged); git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator Compose Beholder 카드 smoke, Beholder resolve side-effect flow
```

## 2026-05-11 — Remote dashboard summary를 네이티브 앱에 전파

### 작업 범위

- Remote API에 read-only `GET /remote/dashboard/summary` endpoint를 추가했다.
- 기존 dashboard analytics 집계 함수를 재사용하되 `/remote/*` 인증/페어링 경계 안에서만 summary를 노출하도록 했다.
- macOS `RemoteAPIClient`/DTO/SwiftUI에 `RemoteDashboardSummary`와 `플레이 요약` 카드를 추가했다.
- Android `RemoteApiClient`/DTO/Compose UI에 동일한 summary 모델과 `플레이 요약` 카드를 전파했다.
- macOS API client smoke가 실제 Remote Agent와 통신해 dashboard summary DTO를 decode하도록 확장했다.
- TODO, setup guide, Android README, completion audit에 dashboard summary 범위와 evidence를 갱신했다.

### 자체 코드 리뷰 메모

- 일반 dashboard API를 네이티브 앱이 직접 호출하지 않도록 Remote API 안전 레이어에 좁은 read-only summary만 추가했다.
- endpoint는 명령을 실행하지 않고 세션/게임 집계만 반환하므로 사용자 승인이나 외부 장비가 필요 없는 로컬 보강 범위다.
- Android는 APK compile 전이므로 정적 계약/DTO/UI 전파까지 검증하고, 실제 Compose runtime은 SDK License 승인 후 APK smoke로 확인한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py` → 30 passed, 4 warnings
- `./.venv/bin/python tools/smoke_macos_remote_api_client.py` → `macOS RemoteAPIClient smoke passed: 0.1.1, devices=1, dashboard_sessions=0`
- `swift build` → Build complete (1.12s)
- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker` → remote routes 11 passed, full pytest 139 passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
Remote dashboard summary를 네이티브 앱의 read-only 카드로 노출한다

Constraint: 네이티브 앱은 일반 dashboard API가 아니라 /remote 인증 경계 안의 좁은 read-only summary만 소비해야 함
Rejected: 기존 /api/analytics/summary를 앱에서 직접 호출 | Remote API의 device token/auth boundary와 capability contract를 우회하게 됨
Confidence: high
Scope-risk: moderate
Directive: Beholder/analytics 화면을 추가할 때도 먼저 /remote read-only 또는 allowlist 명령 경계를 만들고 macOS smoke와 Android 정적 계약을 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py tests/test_remote_android_client_static.py tests/test_remote_verifier_contract.py (30 passed); ./.venv/bin/python tools/smoke_macos_remote_api_client.py; swift build; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker (139 passed, Android SDK License blocker acknowledged); git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator Compose summary 카드 smoke, SwiftUI 실제 창 클릭 자동화
```

## 2026-05-11 — Android UsageStats 허용 gate 추가

### 작업 범위

- `tools/smoke_android_remote_controller.py`에 `--require-usage-access` option을 추가했다.
- 설치된 APK에 대해 `GET_USAGE_STATS` appop이 `allow`가 아니면 smoke가 실패하도록 해 Usage Access 허용 여부를 실제 gate로 확인할 수 있게 했다.
- 구동 환경 가이드, Android README, TODO, completion audit에 권한 보고/설정 화면 진입/허용 gate 순서를 반영했다.
- verifier contract test에 `--require-usage-access`와 실패 메시지 marker를 추가했다.

### 자체 코드 리뷰 메모

- Usage Access 허용은 여전히 사용자가 Android 설정에서 수행해야 하므로 스크립트가 권한을 변경하지 않는다.
- `--report-usage-access`는 관찰용, `--require-usage-access`는 APK 설치 후 완료 gate용으로 역할을 분리했다.
- APK/실기기 blocker는 유지되며, 이번 변경은 승인 이후 검증이 단순 launch smoke에서 권한 gate까지 이어지도록 만드는 안전한 보조 단계다.

### 테스트/검증 결과

- `./.venv/bin/python tools/smoke_android_remote_controller.py --help` → `--require-usage-access` option 출력 확인
- `./.venv/bin/python tools/smoke_android_remote_controller.py --allow-missing-apk` → APK 누락 blocker를 보고하고 정상 종료
- `./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py` → 6 passed
- `git diff --check` → 통과
- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker` → 138 passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단

### 커밋 예정 Korean Lore 메시지

```text
Android smoke가 UsageStats 허용 상태를 완료 gate로 검증한다

Constraint: Usage Access 허용은 사용자 기기 설정 작업이므로 smoke가 권한을 변경하지 않고 관찰/검증만 해야 함
Rejected: appops 상태 출력만 유지 | 실제 허용 여부가 실패 조건이 아니면 Android UsageStats smoke 완료를 잘못 판단할 수 있음
Confidence: high
Scope-risk: narrow
Directive: APK 설치와 Usage Access 수동 허용 후 --require-usage-access를 실행해 appops allow evidence를 보고서에 남길 것
Tested: ./.venv/bin/python tools/smoke_android_remote_controller.py --help; ./.venv/bin/python tools/smoke_android_remote_controller.py --allow-missing-apk; ./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py (6 passed); ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker (138 passed, Android SDK License blocker acknowledged); git diff --check
Not-tested: 실제 Android device/emulator의 Usage Access 허용/조회, Android SDK License 수락 이후 APK assemble/install
```

## 2026-05-11 — 완료 감사 최신 commit 포인터 보정

### 작업 범위

- `remote-controller-completion-audit.md`의 최신 기능/검증 확인 commit을 `b055b98`로 갱신하고, 후속 문서-only 보정 commit은 `git log`로 확인하도록 분리했다.
- completion audit의 Korean Lore evidence 목록에 squash merge commit `a386423`, 이후 후속 검증 commit, 문서-only 보정 commit 범주를 반영했다.
- 완료 판정 자체는 변경하지 않고 Android SDK License, APK assemble/install, 실기기 UsageStats, 외부망, 실제 전원 장비 blocker를 유지했다.

### 자체 코드 리뷰 메모

- 문서 최신성만 보정하는 좁은 변경이며 제품 코드/검증 스크립트 동작에는 영향을 주지 않는다.
- active goal 완료 여부는 proxy signal이 아니라 audit의 실제 blocker 목록으로 계속 판단한다.
- 최신 기능/검증 commit과 문서-only 보정 commit을 분리해 문서 보정 commit이 다시 최신 포인터를 낡게 만드는 self-stale 루프를 피했다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py` → 6 passed
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
완료 감사가 기능 검증 commit과 문서 보정 commit을 구분한다

Constraint: 문서-only 보정 commit은 새 기능 검증 evidence가 아니므로 최신 기능/검증 commit 포인터와 분리해야 함
Rejected: HEAD hash를 매 문서 보정마다 직접 고정 | 문서-only commit이 다시 audit 포인터를 낡게 만드는 self-stale 루프가 생김
Confidence: high
Scope-risk: narrow
Directive: 후속 기능/검증 commit을 추가할 때만 최신 기능/검증 확인 commit을 갱신하고, 문서-only 보정은 git log 범주로 남길 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py (6 passed); git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator UsageStats smoke
```

## 2026-05-11 — main squash merge 이후 상태 감사

### 작업 범위

- `dev-remote` 누적 작업을 `main`에 Korean Lore 형식의 squash commit으로 통합했다.
- squash merge 후 `origin/dev-remote`와 로컬 `dev-remote` 브랜치를 삭제했다.
- merge 이후 문서가 여전히 `dev-remote`만 기준으로 보이던 부분을 `main` 통합 상태로 갱신했다.
- 통합 검증 진입점을 `tools/verify_remote_controller.py`로 문서화하고 Android SDK License blocker 처리 방식을 명시했다.

### 자체 코드 리뷰 메모

- merge 결과는 `main`의 단일 결정 커밋으로 남겼고, feature branch는 사용자 요청대로 삭제했다.
- Android APK 산출은 Google Android SDK License 수락이 필요한 상태라 에이전트가 임의로 완료 처리하지 않는다.
- `--allow-android-license-blocker`는 현재 blocker를 명시적으로 인정하는 검증 모드일 뿐, APK assemble 완료를 대체하지 않는다.

### 테스트/검증 결과

- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker` → Python 전체 테스트 132 passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단.
- `git diff --cached --check` → squash merge commit 직전 통과.
- `git status --short --branch` → `main...origin/main` clean 상태 확인 후 문서 갱신 시작.

### 커밋 예정 Korean Lore 메시지

```text
리모트 컨트롤러 통합 후 남은 검증 경계를 문서에 고정한다

Constraint: dev-remote는 main에 squash merge 후 삭제되었지만 Android APK 산출은 SDK License 수락 전이라 완료로 표시할 수 없음
Rejected: merge 전 브랜치 기준 문서 유지 | 현재 작업 기준과 남은 blocker가 불명확해 다음 검증자가 잘못된 branch/명령을 사용할 수 있음
Confidence: high
Scope-risk: narrow
Directive: Android SDK License 승인 후 verifier를 blocker 허용 없이 실행하고 APK install/device smoke 결과를 이 보고서에 추가할 것
Tested: 문서 갱신 후 ./.venv/bin/python -m pytest; git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — 실제 서버 프로세스 기반 Remote API smoke 추가

### 작업 범위

- `tools/smoke_remote_controller_runtime.py`를 추가했다.
- smoke는 `homework_helper.pyw`의 `run_server_main()`을 별도 Python subprocess로 띄우고 실제 HTTP 요청으로 Remote API를 검증한다.
- 임시 `HOME`과 임시 loopback port를 사용해 사용자 데이터/기존 서버 상태를 오염시키지 않도록 했다.
- `tools/verify_remote_controller.py`의 통합 검증 루프에 runtime smoke를 포함했다.
- 구동 환경 가이드와 TODO에 실제 서버 프로세스 smoke 진입점을 기록했다.

### 자체 코드 리뷰 메모

- 기존 `tests/test_remote_routes.py`는 FastAPI TestClient로 router 계약을 빠르게 검증하지만, 실제 `homework_helper.pyw` 서버 부팅/환경변수/uvicorn 경로까지는 검증하지 않는다.
- 새 smoke는 macOS/Android 네이티브 앱이 실제로 호출하는 HTTP 경로에 더 가까운 검증이다.
- pairing 후 token 없는 `/remote/status`가 401이 되고, 발급 token으로 `/remote/status`와 `/remote/devices`가 성공하는 경계를 확인한다.

### 테스트/검증 결과

- `./.venv/bin/python tools/smoke_remote_controller_runtime.py` → passed, 임시 loopback server로 Remote Controller runtime smoke 통과.
- `./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker --skip-full-pytest` → remote routes 10 passed, Android static 8 passed, macOS static 5 passed, runtime smoke passed, macOS Swift build passed, Android assembleDebug는 SDK License blocker로만 중단.

### 커밋 예정 Korean Lore 메시지

```text
Remote API pairing 경계를 실제 서버 프로세스로 검증한다

Constraint: Android License 수락 전에는 APK 산출 대신 macOS 개발 환경에서 더 강한 런타임 검증을 추가해야 함
Rejected: TestClient 계약 테스트만 신뢰 | 실제 homework_helper.pyw 서버 부팅과 HTTP pairing/token 경로 회귀를 놓칠 수 있음
Confidence: high
Scope-risk: narrow
Directive: Android SDK License 승인 후 이 verifier를 blocker 허용 없이 실행하고 APK install/device smoke를 이어서 추가할 것
Tested: ./.venv/bin/python tools/smoke_remote_controller_runtime.py; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker --skip-full-pytest; git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — Swift RemoteAPIClient 실통신 smoke 추가

### 작업 범위

- `tools/smoke_macos_remote_api_client.py`를 추가했다.
- smoke는 실제 Remote Agent를 임시 loopback port로 띄우고, 생산 코드인 `RemoteAPIClient.swift`와 `RemoteModels.swift`를 임시 Swift binary에 함께 컴파일한다.
- Python은 pairing code 발급만 담당하고, Swift binary가 `confirmPairing`, Bearer token 기반 `status`, `devices` 조회를 수행한다.
- `tools/verify_remote_controller.py` 통합 검증 루프에 macOS `RemoteAPIClient` smoke를 포함했다.
- 구동 환경 가이드와 TODO에 macOS-native smoke 진입점을 기록했다.

### 자체 코드 리뷰 메모

- `swift build`는 macOS 앱 컴파일 가능성만 보장하고, `RemoteAPIClient`의 endpoint 조립/DTO decode/token header가 실제 서버 응답과 맞는지는 직접 확인하지 못한다.
- 새 smoke는 SwiftUI 창 자동화 대신, macOS 앱의 핵심 네트워크 클라이언트 코드를 그대로 컴파일해 실제 HTTP 경로를 검증한다.
- 임시 `HOME`과 임시 loopback port를 사용하므로 사용자 Keychain/기존 서버 상태를 건드리지 않는다.

### 테스트/검증 결과

- `./.venv/bin/python tools/smoke_macos_remote_api_client.py` → `macOS RemoteAPIClient smoke passed: 0.1.0, devices=1`.

### 커밋 예정 Korean Lore 메시지

```text
macOS RemoteAPIClient가 실제 Remote Agent 계약을 통신으로 검증한다

Constraint: macOS 선행 앱 검증은 Swift build만이 아니라 실제 Swift 클라이언트의 HTTP/DTO/token 경로까지 확인해야 함
Rejected: Python runtime smoke만 유지 | 서버 경로는 확인해도 macOS RemoteAPIClient의 endpoint 조립과 Decodable 계약 회귀를 놓칠 수 있음
Confidence: high
Scope-risk: narrow
Directive: SwiftUI 화면 자동화가 가능한 환경에서는 이 smoke 뒤에 실제 버튼 클릭 smoke를 추가할 것
Tested: ./.venv/bin/python tools/smoke_macos_remote_api_client.py; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker; git diff --check
Not-tested: SwiftUI 실제 창 클릭 자동화, Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — Android APK install/launch smoke preflight 추가

### 작업 범위

- `tools/smoke_android_remote_controller.py`를 추가했다.
- script는 Android manifest/applicationId 계약을 먼저 확인하고, APK가 있으면 `adb install -r`과 `adb shell am start -n dev.homeworkhelper.remote/.MainActivity`로 install/launch smoke를 수행한다.
- Android SDK License 수락 전처럼 APK가 아직 없을 때는 `--allow-missing-apk`로 blocker를 명시적으로 보고하고 0으로 종료할 수 있게 했다.
- `tools/verify_remote_controller.py`에 Android APK smoke readiness check를 포함했다.
- TODO와 구동 환경 가이드에 Android APK smoke 진입점을 기록했다.

### 자체 코드 리뷰 메모

- APK 산출 전 상태에서 install smoke를 통과로 가장하면 안 되므로 기본 동작은 APK 누락을 exit 2 blocker로 처리한다.
- 통합 verifier는 이미 Android assemble 단계에서 SDK License blocker를 별도로 확인하므로, readiness check는 `--allow-missing-apk`로 manifest/applicationId 계약만 추가 검증한다.
- License 승인 후에는 `tools/smoke_android_remote_controller.py`를 flag 없이 실행해야 실제 device/emulator install/launch 검증이 완료된다.

### 테스트/검증 결과

- `./.venv/bin/python tools/smoke_android_remote_controller.py --allow-missing-apk` → APK 누락 blocker를 보고하고 정상 종료.

### 커밋 예정 Korean Lore 메시지

```text
Android APK smoke가 산출 전 blocker와 install 경로를 구분한다

Constraint: Android SDK License 수락 전에는 APK가 없어도 실기기 smoke 절차와 blocker를 repo-local로 고정해야 함
Rejected: 문서상 수동 adb 절차만 유지 | APK 산출 후 install/launch 검증이 반복 가능하지 않아 Android 전파 완료 여부를 놓칠 수 있음
Confidence: high
Scope-risk: narrow
Directive: SDK License 승인 후 APK를 산출하고 이 smoke를 --allow-missing-apk 없이 실행해 device/emulator launch evidence를 남길 것
Tested: ./.venv/bin/python tools/smoke_android_remote_controller.py --allow-missing-apk; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker; git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — Android SDK/License readiness preflight 추가

### 작업 범위

- `tools/check_android_sdk_readiness.py`를 추가했다.
- preflight는 SDK 상태를 변경하지 않고 `sdkmanager`, `adb`, `platform-tools`, `platforms;android-36`, `build-tools;35.0.0`, Android SDK license 파일 존재 여부를 보고한다.
- `--allow-blocker`를 주면 현재처럼 License/package 미설치 상태를 명시 blocker로 출력하고 0으로 종료한다.
- `tools/verify_remote_controller.py` 통합 검증 루프에 Android SDK readiness check를 포함했다.
- TODO와 구동 환경 가이드에 SDK readiness 진입점을 기록했다.

### 자체 코드 리뷰 메모

- Gradle stacktrace만으로 blocker를 확인하면 필요한 SDK package와 license 상태를 한눈에 보기 어렵다.
- readiness preflight는 license 수락이나 package 설치를 수행하지 않으므로 사용자 의사결정 경계를 침범하지 않는다.
- License 승인 후에는 `--allow-blocker` 없이 실행해 package/license/adb 준비가 모두 green인지 확인할 수 있다.

### 테스트/검증 결과

- `./.venv/bin/python tools/check_android_sdk_readiness.py --allow-blocker` → `platform-tools`, `platforms;android-36`, `build-tools;35.0.0`, license files 누락을 blocker로 보고.

### 커밋 예정 Korean Lore 메시지

```text
Android SDK blocker를 Gradle 실행 전 readiness로 분리한다

Constraint: SDK License 수락은 사용자 결정이므로 preflight는 상태 보고만 하고 설치/수락을 수행하면 안 됨
Rejected: Gradle assemble stacktrace만 blocker evidence로 유지 | 어떤 SDK package와 license가 빠졌는지 반복 검증 때 즉시 파악하기 어려움
Confidence: high
Scope-risk: narrow
Directive: SDK License 승인 후 check_android_sdk_readiness.py를 --allow-blocker 없이 실행해 Android toolchain 준비를 먼저 green으로 만들 것
Tested: ./.venv/bin/python tools/check_android_sdk_readiness.py --allow-blocker; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker; git diff --check
Not-tested: Android SDK License 수락 이후 SDK package 설치, APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — Remote Controller 검증 스크립트 계약 테스트 추가

### 작업 범위

- `tests/test_remote_verifier_contract.py`를 추가했다.
- 통합 verifier가 Remote API pytest, Android/macOS 정적 계약, 실제 서버 smoke, Swift `RemoteAPIClient` smoke, Android SDK readiness, Android APK smoke readiness, Swift build, Gradle assemble을 모두 호출하는지 정적으로 검증한다.
- Android SDK readiness script가 license/package 상태만 보고하고 SDK를 변경하지 않는 계약을 검증한다.
- Android APK smoke가 APK 누락 blocker와 실제 `adb install`/`am start` 경로를 구분하는 계약을 검증한다.
- macOS smoke들이 실제 `homework_helper.pyw` 서버 프로세스와 생산 Swift client 파일을 사용한다는 계약을 검증한다.

### 자체 코드 리뷰 메모

- 검증 스크립트 자체가 회귀하면 전체 완료 감사가 잘못된 proxy signal에 의존할 수 있다.
- 정적 테스트는 Android SDK License 수락 전에도 실행 가능하며, 기본 `pytest`에 포함되어 검증 루프의 구성 drift를 막는다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py` → 4 passed.

### 커밋 예정 Korean Lore 메시지

```text
Remote Controller verifier 자체도 테스트벤치에 고정한다

Constraint: Android License 승인 전에는 verifier/smoke 구성 drift를 정적 테스트로 막아야 함
Rejected: 검증 스크립트는 수동 관리 | verifier가 일부 lane을 누락해도 테스트가 통과하는 proxy signal 문제가 생길 수 있음
Confidence: high
Scope-risk: narrow
Directive: 새 smoke나 blocker lane을 추가하면 tests/test_remote_verifier_contract.py도 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker; git diff --check
Not-tested: Android SDK License 수락 이후 SDK package 설치, APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — LAN/Tailscale connectivity smoke 추가

### 작업 범위

- `tools/smoke_remote_controller_connectivity.py`를 추가했다.
- 이 smoke는 서버를 직접 시작하지 않고, 이미 실행 중인 Remote Agent의 LAN/Tailscale/ZeroTier URL을 받아 `/remote/status` metadata/counts/capabilities/power 계약을 검증한다.
- `--token`, `--expect-auth`, `--expect-no-auth` option으로 Bearer token 인증 경계를 확인할 수 있게 했다.
- 구동 환경 가이드의 Tailscale/ZeroTier 섹션에 connectivity smoke 실행 예시를 추가했다.
- verifier/smoke 계약 pytest에 connectivity smoke 필수 marker를 추가했다.

### 자체 코드 리뷰 메모

- 외부망/tailnet 실접속은 실제 네트워크와 token이 필요해 기본 verifier에 자동 포함할 수 없다.
- 대신 반복 가능한 smoke script를 repo에 고정해, 사용자 환경이 준비되는 즉시 같은 기준으로 실접속 evidence를 남길 수 있게 했다.
- smoke는 `/remote/status`만 사용하므로 실행/전원 명령 side effect 없이 안전하게 connectivity와 인증 요구 여부를 확인한다.

### 테스트/검증 결과

- `./.venv/bin/python tools/smoke_remote_controller_connectivity.py --help` → CLI option 출력 확인.
- `./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py` → connectivity smoke marker 포함 검증.

### 커밋 예정 Korean Lore 메시지

```text
외부망 Remote Agent 접속 검증도 side-effect 없는 smoke로 고정한다

Constraint: Tailscale/ZeroTier 실접속은 사용자 네트워크와 token이 필요해 기본 verifier에서 자동 실행할 수 없음
Rejected: 외부망 검증을 수동 curl 절차로만 유지 | 실접속 evidence 기준이 매번 달라져 완료 감사의 남은 gap을 줄이기 어려움
Confidence: high
Scope-risk: narrow
Directive: tailnet URL과 paired token이 준비되면 connectivity smoke를 --expect-auth로 실행해 결과를 보고서와 완료 감사에 반영할 것
Tested: ./.venv/bin/python tools/smoke_remote_controller_connectivity.py --help; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker; git diff --check
Not-tested: 실제 Tailscale/ZeroTier/LAN 원격 URL 접속, Android SDK License 수락 이후 APK assemble/install
```

---

## 2026-05-11 — Remote power adapter readiness preflight 추가

### 작업 범위

- `tools/check_remote_power_readiness.py`를 추가했다.
- preflight는 `remote_power_config.json` 또는 환경변수로 로드되는 `RemotePowerConfig`를 검사하되 SmartThings/SSH 명령은 실행하지 않는다.
- SmartThings CLI path, SSH host/user/key path, 지원 가능한 power action 목록을 보고한다.
- `tools/verify_remote_controller.py` 통합 검증 루프에 remote power readiness check를 포함했다.
- 구동 환경 가이드와 TODO에 power readiness 진입점을 기록하고, verifier contract test에 script marker를 추가했다.

### 자체 코드 리뷰 메모

- 실제 wake/shutdown/sleep/restart는 개인 장비와 네트워크에 side effect가 있으므로 기본 verifier에서 수행하면 안 된다.
- readiness preflight는 설정 누락과 지원 action을 명확히 보고해 macOS/Android UI의 power capability gating을 실제 설정 단계와 연결한다.
- 현재 환경에는 `remote_power_config.json`이 없어 blocker로 보고된다.

### 테스트/검증 결과

- `./.venv/bin/python tools/check_remote_power_readiness.py --allow-blocker` → config/SmartThings/SSH key 누락 blocker 보고.

### 커밋 예정 Korean Lore 메시지

```text
전원 adapter 설정도 명령 실행 전 readiness로 분리한다

Constraint: SmartThings/SSH 전원 명령은 실제 장비 side effect가 있어 기본 verifier에서 실행하면 안 됨
Rejected: 전원 readiness를 문서 확인에만 의존 | 설정 누락과 지원 action을 반복 검증할 수 없어 power capability gating 검증이 약해짐
Confidence: high
Scope-risk: narrow
Directive: remote_power_config.json을 구성한 뒤 readiness를 --allow-blocker 없이 실행하고 실제 전원 명령은 별도 승인된 환경에서만 smoke할 것
Tested: ./.venv/bin/python tools/check_remote_power_readiness.py --allow-blocker; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker; git diff --check
Not-tested: 실제 SmartThings WoL/SSH shutdown/sleep/restart, Android SDK License 수락 이후 APK assemble/install
```

---

## 2026-05-11 — Android UsageStats smoke 보조 옵션 추가

### 작업 범위

- `tools/smoke_android_remote_controller.py`에 `--report-usage-access` option을 추가했다.
- 설치된 APK에 대해 `adb shell cmd appops get <package> GET_USAGE_STATS` 결과를 보고해 UsageStats 권한 상태를 확인할 수 있게 했다.
- `--open-usage-access-settings` option으로 Android Usage Access 설정 화면을 열 수 있게 했다.
- 구동 환경 가이드에 UsageStats 권한 상태 보고와 설정 화면 진입 명령을 추가했다.
- verifier contract test에 UsageStats appops/설정 화면 marker를 추가했다.

### 자체 코드 리뷰 메모

- Usage Access 허용은 사용자의 기기 설정 작업이므로 스크립트가 기본으로 권한을 변경하면 안 된다.
- 기본 install/launch smoke는 그대로 유지하고, appops 보고와 설정 화면 열기는 명시 option으로만 수행한다.
- 이 옵션은 Android APK가 실제 설치된 후 UsageStats provider smoke로 넘어가기 전 권한 blocker를 빠르게 확인하는 용도다.

### 테스트/검증 결과

- `./.venv/bin/python tools/smoke_android_remote_controller.py --help` → `--report-usage-access`, `--open-usage-access-settings` option 출력 확인.

### 커밋 예정 Korean Lore 메시지

```text
Android smoke가 UsageStats 권한 blocker도 보고할 수 있게 한다

Constraint: Usage Access 허용은 사용자 기기 설정 작업이므로 smoke가 기본으로 권한을 변경하면 안 됨
Rejected: APK launch만 smoke | UsageStats 권한 blocker를 별도 수동 adb 절차로 확인해야 해 Android 세션 추적 검증이 끊김
Confidence: high
Scope-risk: narrow
Directive: APK 설치 후 --report-usage-access로 권한 상태를 기록하고, 필요 시 --open-usage-access-settings로 사용자가 직접 허용하게 할 것
Tested: ./.venv/bin/python tools/smoke_android_remote_controller.py --help; ./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py; ./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker; git diff --check
Not-tested: 실제 Android device/emulator의 Usage Access 허용/조회, Android SDK License 수락 이후 APK assemble/install
```

---

## 2026-05-11 — 착수 / 1차 수직 슬라이스 준비

### 작업 범위

- 신규 브랜치 `dev-remote` 생성.
- 설계 문서 `remote-controller-technical-review.md`를 루트 산출물로 유지.
- 지속 업데이트 문서 2종 생성.
  - `remote-controller-todo.md`
  - `remote-controller-work-report.md`
- HomeworkHelper FastAPI에 원격 네이티브 클라이언트용 `/remote/*` 라우터 추가.
- macOS SwiftUI 클라이언트 골격 생성.

### 구현 상세

- `src/api/remote_routes.py`
  - `/remote/status`
  - `/remote/processes`
  - `/remote/processes/{process_id}/launch`
  - `/remote/shortcuts`
  - `/remote/shortcuts/{shortcut_id}/open`
  - `/remote/power/status`
  - `/remote/power/{action}`
- `src/core/remote_power.py`
  - 미설정 환경에서 안전하게 power command를 거부하는 기본 adapter 추가.
- `homework_helper.pyw`
  - 서버 시작 시 remote router 등록.
- `tests/test_remote_routes.py`
  - 상태 조회, 실행 대상 선택, direct mode override, 숏컷 open command 테스트 추가.
- `remote_clients/macos/HomeworkHelperRemote`
  - Swift Package 기반 macOS SwiftUI 앱 골격.
  - Remote status/process/shortcut 조회 및 process launch/shortcut open 호출 UI.

### 자체 코드 리뷰 메모

- 원격 API는 기존 CRUD를 인터넷에 직접 노출하지 않고 `/remote/*` 명령 표면으로 분리했다.
- 게임 실행은 기존 `Launcher`를 계속 사용해 .url/.lnk/protocol 처리 경계를 유지했다.
- 전원 제어는 아직 SmartThings/SSH 실제 명령을 연결하지 않고 안전 기본 adapter로 막았다.
- 인증/pairing은 아직 미구현이므로 외부 노출 전 반드시 다음 단계에서 구현해야 한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 5 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (initial 31.15s, incremental 0.07s)
- `./.venv/bin/python -m pytest` → 114 passed, 4 warnings
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
리모트 컨트롤러의 첫 수직 슬라이스를 안전한 명령 표면으로 착수한다

Constraint: macOS에서 먼저 실제 빌드 가능한 네이티브 클라이언트와 Remote Agent API를 검증해야 함
Rejected: 기존 FastAPI CRUD 전체를 원격 앱에 직접 노출 | 실행/전원 명령 공격면이 커져 별도 allowlist 명령 표면이 필요함
Confidence: medium
Scope-risk: moderate
Directive: 외부망 노출 전 pairing/token 인증과 command audit log를 반드시 추가할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (5 passed); swift build in remote_clients/macos/HomeworkHelperRemote (Build complete; initial 31.15s, incremental 0.07s); ./.venv/bin/python -m pytest (114 passed); git diff --check
Not-tested: Android APK 전파, 실제 SmartThings/SSH 전원 adapter, 외부망 Tailscale/ZeroTier 실기기 연결
```

---

## 2026-05-11 — 인증 경계 1차 보강

### 작업 범위

- Remote Agent `/remote/*` 라우터에 선택적 Bearer token 인증을 추가했다.
- `HH_REMOTE_TOKEN` 환경변수 또는 router factory 인자로 토큰을 설정하면 모든 Remote API 요청이 `Authorization: Bearer <token>` 없이는 401을 반환한다.
- macOS SwiftUI 클라이언트에 Bearer token 입력란을 추가하고 모든 GET/POST 요청에 Authorization 헤더를 붙이도록 했다.
- 인증 요구 상태를 `/remote/status`의 `capabilities.auth_required`에 노출했다.

### 자체 코드 리뷰 메모

- 아직 pairing UX와 device registry는 없지만, 외부망 노출 전 최소한의 shared-secret 방어선을 먼저 만들었다.
- 기본값은 기존 로컬 개발 흐름을 깨지 않도록 토큰 미설정 시 인증 비활성화다.
- 실제 Tailscale/Cloudflare 공개 전에는 token revoke, 저장소 암호화, command audit log가 필요하다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 6 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.66s)

### 커밋 예정 Korean Lore 메시지

```text
원격 API가 외부망에 노출되기 전 최소 인증 경계를 갖춘다

Constraint: macOS 선행 개발 흐름을 깨지 않으면서 Tailscale/터널 노출 전 안전장치가 필요함
Rejected: pairing/device registry를 첫 인증 단위에 모두 포함 | 첫 수직 슬라이스가 과도하게 커지므로 shared token으로 경계를 먼저 세움
Confidence: medium
Scope-risk: narrow
Directive: HH_REMOTE_TOKEN 없이 외부 인터페이스에 bind하지 말고 다음 단계에서 token revoke와 audit log를 추가할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (6 passed); swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.66s); ./.venv/bin/python -m pytest (115 passed); git diff --check
Not-tested: 실제 Tailscale/Cloudflare 외부망 접속, Keychain 영구 저장, Android 클라이언트 전파
```

---

## 2026-05-11 — 원격 명령 감사 로그 추가

### 작업 범위

- 원격 명령 감사 로그 writer `src/core/remote_audit.py`를 추가했다.
- 게임 실행, 웹 숏컷 열기, 전원 명령 결과를 append-only JSONL 이벤트로 기록한다.
- 기본 저장 경로는 HomeworkHelper 데이터 디렉터리의 `remote_command_audit.jsonl`이다.
- Remote API 테스트에서 fake auditor로 명령별 감사 이벤트 생성을 검증한다.

### 자체 코드 리뷰 메모

- DB 마이그레이션 없이 첫 감사 경계를 세우기 위해 JSONL 파일로 시작했다.
- 이벤트에는 command, accepted/status, target id/name/path, metadata를 남긴다.
- 추후 device id, actor, remote address, token fingerprint, retention 정책을 추가해야 한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 6 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 115 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
원격 명령의 결과를 감사 가능한 JSONL 기록으로 남긴다

Constraint: 원격 실행/전원 명령은 pairing 이전 단계부터 추적 가능한 흔적을 남겨야 함
Rejected: 첫 단계부터 DB 테이블 마이그레이션 적용 | Remote API 계약 검증 중이라 파일 기반 append-only 로그가 더 작고 되돌리기 쉬움
Confidence: medium
Scope-risk: narrow
Directive: 다음 단계에서 device id, remote address, token fingerprint, 보존 정책을 감사 이벤트에 추가할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (6 passed); ./.venv/bin/python -m pytest (115 passed); swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.07s); git diff --check
Not-tested: Windows 설치본 데이터 디렉터리에서 장기 로그 rotation, 실제 외부망 명령 감사
```

---

## 2026-05-11 — 페어링 코드와 macOS Keychain 토큰 저장

### 작업 범위

- `src/core/remote_pairing.py`에 파일 기반 디바이스 레지스트리를 추가했다.
- `/remote/pair/start`, `/remote/pair/confirm`, `/remote/devices`, `DELETE /remote/devices/{id}` API를 추가했다.
- 페어링 코드 발급은 로컬 요청 또는 이미 인증된 디바이스로 제한했다.
- 페어링 완료 후 등록 디바이스가 생기면 `/remote/*` 보호 API가 device token을 요구한다.
- macOS SwiftUI 앱에 페어링 코드 입력 UI를 추가했다.
- macOS 앱은 페어링으로 받은 token을 Keychain에 저장하고 다음 실행 시 재사용한다.

### 자체 코드 리뷰 메모

- token은 서버 레지스트리에 평문 저장하지 않고 SHA-256 hash만 저장한다.
- pairing code는 6자리 단기 코드이며 confirm 성공 시 즉시 폐기한다.
- pair/start가 원격 미인증 요청으로 열리지 않도록 loopback 또는 기존 인증 조건으로 제한했다.
- 아직 device revoke는 API만 있고 macOS UI는 없다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 8 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 117 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
페어링 코드로 macOS 리모트 앱의 디바이스 토큰을 발급한다

Constraint: 외부망 연결 전에 shared token 수동 입력보다 안전한 디바이스별 token 흐름이 필요함
Rejected: 원격 미인증 pair/start 허용 | 최초 설정은 편하지만 공격자가 pairing code를 발급할 수 있어 loopback/인증 조건으로 제한함
Confidence: medium
Scope-risk: moderate
Directive: 실제 배포 전 device revoke UI, token fingerprint 감사, pairing code 화면 표시 UX를 추가할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (8 passed); ./.venv/bin/python -m pytest (117 passed); swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.07s); git diff --check
Not-tested: 실제 macOS 앱에서 Keychain 권한 팝업/재실행 persistence 수동 확인, 원격망 페어링
```

---

## 2026-05-11 — pc_remote 전원 adapter 이식

### 작업 범위

- `src/core/remote_power.py`에 SmartThings WoL + SSH 전원 제어 adapter를 추가했다.
- `pc_remote`의 핵심 동작을 Remote Agent에서 재사용할 수 있도록 다음 allowlist 명령으로 제한했다.
  - wake: `smartthings devices:commands <device> switch:on`
  - shutdown: `shutdown /s /t 0`
  - sleep: `rundll32.exe powrprof.dll,SetSuspendState 0,0,0`
  - restart: `shutdown /r /t 0`
- 설정은 HomeworkHelper 데이터 디렉터리의 `remote_power_config.json` 또는 `HH_REMOTE_*` 환경변수로 읽는다.
- `/remote/power/status`는 SSH TCP 상태 확인으로 on/off/unknown을 반환한다.
- 테스트에서는 fake runner/tcp checker로 실제 전원 명령 없이 command assembly를 검증했다.

### 자체 코드 리뷰 메모

- 원격 클라이언트 입력을 shell command로 직접 전달하지 않고 action enum만 허용한다.
- 설정이 없으면 기존처럼 명령을 거부하며 `not_configured`를 반환한다.
- 실제 사용 전에는 config 작성 UI/문서와 secret 보관 정책이 필요하다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 9 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 118 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.09s)
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
pc_remote 전원 제어를 Remote Agent의 안전한 allowlist adapter로 이식한다

Constraint: 원격 앱에서 데스크톱 on/off를 지원하되 임의 shell 실행면을 열지 않아야 함
Rejected: 원격 요청 body로 실행 명령을 받기 | 전원 제어 요구를 넘어서 command injection 위험을 만든다
Confidence: medium
Scope-risk: moderate
Directive: remote_power_config.json에는 개인 IP/device id/key path가 들어가므로 repo에 커밋하지 말고 설정 UI/문서를 별도로 제공할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (9 passed); ./.venv/bin/python -m pytest (118 passed); swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.09s); git diff --check
Not-tested: 실제 SmartThings Hub WoL, Windows OpenSSH 전원 명령, 외부망 Tailscale 경유 상태 확인
```

---

## 2026-05-11 — macOS 앱 전원 제어 버튼 연결

### 작업 범위

- macOS SwiftUI 클라이언트에 PC 전원 제어 섹션을 추가했다.
- 버튼 4종을 Remote Agent `/remote/power/{action}`에 연결했다.
  - 켜기: `wake`
  - 절전: `sleep`
  - 재시작: `restart`
  - 끄기: `shutdown`
- 전원 명령 후 상태를 다시 refresh하도록 했다.

### 자체 코드 리뷰 메모

- macOS 앱은 action 문자열만 전송하고 실제 SmartThings/SSH command는 서버 adapter의 allowlist가 생성한다.
- 버튼은 power adapter 미설정 상태에서도 호출 가능하지만 서버가 `not_configured`를 반환하므로 위험한 동작은 없다.
- 추후 power capability/supported_actions를 UI disabled 조건으로 반영해야 한다.

### 테스트/검증 결과

- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.72s)
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 9 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 118 passed, 4 warnings
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
macOS 리모트 앱에서 PC 전원 명령을 호출한다

Constraint: macOS 앱에서 먼저 데스크톱 on/off UX를 검증해야 Android로 전파할 수 있음
Rejected: macOS 앱에서 SmartThings/SSH를 직접 실행 | 전원 명령 생성과 감사는 Remote Agent allowlist 경계에 남겨야 함
Confidence: medium
Scope-risk: narrow
Directive: supported_actions와 power_control capability를 UI 활성/비활성 조건으로 다음 단계에서 반영할 것
Tested: swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.72s); ./.venv/bin/python -m pytest tests/test_remote_routes.py (9 passed); ./.venv/bin/python -m pytest (118 passed); git diff --check
Not-tested: 실제 SmartThings/SSH 설정이 있는 PC 전원 동작, GUI 수동 클릭 smoke
```

---

## 2026-05-11 — macOS 등록 디바이스 revoke UI

### 작업 범위

- macOS SwiftUI 클라이언트에 등록 디바이스 목록 조회 UI를 추가했다.
- `/remote/devices` 응답 모델과 `DELETE /remote/devices/{id}` 클라이언트 메서드를 추가했다.
- 디바이스별 폐기 버튼으로 서버 device token을 revoke할 수 있게 했다.
- token이 비어 있으면 디바이스 새로고침을 비활성화한다.

### 자체 코드 리뷰 메모

- revoke API는 이미 인증된 토큰이 있어야 호출 가능하므로 미페어링 상태에서는 접근하지 않는다.
- 현재 자기 자신을 revoke하면 이후 refresh가 401이 될 수 있으므로, 다음 단계에서 현재 디바이스 식별 및 로컬 token 삭제 UX를 보강해야 한다.
- 디바이스 모델에는 created/last_seen/revoked 시각을 받아두지만 첫 UI는 이름/platform 중심으로 최소화했다.

### 테스트/검증 결과

- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.82s)
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 9 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 118 passed, 4 warnings
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
macOS 앱에서 등록 디바이스 토큰을 폐기한다

Constraint: pairing으로 발급한 device token은 사용자가 회수할 수 있어야 외부망 노출 전 안전 경계가 완성됨
Rejected: 서버 API만 두고 UI를 미루기 | macOS 선행 검증 흐름에서 token revoke 동작을 직접 확인할 수 없음
Confidence: medium
Scope-risk: narrow
Directive: 자기 디바이스 revoke 시 Keychain token 삭제와 재페어링 안내를 추가할 것
Tested: swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.82s); ./.venv/bin/python -m pytest tests/test_remote_routes.py (9 passed); ./.venv/bin/python -m pytest (118 passed); git diff --check
Not-tested: 실제 앱에서 자기 자신 revoke 후 Keychain 동작 수동 확인
```

---

## 2026-05-11 — Tailscale 바인딩과 전원 설정 문서화

### 작업 범위

- `HH_API_HOST` / `HH_API_PORT`로 API 서버 bind 주소를 설정할 수 있게 했다.
- loopback 밖으로 bind하거나 `HH_REMOTE_REQUIRE_AUTH=1`을 설정하면 Remote API 인증을 강제한다.
- `remote_power_config.example.json` 예시 파일을 추가했다.
- `docs/remote-controller/setup-guide.md`에 로컬 검증, pairing, Tailscale/ZeroTier bind, 전원 설정, 검증 명령을 문서화했다.

### 자체 코드 리뷰 메모

- 외부 bind 시 등록 디바이스가 없어도 인증을 강제해 무인 외부 노출을 막는다.
- 최초 pairing code 발급은 여전히 loopback 또는 인증된 디바이스에서만 가능하다.
- 실제 config 파일은 사용자 데이터 디렉터리에 두도록 문서화하고, repo에는 예시만 둔다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 119 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- `git diff --check` → 통과

### 커밋 예정 Korean Lore 메시지

```text
외부망 원격 접속을 위한 bind와 설정 가이드를 고정한다

Constraint: Tailscale/ZeroTier에서 접근하려면 loopback 밖 bind가 필요하지만 인증 없는 노출은 금지해야 함
Rejected: 127.0.0.1 고정 유지 | macOS/Android 리모트 앱의 외부망 실기기 검증을 진행할 수 없음
Confidence: medium
Scope-risk: moderate
Directive: HH_API_HOST를 loopback 밖으로 열 때는 HH_REMOTE_REQUIRE_AUTH 또는 등록 device token 없이 운용하지 말 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (10 passed); ./.venv/bin/python -m pytest (119 passed); swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.07s); git diff --check
Not-tested: 실제 Tailscale/ZeroTier 네트워크에서 원격 접속 smoke
```

---

## 2026-05-11 — Android Compose 클라이언트 계약 전파

### 작업 범위

- `remote_clients/android/HomeworkHelperRemote`에 Kotlin + Jetpack Compose Android 앱 초안을 추가했다.
- 기존 `HomeworkHelper/` ignore 규칙이 Android 앱 경로를 가리지 않도록 `.gitignore` 예외를 추가했다.
- Android Gradle Plugin/Kotlin/Compose 설정을 분리하고 Kotlin 2.x용 `org.jetbrains.kotlin.plugin.compose` plugin을 명시했다.
- Android 앱에 Remote Agent URL, Bearer token, device name 저장 흐름을 추가했다.
- `/remote/pair/confirm` pairing code 입력으로 Android device token을 발급받는 UI와 API client를 추가했다.
- `/remote/status`, `/remote/processes`, `/remote/shortcuts`, `/remote/devices` 조회 및 PC 실행/숏컷/전원/device revoke 호출을 macOS 앱과 같은 API 계약으로 전파했다.
- Android package name 수동 입력 기반 `PackageManager.getLaunchIntentForPackage()` 실행과 Usage Access 설정 진입 버튼을 추가했다.
- Android manifest에 `INTERNET`, `PACKAGE_USAGE_STATS`, launcher intent `<queries>`를 선언했다.
- `docs/remote-controller/setup-guide.md`, `remote-controller-todo.md`, Android README에 APK 빌드 한계와 후속 검증 항목을 기록했다.

### 자체 코드 리뷰 메모

- Android 앱은 Remote Agent가 생성한 command만 호출하고, Android 로컬 실행은 사용자가 입력한 package name을 Android package manager에 전달하는 최소 smoke 경계로 제한했다.
- token 저장은 현재 `SharedPreferences` 초안이므로 실사용 APK 전에는 Android Keystore/EncryptedSharedPreferences로 교체해야 한다.
- Usage Access는 manifest 선언만으로 허용되지 않으므로 앱에서 설정 화면 진입만 제공하고 실제 권한 허용은 사용자 동작으로 남긴다.
- 현재 macOS 환경에는 Java Runtime/Gradle/Android SDK가 없어 `assembleDebug`를 실행하지 못했다. 따라서 Kotlin/Gradle compile 검증은 다음 환경 준비 후 가장 먼저 수행해야 한다.
- Compose 설정은 Android 공식 문서 확인 결과에 맞춰 Compose BOM, activity-compose, Material3, Kotlin Compose compiler plugin을 포함했다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 119 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- Android XML parse/static contract check → manifest/styles XML OK, Gradle/RemoteApiClient/AndroidIntegration required contract strings OK
- `git diff --check` → 통과
- `java -version` → Java Runtime 없음
- `gradle -v` → command not found

### 커밋 예정 Korean Lore 메시지

```text
Android 리모트 앱 초안에 macOS Remote API 계약을 전파한다

Constraint: 현재 macOS 개발 환경에 Java Runtime/Gradle/Android SDK가 없어 APK assemble 검증은 수행할 수 없음
Rejected: Android 작업을 APK 가능 환경까지 전부 미루기 | macOS에서 검증한 Remote API 계약을 Android 코드에 조기 전파해야 DTO/API drift를 줄일 수 있음
Rejected: Android에서 PC 제어 명령을 별도 구현 | PC 실행/전원 제어는 Remote Agent allowlist와 감사 로그 경계를 재사용해야 함
Confidence: medium
Scope-risk: moderate
Directive: JDK/Android SDK 준비 후 `gradle :app:assembleDebug`를 가장 먼저 실행하고 token 저장소를 Keystore/EncryptedSharedPreferences로 교체할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (10 passed); ./.venv/bin/python -m pytest (119 passed); swift build in remote_clients/macos/HomeworkHelperRemote (Build complete 0.07s); Android XML parse/static contract check; git diff --check
Not-tested: Android APK assemble/install, 실제 Android device/emulator pairing/Intent/Usage Access smoke
```

---

## 2026-05-11 — Android APK 빌드 환경 구성 시도

### 작업 범위

- Homebrew로 OpenJDK 17, Gradle 9.5.0, Android command line tools를 설치했다.
- Android 프로젝트에 Gradle wrapper 9.5.0을 생성했다.
- wrapper와 Android app 경로가 Git에 안정적으로 포함되도록 `.gitignore` 예외/빌드 산출물 제외 규칙을 정리했다.
- `./gradlew :app:assembleDebug --stacktrace`를 실제 실행해 APK 빌드의 현재 blocker를 확인했다.
- Android README, 구동 환경 가이드, TODO에 SDK License blocker와 다음 검증 명령을 기록했다.

### 자체 코드 리뷰 메모

- Gradle wrapper는 프로젝트별 재현성을 높이므로 커밋 대상이다.
- `.gradle/`, `build/`, `app/build/`, `local.properties`는 개인/빌드 산출물이므로 ignore 대상으로 남겼다.
- Android SDK package 설치 단계에서 Google Android SDK License 수락이 필요했고, 법적 동의가 필요한 사용자 결정으로 판단해 수락하지 않았다.
- `assembleDebug`는 Kotlin compile까지 도달하기 전에 SDK license 미수락으로 중단되었으므로 APK 생성은 아직 완료되지 않았다.

### 테스트/검증 결과

- `JAVA_HOME=/opt/homebrew/opt/openjdk@17 /opt/homebrew/opt/openjdk@17/bin/java -version` → OpenJDK 17.0.19 확인
- `JAVA_HOME=/opt/homebrew/opt/openjdk@17 /opt/homebrew/bin/gradle -v` → Gradle 9.5.0 확인
- `JAVA_HOME=/opt/homebrew/opt/openjdk@17 /opt/homebrew/bin/sdkmanager --version` → 20.0 확인
- `JAVA_HOME=/opt/homebrew/opt/openjdk@17 /opt/homebrew/bin/gradle wrapper --gradle-version 9.5.0 --distribution-type bin` → BUILD SUCCESSFUL
- `JAVA_HOME=/opt/homebrew/opt/openjdk@17 ANDROID_HOME=/opt/homebrew/share/android-commandlinetools ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools ./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락으로 실패

### 커밋 예정 Korean Lore 메시지

```text
Android APK 빌드 재현성을 위해 Gradle wrapper와 SDK blocker를 고정한다

Constraint: Android SDK package 설치는 Google Android SDK License 수락이 필요해 사용자 동의 없이 진행하지 않음
Rejected: license 파일을 수동으로 생성해 우회 | 라이선스 수락은 빌드 편의보다 사용자 명시 동의가 우선임
Confidence: medium
Scope-risk: narrow
Directive: 사용자가 Android SDK License 수락을 승인하면 sdkmanager --licenses 후 ./gradlew :app:assembleDebug를 다시 실행할 것
Tested: OpenJDK 17.0.19 확인; Gradle 9.5.0 확인; sdkmanager 20.0 확인; gradle wrapper 생성 BUILD SUCCESSFUL; ./gradlew :app:assembleDebug --stacktrace 실행 후 SDK license blocker 확인
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — Android token 저장소 Keystore 암호화 전환

### 작업 범위

- Android 초안의 Bearer token 저장을 평문 `SharedPreferences`에서 Android Keystore 기반 AES/GCM 암호화 저장으로 전환했다.
- `AndroidTokenStore`를 추가해 `AndroidKeyStore`, `KeyGenParameterSpec`, `AES/GCM/NoPadding`, 128-bit GCM tag로 token을 암복호화한다.
- 기존 초안에서 저장했을 수 있는 legacy 평문 token은 최초 실행 시 암호화 저장소로 마이그레이션하고 legacy key를 제거하도록 했다.
- UI에 로컬 token 삭제 버튼을 추가해 기기 내 저장 token을 제거할 수 있게 했다.
- Android README, 구동 환경 가이드, TODO를 Keystore 저장 흐름 기준으로 갱신했다.

### 자체 코드 리뷰 메모

- Remote Agent token은 외부망 접근 권한이므로 Android 실사용 전 평문 저장을 남기지 않는 것이 안전하다.
- Android Keystore key는 앱 sandbox와 Keystore에 남고, 저장소에는 IV와 ciphertext만 둔다.
- 암호문 복호화 실패 시 저장 token을 삭제해 손상된 token이 반복 사용되지 않도록 했다.
- 생체 인증 요구는 MVP 자동 refresh/pairing 흐름을 막을 수 있어 이번 단계에서는 적용하지 않았다.
- 실제 기기에서 Keystore provider와 앱 재시작 후 복호화 smoke는 Android SDK License 승인 및 APK 설치 이후 필요하다.

### 테스트/검증 결과

- Android 공식 문서 확인: Android Keystore `KeyGenerator`, `KeyGenParameterSpec`, `AndroidKeyStore` 사용 패턴 확인
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 119 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- Android Keystore/static contract check → 통과
- `./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락 blocker 유지 확인 (`build-tools;35.0.0`, `platforms;android-36`)

### 커밋 예정 Korean Lore 메시지

```text
Android 리모트 토큰을 Keystore 암호화 저장으로 옮긴다

Constraint: Android APK 설치 검증 전이라도 외부망 device token을 평문 SharedPreferences에 남기지 않아야 함
Rejected: AndroidX Security Crypto dependency 추가 | 새 dependency 없이 Android framework Keystore로 MVP 보안 경계를 먼저 강화할 수 있음
Confidence: medium
Scope-risk: narrow
Directive: SDK License 승인 후 실제 기기에서 pairing token 저장, 앱 재시작 복호화, 토큰 삭제 smoke를 확인할 것
Tested: Android 공식 Keystore 문서 확인; ./.venv/bin/python -m pytest tests/test_remote_routes.py; ./.venv/bin/python -m pytest; swift build; Android wrapper/static contract check; ./gradlew :app:assembleDebug --stacktrace blocker 재확인; git diff --check
Not-tested: Android APK 설치 후 Keystore provider 실기기 동작, 생체 인증 연동
```

---

## 2026-05-11 — Android 클라이언트 정적 계약 테스트벤치 고정

### 작업 범위

- `tests/test_remote_android_client_static.py`를 추가해 Android 클라이언트의 핵심 계약을 pytest로 고정했다.
- Gradle/Compose/wrapper 버전, Android manifest 권한, Remote Agent endpoint 문자열, Keystore token 저장, Android Intent/Usage Access 경계, SDK License blocker 문서를 검증한다.
- Android 앱 변경 검증을 임시 스크립트가 아니라 기본 Python 테스트벤치에 포함했다.
- TODO에 Android 정적 계약 pytest 추가 완료 항목을 기록했다.

### 자체 코드 리뷰 메모

- Android SDK License 수락 전에는 APK compile 검증이 불가능하므로, 현재 가능한 회귀 방어는 정적 계약 테스트가 가장 안전하다.
- 테스트는 빌드 산출물이나 로컬 SDK 상태에 의존하지 않고 repo 파일만 확인한다.
- endpoint/권한/Keystore 계약을 명시적으로 확인해 Android 코드가 macOS에서 검증한 Remote Agent 계약에서 drift되는 것을 막는다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_android_client_static.py` → 6 passed
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 125 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- `./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락 blocker 유지 확인 (`build-tools;35.0.0`, `platforms;android-36`)

### 커밋 예정 Korean Lore 메시지

```text
Android 리모트 앱 계약을 Python 테스트벤치에 고정한다

Constraint: Android SDK License 승인 전에는 APK compile 검증을 완료할 수 없으므로 repo-local 정적 계약 테스트로 drift를 먼저 막아야 함
Rejected: ad-hoc Python 검사만 유지 | 반복 실행되는 pytest에 포함하지 않으면 이후 변경에서 Android 계약 회귀를 놓칠 수 있음
Confidence: high
Scope-risk: narrow
Directive: SDK License 승인 후 이 정적 테스트와 assembleDebug를 함께 Android 변경의 기본 검증으로 유지할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_android_client_static.py (6 passed); ./.venv/bin/python -m pytest tests/test_remote_routes.py; ./.venv/bin/python -m pytest; swift build; ./gradlew :app:assembleDebug --stacktrace blocker 재확인; git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator smoke
```

---

## 2026-05-11 — macOS 클라이언트 정적 계약 테스트벤치 고정

### 작업 범위

- `tests/test_remote_macos_client_static.py`를 추가해 macOS SwiftUI 클라이언트의 핵심 계약을 pytest로 고정했다.
- Swift Package executable target, SwiftUI app entry, Remote API DTO snake_case coding keys, endpoint 문자열, Bearer auth header, Keychain service/account 경계를 검증한다.
- SwiftPM `XCTest`는 현재 CommandLineTools 환경에서 모듈을 찾지 못해 패키지 구조 변경 없이 repo-local Python 정적 테스트로 회귀 방어를 추가했다.

### 자체 코드 리뷰 메모

- macOS 앱은 이미 `swift build`로 compile 검증되지만, DTO coding key drift는 빌드만으로는 서버 계약 불일치를 충분히 설명하지 못한다.
- 정적 테스트는 macOS SDK/XCTest 상태와 무관하게 기본 `pytest`에 포함되어 CI/로컬 테스트벤치에서 반복 실행된다.
- Keychain service/account 문자열을 테스트해 device token 저장 경계가 임의로 흔들리지 않도록 했다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py` → 4 passed
- `swift test` → 실패: CommandLineTools 환경에서 `no such module 'XCTest'`
- `./.venv/bin/python -m pytest tests/test_remote_android_client_static.py` → 6 passed
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 129 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.08s)
- `./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락 blocker 유지 확인 (`build-tools;35.0.0`, `platforms;android-36`)

### 커밋 예정 Korean Lore 메시지

```text
macOS 리모트 앱 계약도 Python 테스트벤치에 고정한다

Constraint: 현재 CommandLineTools 환경의 SwiftPM test는 XCTest 모듈을 찾지 못해 Swift package test로 DTO 계약을 고정할 수 없음
Rejected: swift test target 유지 | 로컬 검증 환경에서 실패하는 테스트 target은 기본 검증 루프를 불안정하게 만듦
Confidence: high
Scope-risk: narrow
Directive: Xcode/XCTest가 준비된 환경에서는 Swift unit test를 재도입하되, 이 repo-local 계약 pytest는 계속 유지할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py (4 passed); swift test 실패 원인 확인; ./.venv/bin/python -m pytest tests/test_remote_android_client_static.py; ./.venv/bin/python -m pytest tests/test_remote_routes.py; ./.venv/bin/python -m pytest; swift build; ./gradlew :app:assembleDebug --stacktrace blocker 재확인; git diff --check
Not-tested: Swift XCTest 기반 unit test, 실제 macOS 앱 GUI 클릭 smoke
```

---

## 2026-05-11 — macOS 전원 capability 기반 UI 방어

### 작업 범위

- macOS `RemoteStatus` 모델에 `auth_required`, `pairing`, `power.supported_actions`, `power.target_host`를 추가로 반영했다.
- macOS 앱 상태 패널에 전원 상태, 지원 명령, 대상 host를 표시하도록 했다.
- Remote Agent의 power adapter가 미설정이거나 특정 action을 지원하지 않으면 PC 전원 버튼을 비활성화하도록 했다.
- 비활성 상태에서 명령 호출이 들어와도 ViewModel에서 한번 더 차단하고 안내 메시지를 남기도록 했다.
- macOS 정적 계약 pytest에 power model/UI gating 검증을 추가했다.

### 자체 코드 리뷰 메모

- 서버는 미설정 전원 명령을 안전하게 거절하지만, 클라이언트가 버튼을 활성 상태로 보여주면 사용자가 실제 동작 가능으로 오해할 수 있다.
- UI gating은 서버 보안을 대체하지 않고 사용성/오작동 방지 계층으로만 동작한다.
- `supported_actions`가 비어 있으면 구버전/불완전 응답 호환을 위해 configured 상태에서는 버튼을 허용하지만, 현재 서버 응답은 명시적 supported action 목록을 제공한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py` → 5 passed
- `./.venv/bin/python -m pytest tests/test_remote_android_client_static.py` → 6 passed
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 130 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (1.33s)
- `./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락 blocker 유지 확인 (`build-tools;35.0.0`, `platforms;android-36`)

### 커밋 예정 Korean Lore 메시지

```text
macOS 앱이 전원 capability에 맞춰 위험 버튼을 비활성화한다

Constraint: 전원 adapter 미설정 상태에서도 서버는 안전하게 거절하지만, macOS 선행 앱은 실제 동작 가능 여부를 UI에 반영해야 함
Rejected: 서버 거절 메시지만 노출 | 사용자가 위험 명령 버튼을 활성 상태로 오해할 수 있어 선행 앱 UX 검증이 약해짐
Confidence: high
Scope-risk: narrow
Directive: 새 power action을 추가할 때는 서버 supported_actions, macOS gating, Android gating 테스트를 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py (5 passed); ./.venv/bin/python -m pytest tests/test_remote_android_client_static.py; ./.venv/bin/python -m pytest tests/test_remote_routes.py; ./.venv/bin/python -m pytest; swift build; ./gradlew :app:assembleDebug --stacktrace blocker 재확인; git diff --check
Not-tested: 실제 macOS 앱 GUI 클릭 smoke, 실제 SmartThings/SSH 전원 동작, Android SDK License 수락 이후 APK assemble/install
```

---

## 2026-05-11 — Android 전원 capability 기반 UI 방어 전파

### 작업 범위

- Android `RemoteStatus` 모델에 `RemotePowerStatus`를 추가하고 `power.supported_actions`, `power.target_host`, `configured`, `status`를 파싱하도록 했다.
- Android 앱 상태 카드에 전원 상태, 지원 명령, 대상 host를 표시하도록 했다.
- Remote Agent의 power adapter가 미설정이거나 특정 action을 지원하지 않으면 Android 전원 버튼을 비활성화하도록 했다.
- `powerCommand`에서 ViewModel/Compose 상태를 재확인해 UI 우회 호출도 차단하도록 했다.
- Android 정적 계약 pytest에 power model/UI gating 검증을 추가했다.

### 자체 코드 리뷰 메모

- macOS에서 보강한 전원 capability UX를 Android에도 전파해 양쪽 클라이언트가 같은 Remote Agent 계약을 따른다.
- 서버의 allowlist/거절 경계는 유지하고, Android UI는 사용자가 실행 불가능한 전원 명령을 누르지 않도록 안내하는 역할만 한다.
- `supported_actions`가 비어 있으면 구버전/불완전 응답 호환을 위해 configured 상태에서는 허용하지만, 현재 Remote Agent는 명시적 action 목록을 반환한다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_android_client_static.py` → 7 passed
- `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py` → 5 passed
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 131 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- `./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락 blocker 유지 확인 (`build-tools;35.0.0`, `platforms;android-36`)

### 커밋 예정 Korean Lore 메시지

```text
Android 앱도 전원 capability에 맞춰 위험 버튼을 비활성화한다

Constraint: Android APK compile 전이라도 macOS에서 검증한 power capability UX를 Android 코드에 전파해 계약 drift를 막아야 함
Rejected: Android 전원 버튼을 항상 활성 유지 | adapter 미설정/미지원 action을 실제 동작 가능처럼 보이게 만들어 원격 전원 UX 검증이 약해짐
Confidence: high
Scope-risk: narrow
Directive: 새 power action을 추가할 때는 서버 supported_actions, macOS gating, Android gating 테스트를 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_android_client_static.py (7 passed); ./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py; ./.venv/bin/python -m pytest tests/test_remote_routes.py; ./.venv/bin/python -m pytest; swift build; ./gradlew :app:assembleDebug --stacktrace blocker 재확인; git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android device/emulator 전원 버튼 smoke, 실제 SmartThings/SSH 전원 동작
```

---

## 2026-05-11 — Remote API power status 계약 alias 고정

### 작업 범위

- 서버 power status 응답에 클라이언트가 표시하는 `status` alias를 추가하고 기존 `state`도 유지했다.
- 서버 power status 응답에 `target_host`를 추가해 macOS/Android 상태 패널의 대상 표시 계약을 맞췄다.
- 미설정 adapter도 `status: unknown`, `target_host: ""`, `supported_actions: []`를 반환하도록 했다.
- `/remote/status`와 `/remote/power/status`가 configured/default 양쪽에서 클라이언트 gating 필드를 제공한다는 테스트를 강화했다.

### 자체 코드 리뷰 메모

- macOS/Android UI가 `power.status`를 표시하도록 구현되어 있었지만 서버는 `state`만 반환하고 있어, UI에는 fallback unknown만 보일 수 있었다.
- 서버에 alias를 추가해 기존 `state` 소비자와 신규 `status` 소비자를 모두 지원한다.
- `target_host`는 SSH 설정이 완성된 경우에만 반환하고, 미설정/default 상태에서는 빈 문자열로 둔다.

### 테스트/검증 결과

- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest tests/test_remote_android_client_static.py` → 7 passed
- `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py` → 5 passed
- `./.venv/bin/python -m pytest` → 131 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- `./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락 blocker 유지 확인 (`build-tools;35.0.0`, `platforms;android-36`)

### 커밋 예정 Korean Lore 메시지

```text
Remote API power status가 클라이언트 gating 필드를 안정적으로 제공한다

Constraint: macOS/Android 클라이언트가 power.status와 target_host를 표시하므로 서버 응답 계약이 이를 제공해야 함
Rejected: 클라이언트 fallback unknown 유지 | 서버가 알고 있는 전원 상태를 UI에 전달하지 못해 capability gating 검증이 약해짐
Confidence: high
Scope-risk: narrow
Directive: power status 필드명을 변경할 때는 state/status alias와 양쪽 클라이언트 정적 계약 테스트를 함께 갱신할 것
Tested: ./.venv/bin/python -m pytest tests/test_remote_routes.py (10 passed); ./.venv/bin/python -m pytest tests/test_remote_android_client_static.py; ./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py; ./.venv/bin/python -m pytest; swift build; ./gradlew :app:assembleDebug --stacktrace blocker 재확인; git diff --check
Not-tested: 실제 SmartThings/SSH 전원 상태 조회, Android SDK License 수락 이후 APK assemble/install
```

---

## 2026-05-11 — Android UsageStats 최근 전면 앱 조회 기반 추가

### 작업 범위

- Android `AndroidIntegration`에 `UsageStatsManager.queryEvents` 기반 최근 전면 앱 조회 helper를 추가했다.
- `UsageEvents.Event.MOVE_TO_FOREGROUND`와 `ACTIVITY_RESUMED` 이벤트를 훑어 최근 package/class/timestamp를 `AndroidUsageSnapshot`으로 반환한다.
- Android UI에 `최근 앱` 버튼과 최근 전면 앱 표시를 추가해 Usage Access 허용 후 모바일 실행 추적 smoke를 할 수 있게 했다.
- Android 정적 계약 pytest에 UsageStatsManager/queryEvents/UI 계약 검증을 추가했다.
- Android README, 구동 환경 가이드, TODO를 최근 전면 앱 조회 기반 기준으로 갱신했다.

### 자체 코드 리뷰 메모

- `PACKAGE_USAGE_STATS`는 manifest 선언만으로 허용되지 않으므로 기존처럼 설정 화면 진입을 제공하고, 실제 조회는 권한이 있을 때만 수행한다.
- 이번 단계는 세션 sync 전 단계로, Android 로컬에서 최근 전면 앱을 읽을 수 있는 최소 기반을 마련한다.
- 실제 UsageStats provider 동작은 APK 설치와 사용자가 Usage Access를 허용한 실기기/emulator에서만 검증 가능하다.

### 테스트/검증 결과

- Android 공식 문서/API 확인: `UsageStatsManager`, `UsageEvents` 이벤트 기반 조회 경계 확인
- `./.venv/bin/python -m pytest tests/test_remote_android_client_static.py` → 8 passed
- `./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py` → 5 passed
- `./.venv/bin/python -m pytest tests/test_remote_routes.py` → 10 passed, 4 warnings
- `./.venv/bin/python -m pytest` → 132 passed, 4 warnings
- `swift build` in `remote_clients/macos/HomeworkHelperRemote` → Build complete (0.07s)
- `./gradlew :app:assembleDebug --stacktrace` → Android SDK License 미수락 blocker 유지 확인 (`build-tools;35.0.0`, `platforms;android-36`)

### 커밋 예정 Korean Lore 메시지

```text
Android 앱에 UsageStats 기반 최근 전면 앱 조회 기반을 둔다

Constraint: Android SDK License 승인 전이라 실기기 Usage Access smoke는 못 하지만 세션 추적 기반 코드를 먼저 고정해야 함
Rejected: Usage Access 설정 버튼만 유지 | 권한 모델만 있고 실제 조회 경로가 없으면 Android-PC 세션 매칭 기반을 검증할 수 없음
Confidence: medium
Scope-risk: narrow
Directive: SDK License 승인 후 실제 기기에서 Usage Access 허용, 최근 전면 앱 조회, 세션 sync 순서로 검증을 확장할 것
Tested: Android 공식 UsageStats API 확인; ./.venv/bin/python -m pytest tests/test_remote_android_client_static.py (8 passed); ./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py; ./.venv/bin/python -m pytest tests/test_remote_routes.py; ./.venv/bin/python -m pytest; swift build; ./gradlew :app:assembleDebug --stacktrace blocker 재확인; git diff --check
Not-tested: Android SDK License 수락 이후 APK assemble/install, 실제 Android Usage Access 허용 후 UsageStats provider 동작
```
