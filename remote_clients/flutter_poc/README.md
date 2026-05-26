# HomeworkHelper Flutter UI POC

이 폴더는 **생산 Android 클라이언트 교체가 아닌 UI 품질 비교용 POC**입니다.

- 현재 production Android 앱은 `remote_clients/android/HomeworkHelperRemote`의 Kotlin/Jetpack Compose 구현을 유지합니다.
- 이 POC는 실제 host pair/token/SSH/Tailscale/SmartThings 상태를 건드리지 않고 fixture JSON만 렌더링합니다.
- 목표는 macOS popover에 가까운 그래픽 밀도, 카드 계층, 진행률/상태 표현을 Flutter로 얼마나 빠르게 낼 수 있는지 비교하는 것입니다.

## 실행

```bash
cd remote_clients/flutter_poc
flutter pub get
flutter run -d <device-id>
```

## 비교 기준

1. 홈 화면에서 4개 게임 카드, 서버 추적/로컬 예측 진행률, 실행/중단 CTA가 한 화면에 충분히 컴팩트하게 보이는가?
2. 설정 화면을 추가했을 때 macOS의 연결 · 전원 · 기기 · 앱 계층을 모바일에서 더 매끄럽게 표현할 수 있는가?
3. Android 네이티브 자동화(Tailscale VPN intent, SSH key store, SmartThings PAT 저장)는 Flutter plugin/platform-channel로 옮길 가치가 있는가?
