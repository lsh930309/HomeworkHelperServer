# Remote Controller 작업 보고서

브랜치: `dev-remote`
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
