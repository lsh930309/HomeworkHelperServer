# macOS Remote Client 실사용 테스트 튜토리얼

이 문서는 **Windows 데스크탑에서 HomeworkHelper 본체/Remote Agent를 실행**하고, **MacBook의 macOS Remote Client 앱으로 접속/페어링/조작**하는 절차를 정리한다.

## 현재 테스트 환경

- MacBook, Remote Client 역할: `100.114.138.46`
- Windows 데스크탑, Remote Agent/서버 역할: `100.109.140.97`
- Remote API port: `8000`
- MacBook 앱에서 입력할 Base URL:

```text
http://100.109.140.97:8000
```

주의: MacBook에서 `127.0.0.1`은 MacBook 자신을 뜻한다. Windows 데스크탑에 붙을 때는 반드시 Windows 데스크탑의 Tailscale IP 또는 LAN IP를 입력한다.

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

### 1.2 Windows 방화벽 확인

Windows Defender Firewall에서 TCP `8000` inbound 접근이 허용되어야 한다.

Tailscale로 테스트할 때는 가능하면 Tailscale 네트워크에서만 접근되도록 제한하는 것이 좋다.

### 1.3 Windows 데스크탑에서 pairing code 발급

pairing code는 Windows 데스크탑 로컬에서 발급한다.

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

여기서 `"code"`의 6자리 숫자를 MacBook 앱에 입력한다.

---

## 2. MacBook에서 할 일

MacBook은 Remote Client 역할이다.

### 2.1 macOS Remote Client 앱 실행

실사용 UI 테스트는 `swift run`이 아니라 `.app` 번들로 실행한다. `swift run`은 터미널에 붙은 프로세스로 실행되어 키보드 입력/포커스가 터미널과 꼬일 수 있다.

MacBook 터미널에서 앱 번들을 만든다.

```bash
cd /Users/lsh930309/projects/HomeworkHelperServer
./.venv/bin/python tools/package_macos_remote_app.py
```

이 패키징 단계는 Tailscale/LAN의 `http://100.109.140.97:8000` Remote Agent에 접속할 수 있도록 macOS App Transport Security 예외를 `Info.plist`에 포함한다. `swift run`으로 직접 실행하면 이 앱 번들 설정이 적용되지 않을 수 있으므로 실사용 테스트는 반드시 아래 `.app`을 `open`으로 실행한다.

생성 위치:

```text
/Users/lsh930309/projects/HomeworkHelperServer/dist/macos/HomeworkHelperRemote.app
```

실행:

```bash
open /Users/lsh930309/projects/HomeworkHelperServer/dist/macos/HomeworkHelperRemote.app
```

이미 앱이 떠 있다면 완전히 종료한 뒤 다시 실행한다.

### 2.2 Base URL 입력

macOS 앱 좌측 패널의 `Base URL`에 다음을 입력한다.

```text
http://100.109.140.97:8000
```

### 2.3 pairing code 입력

Windows 데스크탑에서 발급한 6자리 pairing code를 MacBook 앱의 `페어링 코드` 칸에 입력하고 `페어링`을 누른다.

성공하면 MacBook Keychain에 device token이 저장된다.

### 2.4 새로고침

페어링 후 `새로고침`을 누른다.

정상이라면 다음 항목들이 표시된다.

- Remote Agent 상태
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

---

## 4. 전원 제어 관련

전원 버튼은 Windows 데스크탑의 `remote_power_config.json`이 설정되지 않았으면 비활성화되는 것이 정상이다.

설정 저장만 테스트할 수는 있지만, 실제 sleep/restart/shutdown/wake 명령은 장비 side effect가 있으므로 따로 의도하고 실행해야 한다.

---

## 5. 전체 테스트 체크리스트

Windows 데스크탑:

- [ ] Tailscale 연결됨
- [ ] Windows Tailscale IP가 `100.109.140.97`인지 확인
- [ ] HomeworkHelper Remote Agent 실행 중
- [ ] TCP `8000` 접근 허용
- [ ] `curl.exe -X POST http://127.0.0.1:8000/remote/pair/start`로 pairing code 발급

MacBook:

- [ ] Tailscale 연결됨
- [ ] MacBook Tailscale IP가 `100.114.138.46`인지 확인
- [ ] `curl http://100.109.140.97:8000/remote/status`로 연결 확인
- [ ] macOS Remote Client 실행
- [ ] Base URL에 `http://100.109.140.97:8000` 입력
- [ ] pairing code 입력 후 페어링 성공
- [ ] 새로고침 성공
- [ ] token 갱신 테스트
- [ ] 앱 재실행 후 token 유지 확인
- [ ] 게임/웹숏컷/플레이요약/Android-PC 연결/등록 디바이스 표시 확인

---

## 6. 문제 발생 시 빠른 진단

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

### 페어링 실패

1. pairing code가 만료되지 않았는지 확인한다. 기본 TTL은 300초다.
2. Windows 데스크탑에서 pairing code를 다시 발급한다.
3. MacBook 앱 Base URL이 `http://100.109.140.97:8000`인지 확인한다.

### 새로고침이 401로 실패

1. MacBook 앱에서 다시 페어링한다.
2. 필요하면 MacBook 앱에서 token 삭제 후 재페어링한다.
3. Windows 데스크탑에서 등록 디바이스/token revoke 상태를 확인한다.
