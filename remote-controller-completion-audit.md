# Remote Controller 완료 감사

작성/갱신: 2026-05-12
현재 작업 브랜치: `dev-remote`
최신 기능/검증 확인 commit: `0ace714 Android 검증 문서가 브랜치 gate와 game-link 현실을 따른다` 이후 Android SDK/build gate 해소 변경은 다음 커밋에 포함 예정
문서-only 보정 commit: Android SDK license/build 검증 기록은 다음 Korean Lore 커밋에 포함 예정
목표 원문: `remote-controller-technical-review.md`에서 제안한 방식대로 리모트 컨트롤 인터페이스 앱 및 구동 환경 제작에 착수한다.

## 1. 완료 판단 기준

이번 목표는 “제품 완성”이 아니라 “제안 방식대로 제작에 착수”하는 것이지만, 사용자 유의사항은 다음 산출물을 요구한다.

1. macOS 개발 환경에서 macOS 네이티브 앱을 먼저 실제 빌드/동작 확인하며 Remote API 로직을 robust하게 다진다.
2. macOS에서 검증한 Remote API/DTO/명령 모델을 Android APK 쪽으로 전파한다.
3. 신규 브랜치 `dev-remote`에서 작업하고 주기적으로 Korean Lore commit + push를 수행한다.
4. 매 커밋 직전 자체 코드 리뷰, 동작 테스트, 기초 테스트벤치 검증을 수행한다.
5. 루트에 구체적 TODO와 매 커밋 작업 보고서 2종을 지속 업데이트한다.
6. 의사결정이 필요한 지점에서는 작업을 멈추고 사용자 확인을 받는다.

## 2. prompt-to-artifact 체크리스트

| 요구사항 / gate | 현재 evidence | 판정 | 남은 gap |
| --- | --- | --- | --- |
| 기술 검토서 보존 | `remote-controller-technical-review.md` 존재 | 충족 | 없음 |
| `dev-remote` 브랜치 생성/작업 | remote-controller 변경분은 `dev-remote`/`origin/dev-remote`에 있고 `main`/`origin/main`은 `4052da3` 기준점으로 복구됨. `tools/verify_remote_controller.py --require-branch dev-remote --expect-main-hash 4052da3` gate로 verifier 단계에서 브랜치 drift를 잡을 수 있고, contract test가 pass/fail 경로를 직접 검증함 | 충족 | 브랜치 이동 금지 원칙 유지 필요 |
| Korean Lore commit + push | `a386423`, `b69457d`, `9e6142e`, `486cc75`, `f38cf0d`, `f4ff55d`, `35585dc`, `ea8dcc6`, `a1e3162`, `845b712`, `c57f961`, `5b7b26f`, `4f28b99`, `30bf741`, `c8ed3f5`, `b055b98`, 이후 UsageStats gate commit 및 문서-only 보정 commit 등 `dev-remote` commit이 Lore trailer 포함 | 충족 | 없음 |
| TODO 문서 | `remote-controller-todo.md` | 충족 | Android 후속 항목 남음 |
| 매 커밋 작업 보고서 | `remote-controller-work-report.md` | 충족 | Android 실기기 검증 후 추가 기록 필요 |
| Remote Agent API | `src/api/remote_routes.py`, `homework_helper.pyw` router include, `/remote/capabilities`, `/remote/dashboard/summary` read-only analytics summary, `/remote/beholder/incidents` read-only pending incident list, `/remote/game-links` Android-PC mapping, `/remote/mobile-sessions/start|end` 수동 모바일 세션 기록, `/remote/dashboard/summary` `mobile_metrics` 모바일 세션 집계 | 충족 | Beholder resolve flow 전체 원격화는 후속 범위 |
| Pairing/device token | `src/core/remote_pairing.py`, `/remote/pair/start`, `/remote/pair/confirm`, `/remote/tokens/refresh`, `/remote/devices` | 충족 | 실제 외부망 pairing UX는 후속 실기기 검증 필요 |
| 감사 로그 | `src/core/remote_audit.py` 및 command route 기록 | 충족 | 장기 rotation/retention 정책 후속 |
| 전원 adapter | `src/core/remote_power.py`, `remote_power_config.example.json`, power status/action API, `/remote/power/config`, macOS/Android `전원 설정` UI | 부분 충족 | 실제 SmartThings/SSH 전원 동작은 로컬 설정/장비 필요 |
| 전원 adapter readiness preflight | `tools/check_remote_power_readiness.py`가 config/CLI/key path/support action을 명령 실행 없이 보고 | 부분 충족 | 현재 실제 SmartThings CLI, SSH key, 장비 side effect smoke blocker |
| macOS SwiftUI 앱 | `remote_clients/macos/HomeworkHelperRemote` | 충족 | 실제 SwiftUI 버튼 클릭 자동화는 미검증 |
| macOS build | `swift build` 통합 verifier에서 passed | 충족 | 없음 |
| macOS API client 실통신 | `tools/smoke_macos_remote_api_client.py` → Swift `RemoteAPIClient`가 real loopback server와 pairing/status/capabilities/token refresh/game-link 생성·조회/mobile session start·end/dashboard mobile metrics/beholder/devices 통신 | 충족 | SwiftUI 창 조작 smoke는 후속 |
| macOS dashboard/Beholder/read-only 및 Android-PC 카드 | `RemoteDashboardSummary`, `RemoteBeholderIncident`, `RemoteAPIClient.dashboardSummary()/beholderIncidents()`, SwiftUI `플레이 요약`/`모바일 플레이`/`Beholder 알림`/`Android-PC 연결` 카드, macOS API smoke DTO decode, Android-PC 안내문이 수동 세션/UsageStats sync 구현 상태와 일치함 | 충족 | SwiftUI 창 조작 smoke는 후속 |
| 실제 서버 프로세스 smoke | `tools/smoke_remote_controller_runtime.py` → `homework_helper.pyw` subprocess + HTTP pairing/token 검증 | 충족 | 외부망/tailnet 실접속은 후속 |
| LAN/Tailscale/ZeroTier connectivity smoke | `tools/smoke_remote_controller_connectivity.py` → 실행 중인 Remote Agent URL과 optional token으로 `/remote/status` 계약 및 인증 경계 확인 | 부분 충족 | 실제 tailnet/LAN URL과 paired token이 필요해 아직 실행 evidence 없음 |
| Android Kotlin/Compose 전파 | `remote_clients/android/HomeworkHelperRemote`, `RemoteDashboardSummary`, `RemoteBeholderIncident`, `RemoteGameLink`, `RemoteMobileSession`, Compose `플레이 요약`/`모바일 플레이`/`Beholder 알림`/`Android-PC 연결` 생성·실행·수동/UsageStats 자동 세션 카드, `./gradlew :app:assembleDebug --stacktrace` BUILD SUCCESSFUL | 부분 충족 | 실제 device/emulator install/launch 전까지 Android runtime 보장은 불완전 |
| Android token 보안 | `AndroidTokenStore.kt` Keystore AES/GCM, legacy token migration | 정적 충족 | 실제 Android Keystore provider smoke 미완료 |
| Android UsageStats/Intent | `AndroidIntegration.kt`, manifest `PACKAGE_USAGE_STATS`, UI 경로, game-link create/package launch/mobile session card, `Usage 동기화` 자동 start/end 로직, Android README/구동 가이드가 stale game-link TODO 대신 실기기 smoke gap을 안내 | 정적 충족 | Usage Access 허용 후 실기기 provider 동작 미완료 |
| Android Gradle wrapper | `remote_clients/android/HomeworkHelperRemote/gradlew`, wrapper jar/properties | 충족 | 없음 |
| Android SDK readiness preflight | `tools/check_android_sdk_readiness.py`가 `sdkmanager`, `adb`, required SDK package, license files를 변경 없이 보고하고, 현재 `platform-tools`, `platforms;android-36`, `build-tools;35.0.0`, `android-sdk-license`, `android-sdk-preview-license` present로 passed | 충족 | 없음 |
| Android APK install/launch smoke preflight | `tools/smoke_android_remote_controller.py`가 manifest/applicationId 계약을 확인하고 APK가 있으면 `adb install -r` 및 `am start`를 수행. 현재 APK는 `app/build/outputs/apk/debug/app-debug.apk`로 산출됨 | 부분 충족 | 연결된 adb device/emulator가 없어 install/launch smoke는 `Expected exactly one connected adb device; connected=[]` blocker |
| Android UsageStats appops smoke option | `tools/smoke_android_remote_controller.py --report-usage-access`가 `GET_USAGE_STATS` appops 상태를 보고하고, `--require-usage-access`가 허용 상태를 gate하며, `--open-usage-access-settings`가 설정 화면을 열 수 있음 | 부분 충족 | 실제 device/emulator가 없어 appops allow evidence 없음 |
| Android APK assemble | Android SDK license/package 설치 후 `remote_clients/android/HomeworkHelperRemote/gradle.properties`의 AndroidX 설정과 Java/Kotlin 17 toolchain을 고정했고 `./gradlew :app:assembleDebug --stacktrace` 및 통합 verifier 내 Android assembleDebug가 BUILD SUCCESSFUL | 충족 | Gradle 10 deprecation warning은 후속 정리 가능 |
| 전체 Python 테스트벤치 | 최신 전체 pytest에서 `150 passed, 6 warnings` | 충족 | warnings는 기존 SQLAlchemy/Pydantic deprecation |
| Android 정적 계약 테스트 | `tests/test_remote_android_client_static.py` → 8 passed | 부분 충족 | compile/runtime 대체 불가 |
| macOS 정적 계약 테스트 | `tests/test_remote_macos_client_static.py` → 5 passed | 충족 | 없음 |
| verifier/smoke script 계약 테스트 | `tests/test_remote_verifier_contract.py` → verifier/smoke script 구성 drift 방지와 branch discipline pass/fail 단위 검증 | 충족 | 새 smoke 추가 시 함께 갱신 필요 |
| 통합 verifier | `tools/verify_remote_controller.py --require-branch dev-remote --expect-main-hash 4052da3 --allow-android-device-blocker` → Android assembleDebug 포함 passed, Android device/emulator blocker만 명시 허용 | 부분 충족 | 실제 device/emulator 연결 후 `--allow-android-device-blocker` 없이 green 필요 |
| 사용자 의사결정 blocker | 사용자가 Android SDK License 수락과 추가 도구 설치를 승인했고 `sdkmanager --licenses` 및 필수 SDK package 설치를 완료 | 충족 | 없음 |

## 3. 최신 검증 evidence

최근 통합 검증 명령:

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home sdkmanager --install "platform-tools" "platforms;android-36" "build-tools;35.0.0"
./.venv/bin/python tools/check_android_sdk_readiness.py
cd remote_clients/android/HomeworkHelperRemote && JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home ANDROID_HOME=/opt/homebrew/share/android-commandlinetools ANDROID_SDK_ROOT=/opt/homebrew/share/android-commandlinetools ./gradlew :app:assembleDebug --stacktrace
./.venv/bin/python -m pytest tests/test_remote_verifier_contract.py
./.venv/bin/python tools/verify_remote_controller.py --require-branch dev-remote --expect-main-hash 4052da3 --allow-android-device-blocker
```

확인 결과:

- branch/hash 확인 → 현재 브랜치 `dev-remote`, `main`/`origin/main` `4052da3`, branch discipline gate passed
- Android SDK readiness → `sdkmanager` present, `adb` present, `platform-tools`, `platforms;android-36`, `build-tools;35.0.0`, `android-sdk-license`, `android-sdk-preview-license` present, readiness passed
- Android Gradle build → `./gradlew :app:assembleDebug --stacktrace` BUILD SUCCESSFUL, APK `remote_clients/android/HomeworkHelperRemote/app/build/outputs/apk/debug/app-debug.apk` 생성
- APK artifact contract → `aapt dump badging`에서 package `dev.homeworkhelper.remote`, version `0.1.0`, minSdk 26, targetSdk 36 확인; `aapt dump permissions`에서 `android.permission.INTERNET`, `android.permission.PACKAGE_USAGE_STATS` 확인
- Android build 설정 보정 → `gradle.properties`에 `android.useAndroidX=true`, 앱 Gradle에 Java/Kotlin 17 target/toolchain 고정
- `tests/test_remote_verifier_contract.py` → 8 passed, `--allow-android-device-blocker`와 `blocked: android-device` 계약 포함
- `tests/test_remote_routes.py` → 20 passed, 6 warnings
- `tests/test_remote_android_client_static.py` → 8 passed
- `tests/test_remote_macos_client_static.py` → 5 passed
- `tools/smoke_remote_controller_runtime.py` → passed
- `tools/smoke_macos_remote_api_client.py` → capabilities/token refresh/game-link 생성·조회/mobile session start·end/dashboard mobile metrics summary/Beholder incident decode 포함 passed
- `tools/check_remote_power_readiness.py --allow-blocker` → power config/CLI/key 누락 blocker 명시 후 readiness report passed
- `tools/smoke_android_remote_controller.py --allow-missing-apk` → APK는 존재하나 connected adb device가 없어 `Expected exactly one connected adb device; connected=[]` blocker
- 전체 pytest → 150 passed, 6 warnings
- macOS `swift build` → passed
- 통합 verifier → Android assembleDebug까지 passed, Android device/emulator blocker만 `--allow-android-device-blocker`로 명시 허용
- Android emulator 추가 설치 시도 → `emulator` package는 설치됐으나 `system-images;android-36;google_apis;arm64-v8a`는 로컬 디스크 여유 공간 부족(`No space left on device`, 약 5.5GiB available)으로 중단

## 4. 완료 불가 판정 사유

2026-05-12 현재 Android SDK License 및 APK assemble blocker는 해소되었지만, active goal을 완료로 표시하지 않는다.

이유:

1. 실제 Android device/emulator install/launch smoke가 없다. 현재 `adb devices` 결과 connected device가 없다.
2. Android emulator를 준비하려고 `emulator`와 `system-images;android-36;google_apis;arm64-v8a` 설치를 시도했으나 system image는 로컬 디스크 여유 공간 부족으로 설치되지 않았다.
3. Android Keystore, UsageStats provider, game-link 생성 UI, package Intent 실행, 수동/UsageStats 자동 mobile session start/end는 APK compile과 정적 계약으로는 검증됐지만 실제 device/emulator runtime 동작은 미검증이다.
4. 기술 검토서의 Tailscale/ZeroTier 외부망 실접속은 smoke 스크립트와 가이드까지 준비되었지만 LTE/tailnet 실제 URL/token evidence는 아직 없다.
5. SmartThings/SSH 설정 저장 UI는 추가되었지만 실제 전원 동작은 장비 side effect가 있어 별도 승인된 환경이 필요하다.

## 5. 다음 unblock 순서

현재 다음 순서로 재개한다.

```bash
# 디스크 여유 공간 확보 후 emulator system image 설치 또는 실제 Android 기기 연결
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home sdkmanager --install "system-images;android-36;google_apis;arm64-v8a"
avdmanager create avd --name HomeworkHelperRemoteApi36 --package "system-images;android-36;google_apis;arm64-v8a" --device pixel_8
emulator -avd HomeworkHelperRemoteApi36 -no-snapshot -no-audio

# 또는 USB/무선 디버깅 device 연결 후
./.venv/bin/python tools/smoke_android_remote_controller.py --report-usage-access
./.venv/bin/python tools/smoke_android_remote_controller.py --skip-install --report-usage-access --open-usage-access-settings
./.venv/bin/python tools/smoke_android_remote_controller.py --skip-install --skip-launch --require-usage-access
./.venv/bin/python tools/verify_remote_controller.py --require-branch dev-remote --expect-main-hash 4052da3
./.venv/bin/python tools/smoke_remote_controller_connectivity.py --base-url http://100.x.y.z:8000 --token "<paired-device-token>" --expect-auth
```

그 다음 실제 device/emulator에서 다음을 smoke한다.

1. APK install/launch
2. Remote Agent base URL 저장
3. pairing code 입력 및 token Keystore 저장
4. 앱 재시작 후 token 복호화/재사용
5. `/remote/status`, process/shortcut/device 조회
6. PC 명령 버튼의 capability gating 확인
7. Usage Access 허용 후 최근 전면 앱 조회
8. Android game-link package Intent 실행
9. 수동/UsageStats 자동 mobile session start/end 및 dashboard mobile metrics 반영
