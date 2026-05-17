# HomeworkHelper Remote Android

Kotlin + Jetpack Compose 기반 Android 네이티브 리모트 클라이언트입니다. macOS Remote Client에서 검증한 Remote Agent API 계약을 Android로 전파했고, `docs/remote/android-client-design.md`의 Full-parity 설계를 따라 ViewModel/Repository/Material 3 tab 구조로 재구축했습니다.

## 현재 범위

- Remote Agent URL / device name 저장
- Bearer token Android Keystore AES/GCM 암호화 저장 및 legacy plaintext preference migration
- `/remote/pair/confirm` pairing code 입력, `/remote/tokens/refresh` token 갱신, `/remote/devices` 조회/폐기
- `/remote/status`, `/remote/capabilities`, `/remote/readiness`, `/remote/processes`, `/remote/shortcuts` 조회
- `/remote/dashboard/summary` 기반 플레이 요약/모바일 플레이 집계 카드
- `/remote/beholder/incidents` 기반 Beholder read-only 알림 카드
- Tailscale 앱/스토어 deep link, host `/remote/tailscale/ensure`, suggested base URL 기반 Tailscale-first 연결 보조
- PC 게임 실행, process progress/status 표시, 웹 숏컷 열기, 전원 setup/config 저장 및 capability-gated 전원 명령 호출
- `/remote/game-links` 기반 PC process와 Android package mapping 생성/조회
- Android package name launcher intent 실행
- `PACKAGE_USAGE_STATS` 선언, Usage Access 설정 화면 진입, 최근 전면 앱 조회, game-link 기반 `usage_stats` 모바일 세션 sync
- `/remote/logging/config` host diagnostic logging toggle, device revoke/purge, SmartThings probe, SSH key registration 보조
- Android 11+ package visibility 대응 launcher intent `<queries>` 선언

## 빌드

요구 도구:

- OpenJDK 17
- Android command line tools 또는 Android Studio SDK
- `platform-tools`, `platforms;android-36`, `build-tools;35.0.0`
- Android Gradle Plugin 8.13.0, Kotlin 2.2.21, Kotlin Compose compiler plugin 2.2.21, Compose BOM 2026.03.00
- Gradle wrapper 9.5.0

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleDebug
```

검증된 산출물 계약:

- APK: `app/build/outputs/apk/debug/app-debug.apk`
- package: `dev.homeworkhelper.remote`
- version: `0.1.0`
- minSdk: 26
- targetSdk: 36
- permissions: `INTERNET`, `PACKAGE_USAGE_STATS`

## 로컬 연결 흐름

1. PC/macOS host에서 Remote Agent 실행:

```bash
HH_API_HOST=0.0.0.0 HH_REMOTE_REQUIRE_AUTH=1 ./.venv/bin/python homework_helper.pyw --server
```

2. host loopback에서 pairing code 발급:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

3. Android 앱에 `http://<host LAN 또는 tailnet IP>:8000`, device name, 6자리 pairing code 입력 후 `페어링 완료`.
4. `새로고침`으로 PC 게임, 웹 숏컷, device, dashboard, Beholder, game-link, mobile-session 상태 동기화.
5. PC 실행, 웹 숏컷, 전원, Android package 실행, 모바일 세션 시작/종료를 앱에서 검증.

Android emulator에서 host loopback server에 붙을 때는 `http://10.0.2.2:8000`을 사용합니다.

## Usage Access와 Android 로컬 실행

- Android package launch는 `PackageManager.getLaunchIntentForPackage()`에 의존합니다.
- 실제 package가 설치되어 있고 launcher activity가 있어야 실행됩니다.
- Usage Access는 manifest 선언만으로 활성화되지 않습니다. 앱의 `Usage 권한` 버튼으로 Android 설정에 들어가 사용자가 직접 허용해야 합니다.
- 권한 허용 후 `Usage 동기화`는 최근 전면 앱 package와 game-link를 비교해 `usage_stats` source의 mobile session start/end를 호출합니다.

## 검증

기본 워크플로우는 **내부 테스트 → 실기기 테스트** 2단계입니다. 에뮬레이터는 선택 사항이며 기본 release gate가 아닙니다.

### 1단계: 내부 테스트

Android runtime 없이 빌드/계약을 확인합니다.

```bash
./.venv/bin/python tools/verify_android_internal.py
```

포함 범위: 정적 계약 pytest, SDK readiness, `:app:assembleDebug --stacktrace`, APK artifact 계약 검사.

### 2단계: 실기기 자동 테스트

Android 실기기를 USB 디버깅으로 연결한 뒤 실행합니다.

```bash
./.venv/bin/python tools/verify_android_device.py
```

여러 기기가 연결된 경우:

```bash
./.venv/bin/python tools/verify_android_device.py --device <adb-serial>
```

이 단계는 APK install/launch, UsageStats appop 보고, `adb reverse` 기반 임시 Remote Agent 연결, pairing code 입력, 데이터 sync, mobile session start/end, UsageStats sync, 앱 재시작 후 Android Keystore token persistence를 자동 검증합니다.

## Full-parity 후속 작업

자세한 설계는 `docs/remote/android-client-design.md`를 기준으로 합니다. 현재 구조 재구축과 내부 테스트 게이트는 완료되었습니다.

남은 우선순위:

1. `tools/verify_android_device.py`로 실기기 Stage 2를 실행해 pairing, Keystore persistence, UsageStats sync, adb reverse 흐름을 확인.
2. 런타임 QA 결과에 따라 process/resource icon cache와 세부 visual polish를 추가.
3. Android local log export/share가 실제 필요해질 때 token-safe export만 추가.
