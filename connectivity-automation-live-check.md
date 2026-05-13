# Connectivity Automation Live Check

목표: macOS Remote Client에서 **Windows가 발급한 6자리 PIN을 한 번 입력**하면 현재 구현된 원격 연결 설정이 자동 완료되는지 실사용 환경에서 판정한다.

## 성공 기준

1. Windows 앱에서는 `설정 > 원격 설정`에서 PIN만 발급한다.
2. macOS 앱에서는 Base URL 자동 탐색 또는 수동 입력 후 6자리 PIN을 한 번 입력하고 `페어링 및 자동 설정`만 누른다.
3. macOS 앱이 자동으로 다음을 수행한다.
   - Keychain token 저장
   - Tailscale 서버 상태 확인/복구 시도
   - SSH key 생성 및 서버 public key 등록
   - SmartThings CLI/device 후보 조회
   - 후보가 1개이면 wake 대상 자동 적용, 여러 개이면 후보 선택 안내
   - power config 저장
4. macOS 앱을 종료 후 재실행해도 페어링 상태가 유지된다.
5. Windows host/Remote Agent가 꺼져 있거나 연결 불가하면 macOS 앱이 서버 offline 상태를 표시한다.
6. SmartThings wake 설정이 저장된 경우, 서버 offline 상태에서도 macOS 앱의 `켜기`가 로컬 SmartThings CLI fallback을 사용한다.
7. Windows Tailscale status가 `BackendState` 없는 JSON을 반환해도 plain `tailscale status` fallback으로 IP가 감지된다.
8. 필요 시 Windows/Mac 양쪽에서 `원격 진단 로그를 바탕 화면에 저장`을 켜고 Desktop 로그로 페어링/Tailscale/전원 자동화 이벤트를 확인할 수 있다.
9. 원격 설정 다이얼로그를 열거나 상태를 조회할 때 Windows에서 PowerShell 창이 깜빡이지 않는다.

## Windows host 준비

1. 최신 `dev-remote` 패키지/소스에서 HomeworkHelper를 실행한다.
2. `설정 > 원격 설정`을 연다.
3. 서버 모드가 켜져 있는지 확인한다.
4. `페어링` 탭에서 6자리 PIN을 발급한다.
5. `전원` 탭은 주 설정 마법사가 아니다. 상태/승인 fallback이다. macOS에서 자동 전송한 SSH public key 승인 상태를 확인할 때만 사용한다.
6. 문제 재현이 필요하면 `서버` 탭에서 `원격 진단 로그를 바탕 화면에 저장`을 켠다. 로그 파일은 기본적으로 Windows Desktop의 `HomeworkHelperRemoteHost.log`에 JSONL 형식으로 남는다.
7. 과거에 revoke한 기기가 많이 쌓였으면 `페어링` 탭의 `폐기된 기기 목록 정리`를 누른다.

## macOS client 절차

1. 최신 `dev-remote`에서 macOS 앱을 패키징/실행한다.

```bash
./.venv/bin/python tools/package_macos_remote_app.py
open dist/macos/HomeworkHelperRemote.app
```

2. `Tailscale 찾기` 또는 `자동 설정 점검`으로 Windows Base URL을 적용한다.
3. Windows에서 발급한 6자리 PIN을 입력하고 `페어링 및 자동 설정`을 누른다.
4. 좌측 `원격 설정 자동화` 체크리스트가 다음 상태가 되는지 확인한다.
   - Mac Tailscale: 준비됨
   - Windows 서버: 준비됨 또는 명확한 offline 안내
   - 페어링: 완료/Keychain token 저장
   - 전원 관리: 지원 명령 또는 SmartThings 후보 선택 안내
   - 서버 Tailscale: 준비됨 또는 복구 안내
5. SmartThings 후보가 여러 개면 표시된 후보 중 wake 대상 콘센트/기기를 선택하고 `전원 설정 저장`을 누른다.
6. 문제 분석이 필요하면 `원격 설정 자동화` 섹션에서 `원격 진단 로그를 바탕 화면에 저장`을 켠다. Host 로그 경로는 UI에 표시되고, Mac 클라이언트 이벤트는 Mac Desktop의 `HomeworkHelperRemoteClient.log`에 JSONL로 남는다.
7. 등록 디바이스 섹션에서 `폐기된 기기 정리`를 눌러 host에 남은 revoked device 항목을 정리할 수 있다.

## 자동 검증 명령

개발 Mac에서 로컬 Remote Agent와 macOS ViewModel 경로를 검증한다. 실제 SmartThings는 fake CLI로 대체하지만, PIN→token→offline local wake 제어 경로를 검증한다.

```bash
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py --timeout 20
```

기대 결과:

```text
step: confirmPairing
step: offline local wake
macOS RemoteDashboardViewModel smoke passed: ...
```

실제 Windows host 연결성은 다음으로 확인한다.

```bash
./.venv/bin/python tools/smoke_remote_controller_connectivity.py \
  --base-url http://100.109.140.97:8000 \
  --expect-auth
```

페어링 token이 있으면:

```bash
./.venv/bin/python tools/smoke_remote_controller_connectivity.py \
  --base-url http://100.109.140.97:8000 \
  --token '<Keychain token 또는 앱에서 갱신한 token>' \
  --expect-auth
```

## Tailscale 문제 판정

Windows host에서 `windows_tailscale.log`와 같은 증상이 보이면:

```text
BackendState 없음 / self_ips 없음 / backend_state unknown
```

현재 코드는 `tailscale status --json` 결과가 unknown이거나 JSON 해석이 어려운 경우 plain `tailscale status`를 추가 호출해서 `100.x.y.z` IP를 파싱한다. 그래도 실패하면 다음을 기록한다.

```powershell
tailscale status --json
tailscale status
tailscale ip -4
where tailscale
```

## 아직 자동화하지 않는 것

- Windows OpenSSH Server 설치/방화벽 규칙 변경은 OS 관리자 권한이 필요하므로 자동 무승인 실행하지 않는다.
- SmartThings 계정 로그인은 외부 계정 권한이므로 앱이 대신 로그인하지 않는다.
- SmartThings 후보가 여러 개면 안전상 자동 선택하지 않는다.
- 원격 진단 로그는 기본 OFF다. 사용자가 켜야만 Desktop 파일에 기록한다.
