# HomeworkHelper Remote Controller 구동 환경 가이드

작성일: 2026-05-12
현재 작업 브랜치: `dev-remote`
main 기준점: `4052da3 새 GUI와 데이터 안전 경계를 main에 통합한다`
작업 브랜치 이력: remote-controller 변경분은 `dev-remote`에 유지하고 `main`은 기준점으로 복구 완료

## 1. 개발/로컬 검증

기본 서버는 기존처럼 loopback에만 열린다.

```bash
./.venv/bin/python homework_helper.pyw --server
```

기본값:

- host: `127.0.0.1`
- port: `8000`
- remote auth: 등록 디바이스가 없고 `HH_REMOTE_TOKEN`도 없으면 로컬 개발 편의를 위해 비활성

macOS 앱은 기본 URL `http://127.0.0.1:8000`으로 접속한다.

주요 Remote API:

- `GET /remote/status`
- `GET /remote/capabilities`
- `POST /remote/tokens/refresh`
- `GET /remote/processes`
- `POST /remote/processes/{id}/launch`
- `GET /remote/shortcuts`
- `POST /remote/shortcuts/{id}/open`
- `GET /remote/dashboard/summary` — PC playtime metrics와 `mobile_metrics` 모바일 세션 집계 포함
- `GET /remote/beholder/incidents`
- `GET /remote/game-links`
- `POST /remote/game-links`
- `GET /remote/mobile-sessions/active`
- `POST /remote/mobile-sessions/start`
- `POST /remote/mobile-sessions/end`
- `GET /remote/power/status`
- `GET /remote/power/config`
- `PUT /remote/power/config`
- `POST /remote/power/{wake|sleep|restart|shutdown}`

## 2. 페어링 절차

1. PC/서버 로컬에서 pairing code 발급:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

2. macOS 앱에서 Base URL과 pairing code를 입력하고 `페어링`을 누른다.
3. 앱은 `/remote/pair/confirm` 응답으로 받은 device token을 macOS Keychain에 저장한다.
4. 등록 디바이스가 하나라도 생기면 `/remote/*` 보호 API는 token을 요구한다.
5. macOS 앱의 `등록 디바이스` 섹션에서 현재 device token을 갱신하거나 폐기할 수 있다.

주의: `/remote/pair/start`는 loopback 요청 또는 이미 인증된 디바이스 요청에서만 허용된다.

## 3. Tailscale/ZeroTier 바인딩

외부망에서 직접 접근하려면 Remote Agent를 tailnet/virtual-network IP 또는 전체 인터페이스에 bind한다.

예시:

```bash
HH_API_HOST=0.0.0.0 \
HH_API_PORT=8000 \
HH_REMOTE_REQUIRE_AUTH=1 \
./.venv/bin/python homework_helper.pyw --server
```

권장:

- Tailscale/ZeroTier 방화벽에서 개인 기기만 접근 허용
- 최초 pairing은 PC 로컬에서 `/remote/pair/start`로 발급
- `HH_REMOTE_REQUIRE_AUTH=1` 유지
- `HH_REMOTE_TOKEN` 또는 device pairing token 없이 공인망/터널에 노출 금지

tailnet/LAN URL이 실제로 열렸는지 확인하려면 connectivity smoke를 실행한다.

```bash
./.venv/bin/python tools/smoke_remote_controller_connectivity.py \
  --base-url http://100.x.y.z:8000 \
  --token "<paired-device-token>" \
  --expect-auth
```

이 smoke는 서버를 직접 시작하지 않는다. 이미 실행 중인 Remote Agent에 대해 `/remote/status`의 metadata, counts, capabilities, power 계약과 Bearer token 인증 경계를 확인한다.

## 4. 전원 제어 설정

실제 파일은 사용자 데이터 디렉터리에 둔다.

- macOS/Linux 개발 환경 예: `~/.config/HomeworkHelper/homework_helper_data/remote_power_config.json`
- Windows 설치 환경 예: `%APPDATA%/HomeworkHelper/homework_helper_data/remote_power_config.json`

템플릿은 저장소 루트의 `remote_power_config.example.json`을 복사해 사용한다.

```bash
cp remote_power_config.example.json ~/.config/HomeworkHelper/homework_helper_data/remote_power_config.json
```

필드:

- `smartthings_device_id`: SmartThings WoL 장치 ID
- `smartthings_cli_path`: SmartThings CLI 경로
- `ssh_host`: Windows PC의 Tailscale host, DDNS, 또는 공인 IP
- `ssh_port`: Windows OpenSSH 포트
- `ssh_user`: Windows 사용자
- `ssh_key_path`: SSH private key 경로
- `status_timeout_seconds`: TCP 상태 확인 timeout

환경변수 override도 지원한다.

```bash
HH_REMOTE_SMARTTHINGS_DEVICE_ID=...
HH_REMOTE_SMARTTHINGS_CLI_PATH=/opt/homebrew/bin/smartthings
HH_REMOTE_SSH_HOST=...
HH_REMOTE_SSH_PORT=50022
HH_REMOTE_SSH_USER=...
HH_REMOTE_SSH_KEY_PATH=~/.ssh/id_ed25519
HH_REMOTE_STATUS_TIMEOUT_SECONDS=4
```

보안 주의:

- `remote_power_config.json`에는 개인 IP, 장치 ID, key path가 들어갈 수 있으므로 Git에 커밋하지 않는다.
- Remote API는 action enum만 받고 임의 shell 명령을 받지 않는다.
- 전원 명령 결과는 `remote_command_audit.jsonl`에 기록된다.

전원 제어 설정이 실제 명령을 보내기 전에 충분히 채워졌는지 확인하려면 다음 preflight를 실행한다.

```bash
./.venv/bin/python tools/check_remote_power_readiness.py --allow-blocker
```

이 preflight와 macOS/Android `전원 설정` 카드는 SmartThings 또는 SSH 명령을 실행하지 않고 `remote_power_config.json`, SmartThings CLI path, SSH host/user/key path, 지원 가능한 action 목록만 보고하거나 저장한다.


## 5. Android 클라이언트 초안

Android 네이티브 앱 초안은 `remote_clients/android/HomeworkHelperRemote`에 둔다. 현재 개발 환경에는 OpenJDK 17, Android command line tools, Android SDK license/package, Gradle wrapper가 준비되어 있고 `:app:assembleDebug`가 성공해 debug APK까지 산출된다. macOS 앱에서 검증한 Remote Agent API 계약은 Kotlin + Jetpack Compose UI로 전파했다.

현재 Android 범위:

- Remote Agent URL/device name 저장 및 device token Android Keystore 암호화 저장
- pairing code confirm으로 device token 발급
- status/process/shortcut/device 조회
- dashboard summary 조회 및 플레이 요약/모바일 플레이 집계 카드 표시
- Beholder pending incident 조회 및 read-only 알림 카드 표시
- PC 게임 실행, 웹 숏컷 열기, 전원 명령 호출
- 등록 device token revoke
- Android package name 수동 입력 기반 launcher Intent 실행
- `/remote/game-links`로 PC process와 Android package mapping 조회/생성 계약 전파
- macOS 앱에서 PC process ID와 Android package를 입력해 mapping 생성
- Android 앱에서 PC process ID와 Android package를 입력해 mapping 생성하고 등록 package를 로컬 launcher Intent로 실행
- Android-PC mapping 기반 모바일 세션 수동 start/end API 및 UI 계약
- Usage Access 설정 화면 연결, `PACKAGE_USAGE_STATS` 권한 선언, 최근 전면 앱 조회와 game-link 기반 `usage_stats` 자동 세션 sync

빌드 가능 환경에서는 Gradle wrapper를 사용한다.

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleDebug
```

2026-05-12 검증에서 `sdkmanager --licenses`와 `sdkmanager --install "platform-tools" "platforms;android-36" "build-tools;35.0.0"`를 완료했고, AndroidX 및 Java/Kotlin 17 toolchain 설정을 저장소에 고정해 `./gradlew :app:assembleDebug --stacktrace`가 성공했다. 추가로 Android emulator/system image 설치를 시도했으나 로컬 디스크 여유 공간 부족(`No space left on device`, 약 5.5GiB available)으로 system image 준비가 중단되어 adb install/launch smoke는 실제 device/emulator 연결 후 재개한다.

주의: Android token은 Android Keystore AES/GCM key로 암호화해 저장한다. 기존 초안의 평문 `SharedPreferences` token은 최초 실행 시 암호화 저장소로 마이그레이션하고 제거한다.

## 6. 현재 검증 명령

통합 검증:

```bash
./.venv/bin/python tools/verify_remote_controller.py \
  --require-branch dev-remote \
  --expect-main-hash 4052da3 \
  --allow-android-device-blocker
```

`--allow-android-license-blocker`는 Android SDK License 수락 전의 알려진 blocker만 허용한다. License 수락 및 SDK package 설치가 끝난 현재 상태에서는 이 flag를 사용하지 않는다.

`--allow-android-device-blocker`는 APK가 산출된 뒤에도 연결된 adb device/emulator가 없을 때만 허용하는 gate다. 이 flag 없이 verifier를 실행하면 device/emulator 부재를 실패로 취급한다.

`--require-branch dev-remote`와 `--expect-main-hash 4052da3`는 remote-controller 작업이 `dev-remote`에서만 진행되고 `main`/`origin/main`이 기준점에서 drift하지 않았는지 확인하는 보호 gate다.

Remote Agent를 TestClient가 아닌 실제 loopback server process로 띄워 pairing/token 경계를 확인하려면 다음 smoke를 단독 실행한다.

```bash
./.venv/bin/python tools/smoke_remote_controller_runtime.py
```

이 smoke는 임시 `HOME`과 임시 loopback port를 사용해 `/remote/status`, `/remote/pair/start`, `/remote/pair/confirm`, token 없는 요청의 401, token 있는 `/remote/devices` 조회를 검증한다.

Swift `RemoteAPIClient.swift`와 `RemoteModels.swift`를 실제로 컴파일해 Remote Agent와 통신하는 macOS-native smoke는 다음 명령으로 단독 실행한다.

```bash
./.venv/bin/python tools/smoke_macos_remote_api_client.py
```

이 smoke는 Python으로 pairing code만 발급한 뒤, 임시 Swift binary가 `confirmPairing`, Bearer token `status`, token refresh, game-link 생성/조회, 모바일 세션 start/end, dashboard/Beholder, `devices` 조회를 수행해 macOS 클라이언트 DTO/endpoint/token 경계를 검증한다.

SwiftUI 버튼이 호출하는 ViewModel 상태 전이를 실제 Remote Agent와 함께 검증하려면 다음 smoke를 실행한다.

```bash
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py
```

이 smoke는 production `RemoteDashboardViewModel.swift`와 `RemoteAPIClient.swift`를 같이 컴파일하고, 임시 in-memory token store를 주입해 pairing/token 저장, refresh, power guard, game-link 생성, 모바일 세션 start/end, token refresh, device refresh를 검증한다. SwiftUI 창 클릭 자동화는 아니지만 macOS 앱 버튼의 핵심 기능 경계를 deterministic하게 확인한다.

Android APK가 생성된 뒤 device/emulator에 install + launch smoke를 수행하려면 다음 명령을 사용한다.

```bash
./.venv/bin/python tools/smoke_android_remote_controller.py
```

SDK package/license 또는 APK 산출 전에는 준비 상태만 확인할 수 있다. APK 산출 후 device/emulator가 없으면 install/launch smoke는 `Expected exactly one connected adb device` blocker를 보고한다.

```bash
./.venv/bin/python tools/check_android_sdk_readiness.py --allow-blocker
./.venv/bin/python tools/check_android_apk_artifact.py
./.venv/bin/python tools/smoke_android_remote_controller.py --allow-missing-apk
```

SDK readiness preflight는 `sdkmanager`, `adb`, `platform-tools`, `platforms;android-36`, `build-tools;35.0.0`, Android SDK license 파일 존재 여부를 변경 없이 보고한다. `tools/check_android_apk_artifact.py`는 빌드된 APK를 `aapt dump badging/permissions`로 검사해 package/version/SDK/permission 계약을 device 없이 검증한다. APK smoke는 Android manifest/applicationId 계약을 확인하고, APK가 있으면 `adb install -r`과 `adb shell am start -n dev.homeworkhelper.remote/.MainActivity`로 실제 앱 launch를 검증한다.

APK 설치 후 UsageStats 권한 상태까지 같이 보고하려면:

```bash
./.venv/bin/python tools/smoke_android_remote_controller.py --report-usage-access
```

Usage Access를 사용자가 허용한 뒤 해당 권한을 smoke gate로 강제하려면:

```bash
./.venv/bin/python tools/smoke_android_remote_controller.py --skip-install --skip-launch --require-usage-access
```

Usage Access 설정 화면을 기기에서 열어 수동 허용을 이어가려면:

```bash
./.venv/bin/python tools/smoke_android_remote_controller.py --skip-install --report-usage-access --open-usage-access-settings
```

emulator/기기에서 Android 앱 UI와 Remote Agent를 함께 end-to-end로 검증하려면:

```bash
./.venv/bin/python tools/smoke_android_remote_e2e.py
```

이 smoke는 host `127.0.0.1:8000`에 임시 Remote Agent를 띄우고 Android 기본 URL `http://10.0.2.2:8000`을 통해 실제 앱 UI를 조작한다. 검증 범위는 APK install, pairing code 입력, Android Keystore 암호화 token 저장, 앱 재시작 후 token 복호화/refresh, game-link 기반 mobile session start/end, UsageStats 권한 허용 상태에서 자동 sync 경로까지다.

개별 최소 검증:

```bash
./.venv/bin/python -m pytest tests/test_remote_routes.py
./.venv/bin/python -m pytest
cd remote_clients/macos/HomeworkHelperRemote && swift build
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:assembleDebug
```
