# Moonlight/Apollo 원격 플레이 연동 Spike

Last refreshed: 2026-05-24
Status: Phase 3A-2 Moonlight 감지/readiness + Tailscale direct 등록 보조 shipped; stream start is not shipped yet

## 1. 결정 요약

Task 3의 1차 목표는 코드 구현이 아니라 **Moonlight/Apollo 연동 방향을 고정하는 설계 spike**다.

고정된 방향:

- HomeworkHelper Remote의 기본 호스트/클라이언트 기능과 분리된 **선택형 extension**으로 둔다.
- 스트리밍 대상은 per-game mapping이 아니라 항상 **`Desktop`** 이다.
- 게임 실행은 HomeworkHelper 호스트 앱이 기존 `/remote/processes/{id}/launch`로 담당한다.
- Moonlight 스트림 진입은 macOS 클라이언트가 담당한다.
- 사용자는 기존 popover의 **▶ 실행 버튼 하나**를 누른다.
- 연동이 활성화되고 readiness가 통과한 경우에만 `게임 실행 + Desktop 스트림 시작`을 통합 실행한다.

비목표:

- Apollo/Sunshine에 게임별 앱을 자동 등록하지 않는다.
- Moonlight pairing을 앱이 완전 자동화하지 않는다.
- 방화벽, 드라이버, 가상 디스플레이, Apollo/Sunshine 설치를 강제로 자동 설정하지 않는다.
- 공인 IP/포트포워딩/UPnP 자동화는 우선 보류하고, v1에서는 Tailscale direct 경로만 사용한다.
- Android 클라이언트 연동은 이번 task 범위가 아니다.

## 2. 현재 HomeworkHelper 기준점

현재 macOS Remote 클라이언트는 이미 다음 흐름을 안정적으로 갖고 있다.

1. `/remote/status`로 호스트 상태를 먼저 확인한다.
2. `state_revision`이 바뀌거나 online recovery가 발생하면 payload를 동기화한다.
3. 게임 행의 ▶ 버튼은 `POST /remote/processes/{id}/launch`를 호출한다.
4. launch accepted 후에는 row-scoped pending 상태와 짧은 launch chase window로 실행 상태를 빠르게 미러링한다.
5. 연결 pill은 불필요하게 `동기화 중` 등으로 흔들리지 않는다.

따라서 Moonlight/Apollo 연동은 새 메인 UX를 만드는 것이 아니라, 이 launch flow 뒤에 붙는 **optional post-launch action**으로 설계한다.

## 3. 외부 도구 표면

### Moonlight PC / Qt

Moonlight PC는 Windows, macOS, Linux용 GameStream 클라이언트이며, Moonlight 문서 기준 Sunshine 호스트는 기본적으로 `Desktop` 앱을 제공한다.

설계상 사용할 표면:

- macOS 클라이언트에서 Moonlight 앱/CLI 존재 여부 탐지.
- 사용자가 이미 pair한 호스트를 대상으로 `Desktop` 스트림 시작.
- 이미 저장된 Moonlight host가 HomeworkHelper host와 일치하면 설정을 수정하지 않고 그대로 사용.
- 일치하는 host가 없으면 `tailscale ping`으로 direct 경로를 확인한 뒤 Moonlight CLI `pair/list`를 명시적 사용자 승인 흐름으로 실행.
- 스트림 종료는 우선 Moonlight 자체 UX에 맡긴다.

초기 구현에서는 Moonlight CLI 세부 옵션 자동 최적화보다, 사용자가 설정한 앱/CLI 경로와 Desktop 앱 이름으로 **실행 가능성 확인 → 실행**만 수행한다.

### Sunshine API

Sunshine은 Moonlight용 self-hosted game stream host이며 REST API를 제공한다. 공식 API 문서에는 앱 목록/등록, 현재 앱 종료, PIN pairing, config, restart 등 endpoint가 있다.

초기 구현에서 Sunshine API를 직접 제어하지 않는 이유:

- 인증/CSRF/버전 차이를 클라이언트 UX에 바로 끌고 오면 scope가 급격히 커진다.
- HomeworkHelper의 게임 실행은 이미 호스트 앱이 담당하고 있다.
- Desktop-only 전략에서는 Sunshine 앱 등록 자동화가 필수 조건이 아니다.

다만 미래의 읽기 전용 readiness에는 다음 정보를 활용할 수 있다.

- `/api/apps`로 `Desktop` 노출 여부 확인.
- `/api/clients/list`로 pairing 상태 보조 진단.
- `/api/apps/close`는 나중에 “스트림/앱 종료 보조” 기능 후보로만 둔다.

### Apollo

Apollo는 Sunshine fork이며 Windows에서 가상 디스플레이 흐름을 더 쉽게 다루는 방향의 프로젝트다. Apollo README는 Windows-only virtual display support, client별 고정 virtual display identity, permission system을 명시한다.

HomeworkHelper 기준 권장 순위:

1. **Apollo primary**
   - Desktop-only 스트림과 virtual display UX가 목표에 잘 맞는다.
2. **Sunshine fallback**
   - 더 표준적인 호스트지만 virtual display 자동화는 환경별 편차가 크다.

Apollo/Sunshine 선택은 HomeworkHelper가 강제하지 않고, 설정/진단 화면에서 “현재 환경이 extension에 적합한지” 보여주는 방식이 안전하다.

## 4. 권장 아키텍처

### macOS client-local orchestration

Moonlight 실행은 macOS 클라이언트의 로컬 side effect다.

권장 컴포넌트:

- `RemotePlaySettings`
  - extension 활성화 여부
  - Moonlight 앱/CLI 경로
  - stream host 주소 또는 host alias
  - app name 기본값: `Desktop`
  - 선호 실행 옵션: fullscreen 여부, 해상도/프레임레이트는 후순위
- `LocalMoonlightManager`
  - Moonlight 실행 파일 탐지
  - 설정된 host/app으로 dry-run 성격의 readiness 확인
  - Desktop stream 시작
  - 사용자에게 보여줄 실패 원인 정규화
- `RemotePlayReadiness`
  - `disabled`, `missingMoonlight`, `notPaired`, `desktopMissing`, `ready`, `unknown`

### Host 역할

초기 구현에서 host는 다음만 담당한다.

- 기존 게임 실행 API 유지.
- 기존 process/session 상태 미러링 유지.
- 필요 시 추후 읽기 전용 readiness hint 제공.

Host가 직접 Moonlight를 실행하거나 Apollo/Sunshine을 강제 제어하지 않는다.

### Launch flow

extension이 꺼져 있거나 readiness가 불완전한 경우:

1. 기존처럼 host game launch만 수행.
2. 사용자에게 Moonlight 관련 오류를 띄우지 않는다.

extension이 켜져 있고 readiness가 `ready`인 경우:

1. 사용자가 기존 ▶ 실행 버튼 클릭.
2. macOS 클라이언트가 `/remote/processes/{id}/launch` 호출.
3. host가 accepted를 반환하면 기존 launch chase 시작.
4. macOS 클라이언트가 Moonlight `Desktop` 스트림 시작.
5. 둘 중 하나만 실패할 수 있으므로 메시지는 분리한다.
   - 게임 실행 실패: 기존 launch failure로 처리.
   - 스트림 시작 실패: 게임은 실행됐을 수 있으므로 “게임 실행 명령은 전달됨, 스트림 시작 실패”로 표시.

## 5. 설정 UX

popover에는 새 버튼을 추가하지 않는다. 설정 화면에만 extension section을 둔다.

추천 설정 항목:

- `Moonlight 설치`
  - Homebrew가 있는 경우 `brew install --cask moonlight`를 명시 버튼으로 제공.
  - Homebrew가 없으면 수동 설치 안내만 표시.
- `Moonlight Desktop 연동 사용`
- `Moonlight 앱/CLI 경로`
  - 기본 탐지 후보: `/Applications/Moonlight.app`
  - CLI가 필요한 경우 사용자가 직접 경로 지정
- `스트리밍 호스트`
  - 기본 후보: 현재 Remote Agent base URL의 host 또는 Tailscale host
- `앱 이름`
  - 기본값: `Desktop`
- `진단 실행`
  - Moonlight 설치 확인
  - host 값 확인
  - Tailscale direct 여부 확인
  - Desktop 앱 존재 여부는 가능하면 수동/문서 안내 또는 미래 API로 확인

설정 section은 실패해도 baseline remote UX를 막지 않아야 한다.

## 6. 환경 게이트

구현 전 반드시 확인할 readiness:

- macOS에 Moonlight가 설치되어 있는가?
- 사용자가 설정한 Moonlight 실행 경로가 실제 실행 가능한가?
- Moonlight에서 Windows host가 이미 pair되어 있는가?
- Apollo/Sunshine에 `Desktop` 앱이 노출되어 있는가?
- Tailscale/LAN 주소가 Moonlight 스트리밍에도 유효한가?
- Apollo를 사용하는 경우 virtual display가 정상 생성/삭제되는가?
- Apollo permission system에서 해당 Moonlight client에 launch/input 권한이 있는가?

무인 자동 pairing은 초기 구현 범위 밖이다. Pairing이 필요하면 macOS 클라이언트가 PIN을 표시하고, 사용자가 호스트 Sunshine/Apollo 화면에서 명시 승인하도록 안내한다.

## 7. 실패 모드와 메시지 원칙

| 상황 | 처리 |
| --- | --- |
| Moonlight 없음 | extension readiness만 warning, 기존 게임 실행은 유지 |
| host launch 실패 | 기존 launch failure 메시지 |
| host launch accepted, stream 실패 | “게임 실행 명령은 전달됨. Moonlight Desktop 스트림 시작에 실패했습니다.” |
| pair 안 됨 | “Moonlight에서 이 호스트를 먼저 pair하세요.” 또는 “호스트 Sunshine/Apollo PIN 화면에서 승인하세요.” |
| Tailscale DERP/relay | Moonlight 등록/스트리밍 부적합 경고, 포트포워딩 자동화는 보류 |
| Desktop 앱 없음 | “Apollo/Sunshine에서 Desktop 앱 노출을 확인하세요.” |
| Apollo permission 부족 | “Apollo client 권한에서 Launch Apps/Input 권한을 확인하세요.” |
| 스트림 종료 실패 | 초기 구현에서는 앱이 강제 종료하지 않고 Moonlight UX에 위임 |

핵심 원칙:

- 스트림 실패가 게임 실행 실패처럼 보이면 안 된다.
- 게임 실행 accepted 후 stream 실패가 발생해도 row pending/chase 흐름은 유지한다.
- extension 문제는 기본 HomeworkHelper Remote 신뢰도를 떨어뜨리지 않게 분리한다.

## 8. 단계별 구현 후보

### Phase 3A: 문서/진단-only

- 이 문서가 기준점이다.
- macOS 설정 화면에 readiness section만 추가하는 것이 첫 구현 후보.
- 실제 stream start는 아직 하지 않아도 된다.
- 2026-05-24 기준 `LocalMoonlightManager`가 macOS Moonlight 앱과
  `com.moonlight-stream.Moonlight.plist`의 host/app 후보를 read-only로 감지한다.
- 2026-05-24 기준 macOS 설정의 Android 탭은 Moonlight 전용 탭으로 교체했고,
  Tailscale direct endpoint/SSH 공인 IP를 Moonlight host 자동 식별 보조 신호로 사용한다.
- 2026-05-24 기준 기존 Moonlight host가 HomeworkHelper host와 매칭되면 read-only로 유지하고,
  매칭되지 않을 때만 Tailscale direct 등록 후보/PIN pairing/`list` 확인 보조를 제공한다.
- 2026-05-24 기준 Moonlight 미설치 시 Homebrew cask 설치 버튼을 제공한다.

### Phase 3B: 수동 테스트 버튼

- 설정 화면에서 `Desktop 스트림 테스트` 버튼 제공.
- 기존 게임 launch 버튼은 아직 건드리지 않는다.
- Moonlight 실행 경로/host/app name 문제를 먼저 실제 장치에서 검증한다.

### Phase 3C: 기존 ▶ 실행 버튼 통합

- extension enabled + readiness ready일 때만 기존 launch flow 뒤에 stream start를 붙인다.
- launch accepted 전에는 Moonlight를 시작하지 않는다.
- 실패 메시지를 host launch와 stream launch로 분리한다.

### Phase 3D: 종료/복귀 보조

- Moonlight session quit, Sunshine/Apollo close-app API, stream 상태 감지는 후순위.
- 종료 자동화는 게임/host 상태를 잘못 닫을 위험이 있으므로 별도 계획으로 분리한다.

## 9. 구현 전 체크리스트

- [ ] 실제 host PC에서 Apollo 또는 Sunshine이 설치되어 있고 `Desktop` stream이 수동으로 동작한다.
- [ ] macOS에서 Moonlight로 동일 host의 `Desktop` stream이 수동으로 동작한다.
- [ ] Tailscale 주소 또는 LAN 주소 중 어떤 주소를 Moonlight host로 쓸지 사용자가 결정했다.
- [ ] Moonlight 실행 경로를 자동 탐지할 수 있는지 확인했다.
- [ ] stream start 실패가 baseline launch UX를 깨지 않는 UI 메시지 정책을 확정했다.
- [ ] 구현 후 macOS smoke에 source list 변경이 필요한지 확인한다.

## 10. 검증 계획

문서 spike 검증:

```bash
git diff --check
```

미래 macOS 구현 검증:

```bash
./.venv/bin/python -m pytest tests/test_remote_macos_client_static.py -q
swift build --package-path remote_clients/macos/HomeworkHelperRemote
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py
```

실기기 검증:

1. 호스트 PC online.
2. Apollo/Sunshine running.
3. macOS Moonlight에서 Desktop stream 수동 성공.
4. HomeworkHelper Remote에서 게임 실행 버튼 클릭.
5. host 게임 실행 상태와 Moonlight stream 진입을 각각 확인.

## 11. 참고 출처

- Moonlight PC / Qt: https://github.com/moonlight-stream/moonlight-qt
- Moonlight setup guide: https://github.com/moonlight-stream/moonlight-docs/wiki/Setup-Guide
- Sunshine API: https://docs.lizardbyte.dev/projects/sunshine/latest/md_docs_2api.html
- Apollo: https://github.com/ClassicOldSong/Apollo
