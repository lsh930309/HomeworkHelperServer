# macOS Remote Client 실사용 테스트 튜토리얼

이 문서는 **Windows 데스크탑에서 HomeworkHelper 본체/Remote Agent를 실행**하고, **MacBook의 macOS Remote Client 앱으로 접속/페어링/조작**하는 절차를 정리한다.

현재 버전은 Tailscale과 전원 제어 준비 상태를 앱 안에서 더 많이 자동화한다. 그래도 최초 실행 시에는 Windows 서버 프로세스 실행, Windows 방화벽, Tailscale 로그인/승인 같은 OS 레벨 작업이 필요할 수 있다.

## 현재 테스트 환경

- MacBook, Remote Client 역할: `100.114.138.46`
- Windows 데스크탑, Remote Agent/서버 역할: `100.109.140.97`
- Remote API port: `8000`
- 자동 탐색 실패 시 MacBook 앱에 수동 입력할 Base URL:

```text
http://100.109.140.97:8000
```

주의: MacBook에서 `127.0.0.1`은 MacBook 자신을 뜻한다. Windows 데스크탑에 붙을 때는 Windows 데스크탑의 Tailscale IP 또는 LAN IP를 입력한다.

---

## 1. Windows 데스크탑에서 할 일

Windows 데스크탑은 원래 HomeworkHelper 패키지를 실행하던 환경이며, Remote Agent/서버 역할을 한다.

### 1.1 HomeworkHelper 서버 실행

Windows PowerShell에서 HomeworkHelper 프로젝트 폴더로 이동한 뒤 실행한다.

```powershell
$env:HH_API_HOST="0.0.0.0"
$env:HH_API_PORT="8000"
$env:HH_REMOTE_REQUIRE_AUTH="1"
.\.venv\Scripts\python.exe homework_helper.pyw --server
```

의미:

- `HH_API_HOST=0.0.0.0`: MacBook/Tailscale에서 Windows 데스크탑 서버에 접속 가능하게 함
- `HH_API_PORT=8000`: Remote API 포트
- `HH_REMOTE_REQUIRE_AUTH=1`: 페어링/token 인증 강제

서버 PowerShell 창은 테스트 중 계속 켜둔다.

### 1.2 Tailscale 준비 상태 확인

최신 서버/클라이언트는 Tailscale을 다음 순서로 준비하려고 시도한다.

1. `tailscale` CLI 사용 가능 여부 확인
2. 사용할 수 없으면 자동 설치 시도
   - macOS: Homebrew cask 우선, 실패 시 Tailscale 공식 package server의 `.pkg`
   - Windows: `winget` 우선, 실패 시 Tailscale 공식 package server의 `.msi`
3. 설치 후 Tailscale 앱/CLI 재실행
4. `tailscale status --json`으로 다시 확인
5. Windows Desktop 후보 IP를 찾아 `http://<tailscale-ip>:8000` Base URL로 제안

단, 자동 설치가 성공해도 Tailscale 로그인, 브라우저 인증, macOS System Extension 승인, Windows 관리자 권한 프롬프트는 사용자가 승인해야 할 수 있다.

Windows에서 수동 확인:

```powershell
tailscale status
tailscale ip -4
```

현재 테스트에서 기대하는 Windows Tailscale IP:

```text
100.109.140.97
```

### 1.3 Windows 방화벽 확인

Windows Defender Firewall에서 TCP `8000` inbound 접근이 허용되어야 한다.

Tailscale로 테스트할 때는 가능하면 Tailscale 네트워크에서만 접근되도록 제한하는 것이 좋다.

### 1.4 전원 제어 설정 import

전원 제어는 원격 데스크탑이 켜져 있어야 하는 앱 특성상 핵심 기능이다. 기존 `pc_remote` 프로젝트의 설정을 현재 HomeworkHelper 설정 파일로 가져올 수 있다.

Mac/개발 환경에서 import 결과를 먼저 확인:

```bash
cd /Users/lsh930309/projects/HomeworkHelperServer
./.venv/bin/python tools/import_pcremote_power_config.py --print-only
```

실제 설정 파일에 저장:

```bash
./.venv/bin/python tools/import_pcremote_power_config.py
```

이 도구는 기본적으로 다음 파일에서 설정을 읽는다.

```text
../pc_remote/Sources/PCRemote/PCRemoteApp.swift
```

저장 대상은 HomeworkHelper의 `remote_power_config.json`이다. 기존 파일이 있으면 `.bak` 백업을 만든다.

### 1.5 Windows 데스크탑에서 pairing code 발급

pairing code는 Windows 데스크탑 로컬에서 발급한다. 패키지 앱에서는 `설정 > 원격 설정 > 페어링` 탭에서 `페어링 코드 발급`을 누르면 된다.

원격 자동화 문제를 재현/분석해야 하면 `설정 > 원격 설정 > 서버` 탭에서 `원격 진단 로그를 바탕 화면에 저장`을 켠다. 기본 로그 파일:

```text
%USERPROFILE%\Desktop\HomeworkHelperRemoteHost.log
```

과거에 언페어링한 기기 항목이 쌓였으면 `페어링` 탭의 `폐기된 기기 목록 정리`를 누른다.

터미널이 있는 개발 실행에서는 아래 API로도 발급할 수 있다.

```powershell
curl.exe -X POST http://127.0.0.1:8000/remote/pair/start
```

응답 예:

```json
{
  "code": "123456",
  "expires_at": 1234567890.0,
  "ttl_seconds": 300,
  "message": "macOS/Android 앱에서 이 코드를 입력해 페어링을 완료하세요."
}
```

여기서 `code`의 6자리 숫자를 MacBook 앱에 입력한다.

---

## 2. MacBook에서 할 일

MacBook은 Remote Client 역할이다.

### 2.1 macOS Remote Client 앱 패키징/실행

실사용 UI 테스트는 `swift run`이 아니라 `.app` 번들로 실행한다. `swift run`은 터미널에 붙은 프로세스로 실행되어 키보드 입력/포커스가 터미널과 꼬일 수 있다.

```bash
cd /Users/lsh930309/projects/HomeworkHelperServer
./.venv/bin/python tools/package_macos_remote_app.py
```

패키징 결과:

```text
/Users/lsh930309/projects/HomeworkHelperServer/dist/macos/HomeworkHelperRemote.app
```

실행:

```bash
open /Users/lsh930309/projects/HomeworkHelperServer/dist/macos/HomeworkHelperRemote.app
```

패키징 단계는 다음도 포함한다.

- Tailscale/LAN HTTP Remote Agent 접속을 위한 macOS App Transport Security 예외
- 기존 HomeworkHelper 앱 아이콘 기반 `HomeworkHelperRemote.icns`

이미 앱이 떠 있다면 완전히 종료한 뒤 다시 실행한다.

### 2.2 Tailscale 자동 탐색 사용

macOS 앱 좌측 패널에서 `Tailscale 찾기`를 누른다.

앱은 다음을 수행한다.

1. MacBook에서 `tailscale` CLI를 찾음
2. 없으면 Tailscale 자동 설치를 시도함
3. Tailscale 앱을 실행함
4. `tailscale status --json`을 다시 확인함
5. Windows/Desktop 후보 peer를 찾아 Base URL에 자동 적용함

정상 탐색되면 Base URL이 다음처럼 채워진다.

```text
http://100.109.140.97:8000
```

자동 탐색이 실패하면 Base URL을 직접 입력한다.

```text
http://100.109.140.97:8000
```

### 2.3 6자리 PIN 1회 입력으로 자동 설정

Windows 데스크탑에서 발급한 6자리 pairing code를 MacBook 앱의 `페어링 코드` 칸에 입력하고 `페어링 및 자동 설정`을 누른다.

성공하면 MacBook Keychain에 device token이 저장되고, 앱이 이어서 다음을 자동 점검/설정한다.

- 서버 Tailscale 상태 확인/복구
- SSH key 생성 및 Windows host로 public key 등록
- SSH host/key path 전원 설정 반영
- SmartThings CLI/device 후보 조회
- 후보가 1개이면 wake 대상 자동 적용, 여러 개이면 후보 선택 안내
- power config 저장

Windows 쪽 `전원` 탭은 주 마법사가 아니라 authorized_keys 승인/상태 확인 fallback이다. 기본 흐름은 macOS 클라이언트가 주도한다.

SmartThings CLI는 Mac 로컬 경로(`/opt/homebrew/bin/smartthings`, `/usr/local/bin/smartthings`, `~/.npm-global/bin/smartthings`)를 우선 후보로 사용한다. host가 꺼진 상태에서 wake를 수행해야 하므로, MacBook에 SmartThings CLI가 설치/로그인되어 있어야 offline wake fallback이 동작한다.

원격 자동화 문제 분석이 필요하면 `원격 설정 자동화` 섹션에서 `원격 진단 로그를 바탕 화면에 저장`을 켠다.

- Host 로그: UI에 표시되는 Windows Desktop `HomeworkHelperRemoteHost.log`
- Client 로그: Mac Desktop `HomeworkHelperRemoteClient.log`

### 2.4 새로고침 및 readiness 확인

페어링 후 `새로고침`을 누른다.

정상이라면 다음 항목들이 표시된다.

- Remote Agent 상태
- 상단/좌측 readiness dot 또는 pill
  - Beholder
  - Remote
  - Server
  - Power
  - Tailscale
- 게임/프로세스 목록
- 웹 숏컷 목록
- 플레이 요약
- Beholder 알림
- Android-PC 연결
- 등록 디바이스 목록
- 전원 설정 섹션

---

## 3. MacBook에서 네트워크 연결만 먼저 확인하기

앱 실행 전 MacBook 터미널에서 Windows 데스크탑 Remote Agent가 보이는지 확인할 수 있다.

```bash
curl http://100.109.140.97:8000/remote/status
```

가능한 결과:

- `200 OK`: 인증이 아직 필요 없거나 로컬/초기 상태
- `401 Unauthorized`: 서버에 닿았고, 인증 token이 필요하다는 뜻이므로 네트워크 연결 자체는 정상
- connection timeout/refused: 서버 실행, Tailscale 연결, Windows 방화벽, 포트 설정을 확인해야 함

readiness만 확인:

```bash
curl http://100.109.140.97:8000/remote/readiness
```

Tailscale ensure API를 직접 호출:

```bash
curl -X POST http://100.109.140.97:8000/remote/tailscale/ensure
```

이 API는 서버 장비에서 Tailscale CLI 확인/설치/재확인을 시도한다. Windows에서는 관리자 권한이나 설치 UI가 필요할 수 있다.

---

## 4. 전원 제어 관련

전원 버튼은 Windows 데스크탑의 `remote_power_config.json`이 설정되지 않았으면 비활성화되는 것이 정상이다.

설정 저장만 테스트할 수는 있지만, 실제 sleep/restart/shutdown/wake 명령은 장비 side effect가 있으므로 따로 의도하고 실행해야 한다.

전원 readiness 확인:

```bash
curl http://100.109.140.97:8000/remote/power/status
```

지원 명령이 비어 있으면 `tools/import_pcremote_power_config.py`로 설정을 가져오거나 macOS 앱의 `전원 설정` 섹션에서 직접 저장한다.

---

## 5. Windows 서버 앱 하단 readiness indicator

Windows HomeworkHelper GUI 하단 status bar에는 다음 dot indicator가 표시된다.

- `Beholder`: 대기 중인 Beholder incident 여부
- `Remote`: Remote API 인증/페어링 준비 상태
- `Server`: 서버 모드 종합 준비 상태
- `Power`: `remote_power_config.json` 설정 여부
- `Tailscale`: Tailscale CLI/status 확인 결과

색상 의미:

- 초록: 사용 가능/정상
- 노랑: 설정 필요/부분 준비
- 빨강: 확인 실패
- 회색: 아직 확인 전

---

## 6. 전체 테스트 체크리스트

Windows 데스크탑:

- [ ] HomeworkHelper Remote Agent 실행 중
- [ ] `HH_API_HOST=0.0.0.0`, `HH_API_PORT=8000`, `HH_REMOTE_REQUIRE_AUTH=1` 적용
- [ ] Tailscale 연결됨 또는 앱/서버의 Tailscale ensure로 설치/실행 시도 완료
- [ ] Windows Tailscale IP가 `100.109.140.97`인지 확인
- [ ] TCP `8000` 접근 허용
- [ ] `remote_power_config.json` import 또는 직접 설정 완료
- [ ] 하단 readiness indicator에서 Power/Tailscale/Remote 상태 확인
- [ ] `설정 > 원격 설정 > 페어링`에서 pairing code 발급
- [ ] 필요 시 `원격 진단 로그를 바탕 화면에 저장` ON
- [ ] 필요 시 `폐기된 기기 목록 정리` 실행

MacBook:

- [ ] `.app` 번들로 macOS Remote Client 실행
- [ ] `Tailscale 찾기` 실행
- [ ] Base URL 자동 적용 또는 `http://100.109.140.97:8000` 수동 입력
- [ ] pairing code 입력 후 페어링 성공
- [ ] 새로고침 성공
- [ ] readiness dot/pill 표시 확인
- [ ] token 갱신 테스트
- [ ] 앱 재실행 후 token 유지 확인
- [ ] 필요 시 `원격 진단 로그를 바탕 화면에 저장` ON
- [ ] 필요 시 `폐기된 기기 정리` 실행
- [ ] 게임/웹숏컷/플레이요약/Android-PC 연결/등록 디바이스 표시 확인

---

## 7. 문제 발생 시 빠른 진단

### MacBook 앱에서 `Could not connect to the server`

MacBook 터미널에서:

```bash
curl http://100.109.140.97:8000/remote/status
```

실패하면:

1. Windows 데스크탑 서버가 켜져 있는지 확인
2. Windows PowerShell에서 `HH_API_HOST=0.0.0.0`으로 실행했는지 확인
3. Windows 방화벽 TCP `8000` 허용 확인
4. 두 기기가 모두 Tailscale에 연결되어 있는지 확인
5. Windows 데스크탑 Tailscale IP가 `100.109.140.97`인지 확인

### Tailscale 자동 설치 후에도 준비되지 않음

1. Tailscale 앱이 열렸는지 확인
2. 로그인/브라우저 인증을 완료했는지 확인
3. macOS라면 System Extension/Network Extension 승인을 완료했는지 확인
4. Windows라면 설치 관리자 권한/UAC를 승인했는지 확인
5. 다시 `Tailscale 찾기`를 누른다

### 페어링 실패

1. pairing code가 만료되지 않았는지 확인한다. 기본 TTL은 300초다.
2. Windows 데스크탑에서 pairing code를 다시 발급한다.
3. MacBook 앱 Base URL이 Windows 데스크탑 주소인지 확인한다.
4. 진단 로그를 켠 뒤 Windows Desktop의 `HomeworkHelperRemoteHost.log`와 Mac Desktop의 `HomeworkHelperRemoteClient.log`를 확인한다.

### 새로고침이 401로 실패

1. MacBook 앱에서 다시 페어링한다.
2. 필요하면 MacBook 앱에서 token 삭제 후 재페어링한다.
3. Windows 데스크탑에서 등록 디바이스/token revoke 상태를 확인한다.
