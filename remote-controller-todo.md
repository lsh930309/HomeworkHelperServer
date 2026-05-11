# Remote Controller TODO

작성/갱신: 2026-05-11
현재 통합 브랜치: `main`
작업 브랜치 이력: `dev-remote`에서 개발 후 `main`에 squash merge, 브랜치 삭제 완료
기준 설계 문서: `remote-controller-technical-review.md`

## 목표

HomeworkHelper 기능을 macOS/Android 네이티브 리모트 컨트롤러에서 수행할 수 있도록 Remote Agent API, macOS 앱, 이후 Android 앱으로 확장 가능한 구동 환경을 만든다.

## 진행 원칙

- macOS 네이티브 앱을 먼저 실제 빌드/동작 확인하며 로직을 다진다.
- Android APK는 검증된 Remote API/DTO/명령 모델을 전파하는 순서로 진행한다.
- 매 커밋 직전 자체 코드 리뷰, 동작 테스트, 기초 테스트벤치 검증을 수행한다.
- 커밋 메시지는 Korean Lore 형식을 사용한다.
- 의사결정이 필요한 지점은 작업을 멈추고 사용자 확인 후 재개한다.

## 1차 수직 슬라이스 — 진행 중

- [x] `dev-remote` 브랜치 생성
- [x] `dev-remote` 작업분을 `main`에 Korean Lore squash merge
- [x] squash merge 후 `dev-remote` 원격/로컬 브랜치 삭제
- [x] 기술 검토 문서 루트 보존: `remote-controller-technical-review.md`
- [x] TODO 문서 생성: `remote-controller-todo.md`
- [x] 작업 보고서 생성: `remote-controller-work-report.md`
- [x] `/remote/status` 최소 Remote Agent API 추가
- [x] `/remote/processes`, `/remote/processes/{id}/launch` 추가
- [x] `/remote/shortcuts`, `/remote/shortcuts/{id}/open` 추가
- [x] 안전 기본 전원 adapter 추가: 미설정 상태에서는 명령 차단
- [x] Remote API power status가 클라이언트 gating 필드를 제공하도록 테스트 고정
- [x] Remote API 단위 테스트 추가
- [x] macOS SwiftUI 네이티브 클라이언트 골격 생성
- [x] macOS 앱 전원 제어 버튼 연결
- [x] macOS 전원 capability 기반 버튼 비활성화 구현
- [x] macOS SwiftUI 클라이언트 빌드 검증
- [x] macOS 클라이언트 정적 계약 pytest 추가
- [x] Python Remote API 테스트 검증
- [x] 자체 코드 리뷰 후 1차 커밋 준비 완료
- [x] `dev-remote` 원격 푸시

## 다음 단계 후보

- [x] Remote Agent 선택적 Bearer token 인증 1차 구현
- [x] Pairing code/device registry/token revoke API 구현
- [x] macOS pairing code 입력 및 Keychain token 저장 구현
- [x] Device revoke UI 구현
- [x] command audit log JSONL 파일 추가
- [x] `pc_remote` SmartThings/SSH 전원 제어 adapter를 안전한 설정 기반으로 이식
- [x] remote_power_config.json 설정 문서화/예시 파일 추가
- [ ] remote_power_config.json 설정 UI 구현
- [x] Tailscale/ZeroTier 연결 가이드와 Agent bind 설정 추가
- [x] macOS 앱 Keychain 저장소 도입
- [x] Android Kotlin/Compose 프로젝트 생성
- [x] Android package visibility / Intent / UsageStats 권한 모델 구현
- [x] Android UsageStatsManager 최근 전면 앱 조회 기반 추가
- [x] Android 전원 capability 기반 버튼 비활성화 구현
- [x] Android Gradle wrapper 생성
- [x] Android token 저장소를 Keystore 암호화 저장으로 교체
- [x] Android 클라이언트 정적 계약 pytest 추가
- [x] Remote Controller 통합 검증 스크립트 추가: `tools/verify_remote_controller.py`
- [x] 실제 서버 프로세스 기반 Remote API pairing/token smoke 추가: `tools/smoke_remote_controller_runtime.py`
- [x] Swift `RemoteAPIClient` 기반 macOS-native HTTP/DTO/token smoke 추가: `tools/smoke_macos_remote_api_client.py`
- [ ] Android SDK License 수락 후 SDK platform/build-tools 설치

## 사용자 의사결정 필요 예정 항목

0. Google Android SDK License를 수락하고 `sdkmanager --licenses` 및 SDK package 설치를 진행할지.
1. 1차 실사용 연결 방식을 Tailscale로 고정할지, ZeroTier도 동등 지원할지.
2. SmartThings 전원 제어를 macOS 앱 직접 실행으로 둘지, PC/LAN helper 또는 릴레이 경유로 추상화할지.
3. Remote Agent 인증을 로컬 pairing code만으로 시작할지, 처음부터 device registry + token revoke UI까지 포함할지.

## Android 후속 검증 항목

- [ ] Android SDK License 수락 후 `./gradlew :app:assembleDebug` 실행
- [ ] 실제 Android 기기 또는 emulator에서 pairing/token 저장/refresh smoke test
- [ ] 실제 Android package name 실행 Intent smoke test
- [ ] Usage Access 허용 후 UsageStatsManager 기반 세션 기록/Remote Agent sync 구현
- [ ] 실제 기기에서 Android Keystore token 저장/마이그레이션 smoke test
