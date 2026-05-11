# HomeworkHelper Remote Android

Kotlin + Jetpack Compose 기반 Android 네이티브 리모트 컨트롤러 초안입니다. macOS 앱에서 먼저 검증한 Remote Agent API 계약을 Android로 전파하는 것을 목표로 합니다.

## 현재 범위

- Remote Agent URL / device name 저장 및 Bearer token Android Keystore 암호화 저장
- `/remote/pair/confirm` pairing code 입력 및 token 저장
- `/remote/status`, `/remote/processes`, `/remote/shortcuts`, `/remote/devices` 조회
- `/remote/dashboard/summary` 조회 및 Compose 플레이 요약 카드 표시
- `/remote/beholder/incidents` 조회 및 Compose Beholder 알림 카드 표시
- PC 게임 실행, 웹 숏컷 열기, 전원 명령 호출
- 등록 device token revoke 호출
- Android package name 수동 입력 후 `PackageManager.getLaunchIntentForPackage()`로 로컬 앱 실행
- `PACKAGE_USAGE_STATS` 선언, Usage Access 설정 화면 진입, 최근 전면 앱 조회 smoke
- Android 11+ package visibility 대응을 위한 launcher intent `<queries>` 선언

## 빌드

이 개발 세션에서 Homebrew로 OpenJDK 17, Gradle, Android command line tools를 설치하고 Gradle wrapper를 생성했습니다. 다만 Android SDK package 설치는 Google Android SDK License 수락이 필요해 중단되어 `assembleDebug`는 아직 완료되지 않았습니다.

```bash
cd remote_clients/android/HomeworkHelperRemote
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools
./gradlew :app:assembleDebug
```

현재 확인된 blocker:

- `sdkmanager --licenses`로 Google Android SDK License를 수락해야 함
- 그다음 `sdkmanager --install "platform-tools" "platforms;android-36" "build-tools;35.0.0"`로 Gradle이 요구한 SDK package를 설치함
- 라이선스 수락 전 Gradle은 `build-tools;35.0.0`, `platforms;android-36` 미수락으로 실패함

Gradle 구성은 Android Gradle Plugin 8.13.0, Kotlin 2.2.21, Kotlin Compose compiler plugin 2.2.21, Compose BOM 2026.03.00을 사용합니다. Gradle wrapper는 9.5.0으로 고정했습니다.

## 로컬 연결 흐름

1. PC/macOS에서 Remote Agent 실행:

```bash
HH_API_HOST=0.0.0.0 HH_REMOTE_REQUIRE_AUTH=1 ./.venv/bin/python homework_helper.pyw --server
```

2. PC 로컬에서 pairing code 발급:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

3. Android 앱에 `http://<PC tailnet 또는 LAN IP>:8000`, device name, 6자리 pairing code 입력 후 `페어링 완료`.
4. `새로고침`으로 PC 게임/숏컷/device 목록을 동기화.
5. PC 실행 버튼, 웹 숏컷, 전원 버튼을 Remote Agent API로 호출.

## Android 로컬 실행 / Usage Access

- Android 패키지명은 현재 수동 입력으로 검증합니다. 예: `com.example.game`
- 앱 실행은 Android package visibility와 launcher intent에 의존하므로 실제 기기에서 설치된 패키지로 smoke test가 필요합니다.
- Usage Access는 manifest 선언만으로 활성화되지 않습니다. 앱의 `Usage 권한` 버튼으로 Android 설정에 들어가 사용자가 직접 허용해야 합니다.
- APK 설치 후 `./.venv/bin/python tools/smoke_android_remote_controller.py --skip-install --skip-launch --require-usage-access`로 `GET_USAGE_STATS` appop이 `allow` 상태인지 gate할 수 있습니다.

## 다음 단계

- 실제 기기에서 Android Keystore token 저장/마이그레이션 smoke test
- PC 게임과 Android package/deeplink 매칭 데이터 모델 추가
- UsageStatsManager 기반 모바일 세션 시작/종료 기록과 Remote Agent 세션 sync
- Gradle wrapper 고정 및 CI/실기기 `assembleDebug` + smoke 검증
