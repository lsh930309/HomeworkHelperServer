# Remote Controller 완료 감사

작성/갱신: 2026-05-11
현재 통합 브랜치: `main`
최신 확인 commit: `c57f961 외부망 Remote Agent 접속 검증도 side-effect 없는 smoke로 고정한다`
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
| `dev-remote` 브랜치 생성/작업 | 작업 이력 commit들이 `dev-remote`에서 생성되었고 이후 사용자 요청대로 `main`에 squash merge | 충족 | 브랜치는 merge 후 삭제됨 |
| Korean Lore commit + push | `b69457d`, `9e6142e`, `486cc75`, `f38cf0d`, `f4ff55d`, `35585dc`, `ea8dcc6`, `a1e3162`, `845b712`, `c57f961` 등 main commit이 Lore trailer 포함 | 충족 | 없음 |
| TODO 문서 | `remote-controller-todo.md` | 충족 | Android 후속 항목 남음 |
| 매 커밋 작업 보고서 | `remote-controller-work-report.md` | 충족 | Android 실기기 검증 후 추가 기록 필요 |
| Remote Agent API | `src/api/remote_routes.py`, `homework_helper.pyw` router include | 충족 | Beholder/대시보드 전체 원격화는 후속 범위 |
| Pairing/device token | `src/core/remote_pairing.py`, `/remote/pair/start`, `/remote/pair/confirm`, `/remote/devices` | 충족 | 실제 외부망 pairing UX는 후속 실기기 검증 필요 |
| 감사 로그 | `src/core/remote_audit.py` 및 command route 기록 | 충족 | 장기 rotation/retention 정책 후속 |
| 전원 adapter | `src/core/remote_power.py`, `remote_power_config.example.json`, power status/action API | 부분 충족 | 실제 SmartThings/SSH 전원 동작은 로컬 설정/장비 필요 |
| 전원 adapter readiness preflight | `tools/check_remote_power_readiness.py`가 config/CLI/key path/support action을 명령 실행 없이 보고 | 부분 충족 | 현재 `remote_power_config.json`, SmartThings CLI, SSH key 설정 누락 blocker |
| macOS SwiftUI 앱 | `remote_clients/macos/HomeworkHelperRemote` | 충족 | 실제 SwiftUI 버튼 클릭 자동화는 미검증 |
| macOS build | `swift build` 통합 verifier에서 passed | 충족 | 없음 |
| macOS API client 실통신 | `tools/smoke_macos_remote_api_client.py` → Swift `RemoteAPIClient`가 real loopback server와 pairing/status/devices 통신 | 충족 | SwiftUI 창 조작 smoke는 후속 |
| 실제 서버 프로세스 smoke | `tools/smoke_remote_controller_runtime.py` → `homework_helper.pyw` subprocess + HTTP pairing/token 검증 | 충족 | 외부망/tailnet 실접속은 후속 |
| LAN/Tailscale/ZeroTier connectivity smoke | `tools/smoke_remote_controller_connectivity.py` → 실행 중인 Remote Agent URL과 optional token으로 `/remote/status` 계약 및 인증 경계 확인 | 부분 충족 | 실제 tailnet/LAN URL과 paired token이 필요해 아직 실행 evidence 없음 |
| Android Kotlin/Compose 전파 | `remote_clients/android/HomeworkHelperRemote` | 부분 충족 | APK assemble/install 전까지 compile/runtime 보장은 불완전 |
| Android token 보안 | `AndroidTokenStore.kt` Keystore AES/GCM, legacy token migration | 정적 충족 | 실제 Android Keystore provider smoke 미완료 |
| Android UsageStats/Intent | `AndroidIntegration.kt`, manifest `PACKAGE_USAGE_STATS`, UI 경로 | 정적 충족 | Usage Access 허용 후 실기기 provider 동작 미완료 |
| Android Gradle wrapper | `remote_clients/android/HomeworkHelperRemote/gradlew`, wrapper jar/properties | 충족 | 없음 |
| Android SDK readiness preflight | `tools/check_android_sdk_readiness.py`가 `sdkmanager`, `adb`, required SDK package, license files를 변경 없이 보고 | 부분 충족 | 현재 `platform-tools`, `platforms;android-36`, `build-tools;35.0.0`, license files 누락 blocker |
| Android APK install/launch smoke preflight | `tools/smoke_android_remote_controller.py`가 manifest/applicationId 계약을 확인하고 APK가 있으면 `adb install -r` 및 `am start`를 수행 | 부분 충족 | 현재는 APK 누락 blocker를 `--allow-missing-apk`로 명시 확인, 실제 device/emulator 실행은 APK 산출 후 필요 |
| Android APK assemble | `tools/verify_remote_controller.py`가 `:app:assembleDebug`를 실행하나 SDK License blocker 확인 | 미충족 | Google Android SDK License 수락 및 SDK package 설치 필요 |
| 전체 Python 테스트벤치 | verifier에서 `137 passed, 4 warnings` | 충족 | warnings는 기존 SQLAlchemy/Pydantic deprecation |
| Android 정적 계약 테스트 | `tests/test_remote_android_client_static.py` → 8 passed | 부분 충족 | compile/runtime 대체 불가 |
| macOS 정적 계약 테스트 | `tests/test_remote_macos_client_static.py` → 5 passed | 충족 | 없음 |
| verifier/smoke script 계약 테스트 | `tests/test_remote_verifier_contract.py` → verifier와 smoke script 구성 drift 방지 | 충족 | 새 smoke 추가 시 함께 갱신 필요 |
| 통합 verifier | `tools/verify_remote_controller.py` | 충족 | License 수락 후 `--allow-android-license-blocker` 없이 green 필요 |
| 사용자 의사결정 blocker | Android SDK License 수락 여부 질문으로 중단 | 충족 | 사용자 승인 필요 |

## 3. 최신 검증 evidence

최근 통합 검증 명령:

```bash
./.venv/bin/python tools/verify_remote_controller.py --allow-android-license-blocker
```

확인 결과:

- `tests/test_remote_routes.py` → 10 passed
- `tests/test_remote_android_client_static.py` → 8 passed
- `tests/test_remote_macos_client_static.py` → 5 passed
- `tools/smoke_remote_controller_runtime.py` → passed
- `tools/smoke_macos_remote_api_client.py` → passed
- `tools/check_remote_power_readiness.py --allow-blocker` → power config/CLI/key 누락 blocker 명시 후 readiness report passed
- `tools/smoke_remote_controller_connectivity.py --help` 및 verifier contract test → connectivity smoke 진입점 확인
- `tools/check_android_sdk_readiness.py --allow-blocker` → SDK package/license 누락 blocker 명시 후 readiness report passed
- `tools/smoke_android_remote_controller.py --allow-missing-apk` → APK 누락 blocker 명시 후 readiness passed
- 전체 pytest → 137 passed, 4 warnings
- macOS `swift build` → passed
- Android `./gradlew :app:assembleDebug --stacktrace` → `build-tools;35.0.0`, `platforms;android-36` license 미수락 blocker

## 4. 완료 불가 판정 사유

현재 상태만으로는 active goal을 완료로 표시하지 않는다.

이유:

1. Android APK assemble이 Google Android SDK License 수락 전이라 완료되지 않았다.
2. 실제 Android device/emulator install smoke가 없다.
3. Android Keystore, UsageStats provider, package Intent 실행은 정적 계약과 APK smoke preflight로만 검증되었고 실제 device/emulator 동작은 미검증이다.
4. 기술 검토서의 Tailscale/ZeroTier 외부망 실접속은 smoke 스크립트와 가이드까지 준비되었지만 LTE/tailnet 실제 URL/token evidence는 아직 없다.

## 5. 다음 unblock 순서

사용자 승인 후 다음 순서로 진행한다.

```bash
sdkmanager --licenses
sdkmanager --install "platform-tools" "platforms;android-36" "build-tools;35.0.0"
./.venv/bin/python tools/verify_remote_controller.py
cd remote_clients/android/HomeworkHelperRemote && ./gradlew :app:assembleDebug
cd ../../.. && ./.venv/bin/python tools/smoke_android_remote_controller.py
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
8. Android package Intent 실행
