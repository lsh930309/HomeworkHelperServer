# HomeworkHelper 네이티브 리모트 컨트롤러 기술 검토 및 마일스톤 계획서

작성일: 2026-05-11
대상 저장소: `/Users/lsh930309/projects/HomeworkHelperServer`
참조 원격 전원 프로젝트: 요청 경로는 `~/projects/pcremote`였으나 실제 확인된 로컬 프로젝트는 `~/projects/pc_remote`

---

## 1. 결론 요약

현재 HomeworkHelper는 로컬 FastAPI 서버(`127.0.0.1`)와 PyQt 메인 GUI가 결합된 구조이며, 게임/프로세스 등록, 세션 추적, 스태미나/HoYoLab, 웹 숏컷, 대시보드, Beholder 안전장치 기능을 이미 API와 GUI 양쪽에 나누어 보유하고 있다. `pc_remote`는 macOS SwiftUI 메뉴바 앱으로, SmartThings 기반 Wake-on-LAN 우회와 SSH 기반 종료/절전/재시작/상태확인을 구현해 둔 상태다.

리모트 컨트롤러의 현실적인 목표는 다음과 같이 잡는 것이 좋다.

1. **PC에는 항상 켜져 있을 때 동작하는 HomeworkHelper Remote Agent가 필요하다.**
   원격 게임 실행, 숏컷 열기, 세션/상태 조회, Beholder 승인 같은 기능은 PC의 로컬 리소스와 DB에 접근해야 하므로 PC 측 에이전트 또는 기존 FastAPI 확장이 필수다.
2. **완전한 의미의 “서버 0개 + 외부망 원격제어”는 제한적이다.**
   같은 LAN 내부나 사용자가 VPN/메시 네트워크를 직접 켜는 조건이면 가능하지만, 일반 LTE/5G/외부망에서 NAT 뒤의 PC에 안정적으로 접근하려면 Tailscale/ZeroTier/Cloudflare 같은 제3자 제어평면, 포트포워딩, 또는 최소 릴레이 서버가 필요하다.
3. **최우선 추천은 “Tailscale 또는 ZeroTier 기반 무자체서버 MVP + `pc_remote` 전원 모듈 주입”이다.**
   별도 백엔드 운영 비용 없이 개인 용도에서 빠르게 검증 가능하고, macOS/Android 네이티브 앱이 같은 Remote Agent API를 호출할 수 있다. 이후 UX와 기기 페어링을 강화하려면 최소 릴레이 서버 방식으로 확장한다.
4. **원격 PC 켜기(WoL)는 별도 경로가 계속 필요하다.**
   PC가 꺼져 있으면 PC Agent, Tailscale, Cloudflare Tunnel, WebRTC 모두 동작하지 않는다. `pc_remote`처럼 SmartThings Hub/Station, 공유기 WoL, NAS/Raspberry Pi, 또는 항상 켜진 LAN 장치를 통해 매직패킷을 대신 쏘는 구조가 필요하다.
5. **macOS와 Android는 웹뷰가 아닌 네이티브로 구현하되, Remote API/DTO/상태 모델은 공유한다.**
   macOS는 SwiftUI, Android는 Kotlin + Jetpack Compose를 권장한다. UI는 HomeworkHelper 메인 GUI의 프로세스 테이블/상태/숏컷/게임 실행 버튼을 재구성하고, Android에는 PC-Android 게임 매칭 및 모바일 실행 세션 기록 기능을 별도 추가한다.

---

## 2. 현재 코드/프로젝트 조사 결과

### 2.1 HomeworkHelper 원격화 가능한 기존 API 표면

`homework_helper.pyw`와 `src/api/*`에서 확인한 주요 FastAPI 엔드포인트는 다음과 같다.

- 프로세스/게임 관리
  - `GET /processes`
  - `GET /processes/{process_id}`
  - `POST /processes`
  - `PUT /processes/{process_id}`
  - `PATCH /processes/{process_id}/runtime-state`
  - `DELETE /processes/{process_id}`
- 웹 숏컷 관리
  - `GET /shortcuts`
  - `GET /shortcuts/{shortcut_id}`
  - `POST /shortcuts`
  - `PUT /shortcuts/{shortcut_id}`
  - `POST /shortcuts/{shortcut_id}/opened`
  - `DELETE /shortcuts/{shortcut_id}`
- 전역 설정
  - `GET /settings`
  - `PUT /settings`
  - `PATCH /settings`
- 플레이 세션
  - `POST /sessions`
  - `PUT /sessions/{session_id}/end`
  - `GET /sessions/process/{process_id}`
  - `GET /sessions/process/{process_id}/active`
  - `GET /sessions/process/{process_id}/last`
  - `PATCH /sessions/{session_id}/stamina`
  - `GET /sessions`
- 대시보드/분석
  - `/dashboard`
  - `/api/dashboard/settings`
  - `/api/analytics/games`, `/api/analytics/range`, `/api/analytics/timeline`, `/api/analytics/summary`, `/api/analytics/patterns`, `/api/analytics/sessions`
  - `/api/dashboard/playtime`, `/api/dashboard/calendar`, `/api/dashboard/icons/{process_id}`
- Beholder 안전장치
  - `/api/beholder/incidents/active`
  - `/api/beholder/incidents/{incident_id}`
  - `/api/beholder/incidents/{incident_id}/resolve`
  - `/api/beholder/runtime/heartbeat`
  - `/api/beholder/open-sessions/reconcile`
  - `/api/beholder/backups`, `/api/beholder/backups/restore-preview`, `/api/beholder/backups/restore`

원격 앱이 바로 재사용할 수 있는 영역은 조회/수정/설정/세션/Beholder다. 다만 **게임 실행 자체는 아직 API로 노출되어 있지 않고 GUI 내부 동작에 가깝다.** `src/core/launcher.py`의 `Launcher.launch_process()`는 `.url`, `.lnk`, exe 직접 실행, Steam/Epic/Uplay/Battle.net 프로토콜, 관리자 권한 런처 재시작 보조 로직을 제공하지만, 이를 원격에서 호출하는 안전한 `/remote/processes/{id}/launch` 형태의 명령 API는 새로 설계해야 한다.

### 2.2 현재 GUI에서 네이티브 앱으로 옮길 기능 묶음

`src/gui/main_window.py`, `src/api/client.py`, `src/core/launcher.py` 기준으로 원격 네이티브 앱에 재구성해야 할 핵심 UI는 다음이다.

- 등록 게임/프로세스 목록, 현재 실행 상태, 마지막 실행/스태미나 상태
- 게임 실행 버튼 및 실행 방식 선택/선호 실행 경로 관리
- 웹 숏컷 목록, 열림 기록(`mark_web_shortcut_opened`) 반영
- 세션 시작/종료 및 열린 세션 복구 상태
- 대시보드 요약/캘린더/플레이타임 분석 조회
- HoYoLab 스태미나 재조회/보정 결과 확인
- Beholder incident 확인/승인/백업 복구
- 스크린샷/녹화 같은 PC 로컬 액션은 원격 명령으로 추가 가능하나 권한/경로/결과 파일 전달 정책이 별도 필요

### 2.3 `pc_remote` 조사 결과

실제 확인된 프로젝트는 `/Users/lsh930309/projects/pc_remote`이다.

- Swift 5.9 + SwiftUI `MenuBarExtra` macOS 앱
- 상태 확인: 공인 IP + SSH 외부 포트에 TCP 연결 시도
- PC 켜기: SmartThings CLI `devices:commands <deviceId> switch:on`
- PC 끄기/절전/재시작: `/usr/bin/ssh`로 Windows OpenSSH에 명령 전송
- README상 네트워크 구성
  - 켜기: macOS → SmartThings Cloud → SmartThings Hub/Station → 로컬 WoL → PC
  - 끄기/절전/재시작: macOS → 공유기 공인 IP:포트포워딩 → Windows PC SSH
  - 상태 확인: SSH 포트 TCP connect 성공/실패

재사용해야 할 모듈화 대상은 다음이다.

```text
PowerController
 ├─ checkPowerState(): SSH/TCP 또는 Remote Agent heartbeat
 ├─ wake(): SmartThings CLI/API, 공유기 WoL, LAN helper 중 하나
 ├─ shutdown(): SSH 또는 Remote Agent 명령
 ├─ sleep(): SSH 또는 Remote Agent 명령
 └─ restart(): SSH 또는 Remote Agent 명령
```

현재 `pc_remote`는 설정값이 Swift 코드 상수로 박혀 있으므로, 실제 통합 단계에서는 Keychain/EncryptedSharedPreferences 기반 설정 저장, 기기 페어링, 권한 분리, 실패 로그가 필요하다.

---

## 3. 외부 기술 리서치 근거

아래 근거는 2026-05-11 기준 공식 문서/공식 저장소를 우선 확인한 것이다.

- Tailscale Serve는 tailnet 내부 기기가 로컬 포트를 다른 tailnet 기기에 안전하게 노출하도록 지원한다. Funnel은 공개 인터넷 노출 용도이며 Serve와 구분된다.
  출처: https://tailscale.com/docs/features/tailscale-serve , https://tailscale.com/docs/features/tailscale-funnel
- Tailscale Personal 플랜은 개인 용도에서 무료 사용 폭이 넓다.
  출처: https://tailscale.com/pricing , https://tailscale.com/docs/reference/free-plans-discounts
- ZeroTier는 원격 접근/홈랩/개인 테스트 용도의 Basic 무료 티어를 제공한다.
  출처: https://docs.zerotier.com/pricing/ , https://docs.zerotier.com/
- Cloudflare Tunnel은 `cloudflared`가 방화벽 내부에서 Cloudflare로 outbound-only 연결을 만들고, 공개 IP/인바운드 포트 없이 HTTP/SSH/RDP/TCP 등을 노출할 수 있다.
  출처: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/ , https://developers.cloudflare.com/tunnel/
- Firebase Cloud Messaging은 Android 등 클라이언트에 알림/데이터 메시지를 보낼 수 있으나, 신뢰 환경(Cloud Functions 또는 앱 서버 등)에서 전송해야 하며 payload 제한이 있다. 민감 데이터는 별도 E2E 암호화가 필요하다.
  출처: https://firebase.google.com/docs/cloud-messaging , https://firebase.google.com/docs/cloud-messaging/customize-messages/set-message-type
- Apple APNs는 앱별 device token을 앱이 provider server로 전달하고, provider server가 APNs에 HTTP/2/TLS로 notification request를 보내는 구조다. 즉 push만으로도 최소 provider 역할은 필요하다.
  출처: https://developer.apple.com/documentation/usernotifications/registering-your-app-with-apns , https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns
- WebRTC는 P2P 데이터채널이 가능하지만 ICE candidate 교환을 위한 signaling이 별도 필요하고, 네트워크 조건에 따라 STUN/TURN이 필요하다.
  출처: https://webrtc.org/getting-started/peer-connections
- Android에서 다른 앱 실행/매칭은 Intent와 package visibility 제약을 고려해야 한다. API 30+에서는 필요한 패키지/intent를 `<queries>`에 선언해야 할 수 있다.
  출처: https://developer.android.com/guide/components/intents-filters , https://developer.android.com/training/package-visibility/declaring
- Android 게임 실행 기록/전면 앱 추적은 `UsageStatsManager`를 쓸 수 있으나 `PACKAGE_USAGE_STATS` 선언만으로는 부족하고 사용자가 설정에서 Usage Access를 허용해야 한다.
  출처: https://developer.android.com/reference/android/app/usage/UsageStatsManager
- Android 네이티브 UI는 Jetpack Compose가 현대적 권장 도구이고, macOS 네이티브 UI는 SwiftUI가 적합하다.
  출처: https://developer.android.com/develop/ui , https://developer.apple.com/swiftui/
- SmartThings CLI는 SmartThings API용 공식/커뮤니티 CLI이며 macOS Homebrew, Windows installer, Node 기반 설치를 지원한다.
  출처: https://github.com/SmartThingsCommunity/smartthings-cli , https://developer.smartthings.com/docs/devices/capabilities/

---

## 4. 서버 필요성 검토: 가능한 방안 목록

### 4.1 방안 A: LAN 전용 직접 연결, 서버 없음

- 구조: macOS/Android 앱 → 같은 Wi-Fi/LAN의 PC Remote Agent (`http://pc.local:port` 또는 mDNS)
- 장점
  - 외부 서비스/서버 비용 0
  - 구현 단순, 디버깅 쉬움
  - 초기에 Remote API 설계 검증에 적합
- 한계
  - 외부망 원격제어 불가
  - PC가 꺼지면 Agent 접근 불가
  - Android의 모바일망/외부망에서는 사용성 부족
- 결론: 개발/테스트 베이스라인으로는 필수지만 최종 요구사항 단독 충족은 어렵다.

### 4.2 방안 B: 기존 `pc_remote` 방식 확장, 자체 서버 없음 + 포트포워딩/SmartThings

- 구조
  - PC 켜기: SmartThings Hub/Station 경유 WoL
  - PC 끄기/절전/재시작: SSH 포트포워딩
  - HomeworkHelper 기능: FastAPI 또는 Remote Agent 포트도 포트포워딩하거나 SSH 터널로 접근
- 장점
  - `pc_remote` 구현을 가장 직접적으로 재사용
  - 별도 서버 운영비 0
  - macOS MVP가 빠름
- 한계
  - 공인 IP/포트포워딩/Windows OpenSSH 보안 관리 필요
  - Android에서 SSH 키/포트포워딩 설정 UX가 번거롭다
  - FastAPI를 직접 인터넷에 노출하는 것은 위험하므로 SSH tunnel 또는 TLS/auth proxy가 필요
- 결론: 개인용 빠른 실험은 가능하나, 장기 구조로는 보안/설정 난도가 높다.

### 4.3 방안 C: Tailscale/ZeroTier 메시 VPN, 자체 서버 없음에 가까움 — 최우선 추천 MVP

- 구조
  - PC, macOS, Android를 같은 tailnet/virtual network에 가입
  - PC의 HomeworkHelper Remote Agent는 로컬 또는 tailnet IP에만 listen
  - macOS/Android 네이티브 앱은 tailnet IP/DNS로 Agent API 호출
  - PC 켜기는 SmartThings WoL 또는 별도 LAN helper 유지
- 장점
  - 자체 서버/포트포워딩 없이 외부망 접근 가능
  - WireGuard/SDN 레이어가 인증과 암호화 대부분을 담당
  - Android/macOS 모두 클라이언트 존재
  - 개인 용도 무료 티어로 시작 가능
- 한계
  - “서버 없음”이 아니라 “직접 운영하는 서버 없음”이다. Tailscale/ZeroTier 제어평면에 의존한다.
  - PC가 꺼져 있으면 VPN도 꺼져 있으므로 WoL 경로는 별도 필요
  - 앱 내부에서 Tailscale/ZeroTier 연결 상태 안내 UX가 필요
- 결론: 비용/난이도/보안/속도 균형상 1차 MVP로 가장 적합하다.

### 4.4 방안 D: Cloudflare Tunnel/Zero Trust, 자체 서버 없음 + Cloudflare 의존

- 구조
  - PC 또는 LAN 장치에서 `cloudflared` 실행
  - Cloudflare Access/WARP를 통해 Remote Agent를 노출
  - 앱은 HTTPS endpoint 또는 WARP private route로 접근
- 장점
  - 인바운드 포트 없이 outbound-only 터널 구성
  - Cloudflare Access로 사용자 인증/정책 적용 가능
  - 공개 API처럼 만들거나 사설 네트워크처럼 만들 수 있음
- 한계
  - 기본적으로 PC가 켜져 있어야 tunnel도 살아 있다
  - 네이티브 앱에서 Access 토큰/브라우저 로그인/서비스 토큰 UX 설계 필요
  - 개인용 간편함은 Tailscale보다 낮을 수 있음
- 결론: 보안 정책/도메인/HTTPS UX가 중요하면 좋은 2차 선택지다.

### 4.5 방안 E: FCM/APNs Push + PC Agent polling/long-polling, 최소 서버 필요

- 구조
  - Android/macOS 앱은 명령을 최소 릴레이에 등록
  - PC Agent가 서버에 WebSocket/long polling으로 outbound 연결 또는 주기 polling
  - FCM/APNs는 모바일/맥 앱에 상태 변경 알림을 보내는 보조 채널
- 장점
  - PC 쪽 인바운드 포트 불필요
  - 모바일 푸시 UX가 좋음
  - 여러 기기/가족 계정/명령 큐/감사 로그에 적합
- 한계
  - FCM/APNs 자체는 명령 저장소가 아니므로 provider/server 역할이 필요
  - 앱 서버, 인증, 명령 재전송, idempotency, 감사 로그 구현 필요
  - PC가 꺼져 있으면 여전히 WoL 경로 필요
- 결론: 제품화/다중기기에는 좋지만 1차 MVP보다 작업량이 크다.

### 4.6 방안 F: WebRTC DataChannel P2P, signaling + TURN 최소 필요

- 구조
  - macOS/Android 앱과 PC Agent가 signaling 서버에서 SDP/ICE candidate 교환
  - 연결 후 WebRTC DataChannel로 명령/상태 송수신
  - NAT 실패 시 TURN relay 필요
- 장점
  - 연결 성립 후 P2P 지연이 낮고 양방향 스트림에 강함
  - 향후 화면/오디오/고급 원격 UI로 확장 가능
- 한계
  - signaling은 WebRTC 표준에 포함되지 않아 별도 구현 필요
  - TURN은 트래픽 비용이 발생하기 쉽다
  - 단순 REST 원격제어에는 과한 구조
- 결론: 화면 스트리밍/저지연 양방향 기능까지 갈 때 검토하고, 현재 요구에는 후순위다.

### 4.7 방안 G: 최소 VPS/홈서버 릴레이

- 구조
  - 소형 FastAPI/Go/Rust 서버: HTTPS API + WebSocket command queue
  - PC Agent: outbound WebSocket 유지
  - macOS/Android 앱: HTTPS로 명령 제출/상태 조회
- 장점
  - 플랫폼 독립적인 자체 제어평면
  - 푸시, 페어링, 감사 로그, 멀티 디바이스 UX를 일관되게 구현 가능
  - Tailscale/ZeroTier 미설치 사용자까지 확장 가능
- 한계
  - 비용 0을 고집하면 무료 티어 안정성/정책 변경 리스크가 있음
  - 서버 보안/운영/백업/모니터링 책임 발생
- 결론: 2차 또는 3차 단계의 “제품형” 구조로 적합하다.

---

## 5. 공통 아키텍처 제안

### 5.1 구성요소

```text
[macOS Native App]
  SwiftUI/AppKit, Keychain, URLSession/WebSocket

[Android Native App]
  Kotlin, Jetpack Compose, EncryptedSharedPreferences/Keystore, WorkManager, UsageStats optional

[HomeworkHelper Remote Agent on PC]
  기존 FastAPI 확장 또는 별도 sidecar
  - 인증/페어링
  - command allowlist
  - Launcher 호출
  - web shortcut open
  - session/status/dashboard proxy
  - Beholder 승인 흐름
  - power command adapter

[Power Adapter]
  SmartThings WoL / SSH / Windows command / future LAN helper

[Connectivity Layer]
  1차: LAN + Tailscale/ZeroTier
  2차: Cloudflare Tunnel 또는 Minimal Relay
```

### 5.2 새로 추가할 Remote API 초안

기존 CRUD API를 그대로 외부에 노출하지 말고, 원격 명령용 안전 레이어를 추가한다.

- 인증/페어링
  - `POST /remote/pair/start`
  - `POST /remote/pair/confirm`
  - `POST /remote/tokens/refresh`
  - `DELETE /remote/devices/{device_id}`
- 상태
  - `GET /remote/status`
  - `GET /remote/capabilities`
  - `GET /remote/processes`
  - `GET /remote/shortcuts`
  - `GET /remote/dashboard/summary`
- 명령
  - `POST /remote/processes/{process_id}/launch`
  - `POST /remote/processes/{process_id}/stop` 또는 “종료 요청”만 지원
  - `POST /remote/shortcuts/{shortcut_id}/open`
  - `POST /remote/settings/patch`
  - `POST /remote/power/wake`
  - `POST /remote/power/shutdown`
  - `POST /remote/power/sleep`
  - `POST /remote/power/restart`
- Beholder
  - `GET /remote/beholder/incidents`
  - `POST /remote/beholder/incidents/{id}/resolve`
- Android-PC 게임 매칭
  - `GET /remote/game-links`
  - `POST /remote/game-links`
  - `POST /remote/mobile-sessions/start`
  - `POST /remote/mobile-sessions/end`

### 5.3 보안 원칙

- Remote Agent는 기본적으로 `127.0.0.1` 또는 VPN 인터페이스에만 listen한다.
- 인터넷 직접 노출 시에는 반드시 TLS + device-bound token + 짧은 만료 + refresh token을 사용한다.
- 원격 명령은 allowlist로 제한한다. 임의 shell 명령 실행 API는 만들지 않는다.
- PC 종료/절전/게임 실행/설정 변경/Beholder override는 audit log를 남긴다.
- 최초 페어링은 PC 화면의 6자리 코드/QR 또는 로컬 네트워크 1회 승인으로 제한한다.
- 저장소에는 SmartThings device id, SSH key path, public IP 같은 개인 설정을 커밋하지 않는다.
- Android에는 Keystore/EncryptedSharedPreferences, macOS에는 Keychain을 사용한다.

### 5.4 Android-PC 크로스플랫폼 게임 매칭 설계

추가 테이블/모델 예시:

```text
game_platform_links
- id
- pc_process_id
- pc_display_name
- android_package_name
- android_launch_intent_uri 또는 deeplink
- android_store_url
- platform_account_hint
- hoyolab_game_id 또는 external_game_id
- sync_strategy: manual | usage_stats | explicit_start_button | cloud_account
- created_at / updated_at
```

Android 앱 동작:

1. 사용자가 PC 게임과 Android 패키지를 수동 매칭한다.
2. 실행 버튼은 Android `Intent`로 모바일 게임을 연다.
3. 사용자가 Usage Access를 허용하면 `UsageStatsManager`로 전면 앱 이벤트를 추적한다.
4. 권한이 없으면 앱 내부 “시작/종료” 버튼으로 모바일 세션을 수동 기록한다.
5. PC Agent 또는 최소 릴레이에 모바일 세션을 업로드하여 HomeworkHelper의 분석/캘린더에 포함한다.
6. Android 11+ package visibility 대응을 위해 알려진 게임 패키지와 intent query를 manifest `<queries>`에 선언한다.

---

## 6. 접근 방식 비교표

| 방안 | 자체 서버 | 외부망 원격 | PC 켜기 | 비용 | 보안/운영 난도 | 추천도 |
|---|---:|---:|---:|---:|---:|---:|
| LAN 전용 | 없음 | 불가 | LAN WoL 가능 | 0 | 낮음 | 개발용 |
| 포트포워딩 + SmartThings/SSH | 없음 | 가능 | 가능 | 0 | 높음 | 개인 실험 |
| Tailscale/ZeroTier | 자체 없음, 제3자 제어평면 | 가능 | 별도 WoL 필요 | 개인 무료 가능 | 낮음~중간 | 1차 MVP 최우선 |
| Cloudflare Tunnel/Access | 자체 없음, Cloudflare 의존 | 가능 | 별도 WoL 필요 | 무료/저비용 가능 | 중간 | 2차 후보 |
| FCM/APNs + polling | 최소 필요 | 가능 | 별도 WoL 필요 | 무료~저비용 | 중간~높음 | 제품형 2차 |
| WebRTC | signaling/TURN 필요 | 가능 | 별도 WoL 필요 | TURN 비용 가능 | 높음 | 후순위 |
| 자체 VPS 릴레이 | 필요 | 가능 | 별도 WoL 필요 | 무료 티어/저비용 | 높음 | 장기 제품형 |

---

## 7. 구체적 마일스톤 계획 1: Tailscale/ZeroTier 기반 무자체서버 MVP

목표: 자체 백엔드 서버 없이 macOS/Android 네이티브 앱에서 HomeworkHelper 기능과 PC 전원 제어를 외부망에서 실행한다.

### 단계 1. Remote Agent 최소 API 분리

- 기간: 3~5일
- 작업
  - 기존 FastAPI에 `/remote/*` router 추가 또는 sidecar FastAPI 생성
  - `/remote/status`, `/remote/processes`, `/remote/shortcuts`, `/remote/dashboard/summary` 구현
  - 기존 `Launcher`를 호출하는 `/remote/processes/{id}/launch` 구현
  - 웹 숏컷 열기 `/remote/shortcuts/{id}/open` 구현
  - PC 로컬 실행 결과를 `command_id`, `accepted`, `result`, `error`로 표준화
- 완료 조건
  - LAN에서 curl로 게임 목록 조회/실행/숏컷 열기 성공
  - Beholder가 막는 변경은 기존 incident 흐름을 유지

### 단계 2. 인증/페어링 1차 구현

- 기간: 2~4일
- 작업
  - PC 화면에 6자리 pairing code 표시
  - macOS/Android 앱이 pairing code로 device token 발급
  - token은 macOS Keychain, Android Keystore/EncryptedSharedPreferences에 저장
  - Remote Agent는 bearer token + device id 검증
- 완료 조건
  - 미페어링 기기 접근 거부
  - 토큰 폐기 후 접근 차단

### 단계 3. Tailscale/ZeroTier 연결 프로파일 지원

- 기간: 1~3일
- 작업
  - Agent bind 주소를 `127.0.0.1`, LAN IP, tailnet IP 중 선택 가능하게 설정
  - 앱 설정에 PC tailnet hostname/IP 입력 UX 추가
  - 연결 실패 시 “VPN 연결 확인” 안내
- 완료 조건
  - LTE/외부망 Android에서 tailnet IP로 `/remote/status` 성공
  - macOS 앱에서도 동일 API 호출 성공

### 단계 4. `pc_remote` PowerController 주입

- 기간: 3~5일
- 작업
  - SmartThings WoL, SSH shutdown/sleep/restart, TCP status를 독립 adapter로 분리
  - Swift 코드 상수 대신 설정 화면/Keychain 저장으로 전환
  - Agent의 `/remote/power/*` 또는 macOS 앱 로컬 power action 중 어느 쪽에서 실행할지 선택
  - Android는 직접 SmartThings API/CLI 사용이 어렵기 때문에 1차는 Agent 또는 최소 relay 전원 명령으로 위임
- 완료 조건
  - macOS 앱에서 PC 켜기/끄기/절전/재시작 성공
  - Android 앱에서 켜기 경로는 SmartThings 앱/웹훅/Agent 정책 중 결정된 방식으로 성공

### 단계 5. 네이티브 UI 1차 구현

- 기간: 1~2주
- macOS
  - SwiftUI Window + MenuBarExtra
  - 게임 목록/상태, 실행 버튼, 숏컷, 전원 버튼, Beholder incident list
- Android
  - Kotlin + Jetpack Compose
  - 게임 목록/상태, 실행 버튼, 숏컷, 전원 버튼, 연결 상태 배너
- 완료 조건
  - 웹뷰 없이 네이티브 컴포넌트로 주요 GUI 재구성
  - PC 앱과 동일한 핵심 작업 5개 이상 수행: 조회, 실행, 숏컷 열기, 세션 확인, 전원 제어

### 단계 6. 검증/하드닝

- 기간: 3~5일
- 작업
  - 원격 명령 audit log
  - 실패 재시도/timeout/idempotency
  - token rotate/revoke
  - 명령 allowlist 테스트
- 완료 조건
  - 외부망에서 30분 이상 상태 polling/명령 실행 안정성 확인
  - 잘못된 token/권한 없는 power command 차단 확인

### 이 계획의 장단점

- 장점: 가장 빠르고 비용 0에 가까우며 보안 리스크가 낮다.
- 단점: Tailscale/ZeroTier 앱 설치와 계정 의존이 있다. PC가 꺼진 상태에서는 WoL 경로가 여전히 별도다.

---

## 8. 구체적 마일스톤 계획 2: Cloudflare Tunnel/Access 기반 HTTPS 원격 API

목표: VPN 앱 사용을 최소화하고, Cloudflare Access 또는 Tunnel을 통해 Remote Agent를 HTTPS endpoint로 노출한다.

### 단계 1. Remote Agent localhost-only 구성

- 기간: 2~4일
- 작업
  - Agent는 `127.0.0.1:HH_REMOTE_PORT`에만 listen
  - Cloudflare Tunnel이 local service를 HTTPS hostname으로 proxy
  - direct LAN 접근과 tunnel 접근을 구분하는 설정 추가
- 완료 조건
  - 로컬에서는 `127.0.0.1`만 열림
  - 외부에서는 Cloudflare hostname으로 `/remote/status` 접근 가능

### 단계 2. Cloudflare Access 인증 모델 결정

- 기간: 2~5일
- 선택지
  - 사용자 로그인 기반 Access
  - service token 기반 앱 접근
  - WARP private route 기반 사설 접근
- 작업
  - 네이티브 앱에서 Access token 획득/갱신 UX 검증
  - 인증 헤더와 Remote Agent bearer token을 이중 검증
- 완료 조건
  - 인증되지 않은 요청 차단
  - macOS/Android 모두 인증 후 접근 가능

### 단계 3. 전원 제어 통합

- 기간: 3~5일
- 작업
  - PC가 켜진 상태: Agent 경유 종료/절전/재시작
  - PC가 꺼진 상태: SmartThings WoL은 macOS 앱 직접 실행 또는 별도 always-on LAN helper로 수행
  - Cloudflare Tunnel은 PC가 꺼지면 사라진다는 UX 표시
- 완료 조건
  - “PC 꺼짐 → WoL → tunnel 재연결 대기 → status on” 플로우가 앱에 표시됨

### 단계 4. 네이티브 UI와 대시보드 API 재구성

- 기간: 1~2주
- 작업
  - SwiftUI/Compose UI를 Remote API 기준으로 구현
  - Dashboard summary/range/calendar를 앱 카드/차트로 변환
  - Beholder incident resolve flow 구현
- 완료 조건
  - 웹 대시보드를 열지 않고도 네이티브 화면에서 주요 지표 확인

### 단계 5. 보안 점검

- 기간: 3~5일
- 작업
  - Cloudflare Access policy
  - command allowlist
  - secret storage
  - audit log
  - tunnel token 유출 대응 절차
- 완료 조건
  - Agent가 공인 IP로 직접 노출되지 않음
  - power/game launch 명령에 감사 로그와 권한 체크 적용

### 이 계획의 장단점

- 장점: HTTPS endpoint UX가 좋고 인바운드 포트가 필요 없다.
- 단점: Cloudflare 계정/도메인/Access 정책 설정이 필요하고, 네이티브 앱 인증 UX가 Tailscale보다 복잡할 수 있다.

---

## 9. 구체적 마일스톤 계획 3: 최소 릴레이 서버 + PC outbound Agent

목표: 사용자가 VPN/포트포워딩을 몰라도 macOS/Android 앱이 명령을 보내고 PC Agent가 outbound 연결로 받아 처리하는 구조를 만든다.

### 단계 1. 릴레이 서버 MVP

- 기간: 1주
- 작업
  - 작은 FastAPI/Go 서버 생성
  - `POST /commands`, `GET /commands/{id}`, `WS /agent/{pc_id}` 구현
  - command 상태: `queued`, `delivered`, `running`, `succeeded`, `failed`, `expired`
  - device/user/pc pairing 모델 구현
- 완료 조건
  - PC Agent가 WebSocket으로 서버에 붙고, 앱이 넣은 명령을 수신/처리/응답

### 단계 2. PC Agent command worker

- 기간: 1주
- 작업
  - HomeworkHelper 내부 API 또는 Python 모듈을 호출하는 worker 작성
  - 게임 실행/숏컷 열기/세션 조회/설정 변경/전원 명령 처리
  - idempotency key와 timeout 구현
- 완료 조건
  - 같은 command 중복 전달 시 1회만 실행
  - 실패 사유가 앱에 명확히 표시

### 단계 3. 모바일/맥 앱 릴레이 클라이언트

- 기간: 1~2주
- 작업
  - macOS SwiftUI와 Android Compose에서 relay API client 구현
  - command 진행 상태 실시간 표시
  - offline PC, sleeping PC, tunnel 없음 등의 상태별 UX
- 완료 조건
  - 외부망에서 별도 VPN 없이 게임 실행/숏컷 열기/상태 조회 가능

### 단계 4. Push notification 보조 채널

- 기간: 1주
- 작업
  - Android FCM, macOS APNs 또는 macOS 로컬 polling 중 선택
  - command 완료/실패/Beholder incident 발생 알림
  - payload에는 민감 정보 대신 command id만 넣고 앱이 서버에서 상세 조회
- 완료 조건
  - 앱 백그라운드 상태에서도 결과 알림 수신
  - push 실패 시 앱 foreground polling으로 복구

### 단계 5. 비용 0/최소 운영 검증

- 기간: 3~5일
- 작업
  - 무료 티어 후보별 sleep/egress/도메인/TLS/cron 제한 확인
  - self-host NAS/Raspberry Pi 대안도 문서화
  - 백업/로그 보존 정책 정의
- 완료 조건
  - 월 비용 0원 후보와 저비용 후보 각각 1개 이상 운영 절차 작성

### 이 계획의 장단점

- 장점: 사용성/확장성/다중기기 UX가 가장 좋다.
- 단점: 서버 코드/운영/보안 책임이 생긴다. 1차 MVP보다 범위가 크다.

---

## 10. 구체적 마일스톤 계획 4: Android-PC 크로스플랫폼 게임 매칭 특화 단계

목표: Android에서 실행한 크로스플랫폼 게임도 PC HomeworkHelper 데이터와 연동하여 분석/세션 처리한다.

### 단계 1. 게임 매칭 데이터 모델 추가

- 기간: 2~4일
- 작업
  - `game_platform_links` 테이블/스키마/API 추가
  - PC process와 Android package/deeplink/manual alias 연결
  - HoYoLab game id 같은 외부 계정 힌트 필드 추가
- 완료 조건
  - PC 앱/remote 앱에서 매칭 CRUD 가능

### 단계 2. Android 앱 실행 및 기록

- 기간: 1주
- 작업
  - Intent로 Android 게임 실행
  - package visibility `<queries>` 선언
  - Usage Access 허용 시 `UsageStatsManager` 기반 foreground event 추적
  - 권한 미허용 시 수동 시작/종료 버튼 제공
- 완료 조건
  - Android 게임 실행 시 mobile session 생성
  - 종료 감지 또는 수동 종료로 session close

### 단계 3. HomeworkHelper 분석 통합

- 기간: 1주
- 작업
  - `ProcessSession`에 source/platform 필드 추가 또는 mobile session 별도 테이블 후 analytics 병합
  - 대시보드에 PC/Mobile/Total 분리 표시
  - 동일 게임의 PC/Android 플레이타임 합산 옵션
- 완료 조건
  - 캘린더/요약/게임별 분석에서 Android 세션이 표시됨

### 단계 4. 계정/클라우드 데이터 보조 통합

- 기간: 1~2주
- 작업
  - HoYoLab 등 계정 기반 스태미나/플레이 상태와 Android 세션을 연결
  - 자동 매칭 실패 시 수동 보정 UI 제공
- 완료 조건
  - 최소 2개 크로스플랫폼 게임에 대해 PC/Android 매칭 검증

### 이 계획의 장단점

- 장점: 요구사항 5번의 차별화 기능을 직접 만족한다.
- 단점: Android 권한/패키지명/게임별 deeplink 편차가 커서 수동 매칭 UX가 중요하다.

---

## 11. 구체적 마일스톤 계획 5: 포트포워딩/SSH 기반 초단기 프로토타입

목표: 기존 `pc_remote`를 가장 적게 바꿔 macOS에서 HomeworkHelper 일부 기능을 원격 수행하는 데모를 만든다.

### 단계 1. SSH command wrapper 작성

- 기간: 1~2일
- 작업
  - SSH로 Windows에서 `curl http://127.0.0.1:8000/...` 또는 Python helper 실행
  - 게임 실행은 PC 내부 helper script가 `Launcher` 호출
- 완료 조건
  - macOS에서 SSH로 프로세스 목록 조회/게임 실행 데모 성공

### 단계 2. SwiftUI 메뉴 확장

- 기간: 2~3일
- 작업
  - 기존 PCRemote 메뉴에 “HomeworkHelper” 섹션 추가
  - 상위 N개 게임 실행, 숏컷 열기, dashboard open 버튼 추가
- 완료 조건
  - 기존 전원 메뉴와 게임 실행 메뉴가 한 앱에서 동작

### 단계 3. 위험 제거 계획 작성

- 기간: 1일
- 작업
  - SSH 키 권한, 포트포워딩, command allowlist 문서화
  - FastAPI 직접 공인망 노출 금지 명시
- 완료 조건
  - 실사용 전 반드시 Tailscale/Cloudflare/Relay 중 하나로 이전할 기준 수립

### 이 계획의 장단점

- 장점: 가장 빠른 데모.
- 단점: Android 확장성과 보안성이 낮아 장기 계획으로는 부적합하다.

---

## 12. 권장 실행 순서

1. **1주차: Remote Agent API를 먼저 만든다.**
   연결 방식과 무관하게 모든 계획이 필요로 하는 공통 기반이다. 기존 FastAPI를 그대로 외부에 열지 말고 `/remote/*` 안전 레이어를 추가한다.
2. **2주차: Tailscale/ZeroTier MVP로 macOS + Android 네이티브 클라이언트를 붙인다.**
   서버 비용 없이 외부망 성공 여부를 검증한다.
3. **3주차: `pc_remote` PowerController를 모듈화하고 WoL/전원 UX를 통합한다.**
4. **4주차: Android-PC 게임 매칭 MVP를 추가한다.**
5. **5주차 이후: 사용성 요구가 커지면 Cloudflare Tunnel 또는 최소 릴레이 서버로 확장한다.**

최종 추천 조합:

```text
1차 실사용: Tailscale/ZeroTier + Remote Agent + SmartThings WoL
2차 개선: Cloudflare Tunnel 또는 Minimal Relay + Push 알림
장기 제품형: Minimal Relay + PC outbound Agent + Android-PC game matching + audit/security hardening
```

---

## 13. 구현 시 바로 생성할 작업 목록

### HomeworkHelperServer 저장소

- [ ] `src/api/remote_routes.py` 추가
- [ ] `src/core/remote_auth.py` 추가: pairing/token/device registry
- [ ] `src/core/remote_commands.py` 추가: allowlisted command dispatcher
- [ ] `Launcher` 호출을 API-safe wrapper로 감싸기
- [ ] 웹 숏컷 open helper 추가
- [ ] power adapter interface 추가
- [ ] `remote_devices`, `remote_command_audit`, `game_platform_links`, `mobile_sessions` 테이블 검토
- [ ] Remote API test suite 작성

### macOS 앱

- [ ] 기존 `pc_remote`를 새 앱 또는 패키지 모듈로 재구성
- [ ] SwiftUI full window + MenuBarExtra 병행
- [ ] Keychain 설정 저장
- [ ] Remote API client, PowerController, command progress UI

### Android 앱

- [ ] Kotlin + Jetpack Compose 프로젝트 생성
- [ ] Remote API client + token storage
- [ ] package visibility/query 선언 전략
- [ ] Intent launch + UsageStats optional tracking
- [ ] mobile session sync UI

### 운영/보안

- [ ] Tailscale/ZeroTier setup guide
- [ ] Cloudflare Tunnel 대체 guide
- [ ] 포트포워딩 직접 노출 금지 가이드
- [ ] pairing reset/revoke 문서
- [ ] audit log 보존 정책

---

## 14. 핵심 리스크와 대응

1. **PC가 꺼져 있을 때 어떤 네트워크 Agent도 동작하지 않음**
   - 대응: SmartThings Hub/Station, 공유기 WoL, NAS/Raspberry Pi LAN helper 중 하나를 필수 전원 경로로 지정
2. **FastAPI를 인터넷에 직접 노출할 경우 DB/실행 명령 공격면 증가**
   - 대응: VPN/Tunnel/Relay 뒤에 숨기고 `/remote/*` allowlist만 공개
3. **Android 백그라운드 제한과 Usage Access 권한 UX**
   - 대응: UsageStats는 선택 기능으로 두고 수동 세션 기록 fallback 제공
4. **게임 런처/관리자 권한/프로토콜 실행 실패**
   - 대응: 기존 `Launcher`의 실행 방식 선택 로직을 Remote API 결과와 audit log로 노출
5. **무료 티어 정책 변경**
   - 대응: 연결 레이어를 추상화하여 Tailscale/ZeroTier/Cloudflare/Relay를 교체 가능하게 유지
6. **SmartThings CLI를 Android에서 직접 쓰기 어려움**
   - 대응: macOS 직접 실행, PC Agent, always-on LAN helper, SmartThings REST/API 연동 중 환경별 adapter 제공

---

## 15. 완료 기준 제안

1차 MVP 완료 기준:

- macOS 네이티브 앱과 Android 네이티브 앱이 모두 웹뷰 없이 실행된다.
- 두 앱 모두 Remote Agent에 페어링하고 `/remote/status`를 조회한다.
- 두 앱 모두 게임 목록/실행 상태/웹 숏컷 목록을 표시한다.
- 두 앱 중 최소 macOS는 `pc_remote` 기반 PC 켜기/끄기/절전/재시작을 수행한다.
- Android는 PC 원격 게임 실행과 Android 로컬 게임 실행/수동 세션 기록을 수행한다.
- Remote Agent는 임의 shell 실행 없이 allowlist 명령만 처리한다.
- 모든 원격 명령은 audit log에 남는다.
- 외부망에서 Tailscale/ZeroTier 또는 Cloudflare/Relay 중 하나의 경로로 30분 이상 안정성 검증을 완료한다.
