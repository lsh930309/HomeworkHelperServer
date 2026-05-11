# HomeworkHelper Remote Controller 구동 환경 가이드

작성일: 2026-05-11
브랜치: `dev-remote`

## 1. 개발/로컬 검증

기본 서버는 기존처럼 loopback에만 열린다.

```bash
./.venv/bin/python homework_helper.pyw --server
```

기본값:

- host: `127.0.0.1`
- port: `8000`
- remote auth: 등록 디바이스가 없고 `HH_REMOTE_TOKEN`도 없으면 로컬 개발 편의를 위해 비활성

macOS 앱은 기본 URL `http://127.0.0.1:8000`으로 접속한다.

## 2. 페어링 절차

1. PC/서버 로컬에서 pairing code 발급:

```bash
curl -X POST http://127.0.0.1:8000/remote/pair/start
```

2. macOS 앱에서 Base URL과 pairing code를 입력하고 `페어링`을 누른다.
3. 앱은 `/remote/pair/confirm` 응답으로 받은 device token을 macOS Keychain에 저장한다.
4. 등록 디바이스가 하나라도 생기면 `/remote/*` 보호 API는 token을 요구한다.
5. macOS 앱의 `등록 디바이스` 섹션에서 토큰을 폐기할 수 있다.

주의: `/remote/pair/start`는 loopback 요청 또는 이미 인증된 디바이스 요청에서만 허용된다.

## 3. Tailscale/ZeroTier 바인딩

외부망에서 직접 접근하려면 Remote Agent를 tailnet/virtual-network IP 또는 전체 인터페이스에 bind한다.

예시:

```bash
HH_API_HOST=0.0.0.0 \
HH_API_PORT=8000 \
HH_REMOTE_REQUIRE_AUTH=1 \
./.venv/bin/python homework_helper.pyw --server
```

권장:

- Tailscale/ZeroTier 방화벽에서 개인 기기만 접근 허용
- 최초 pairing은 PC 로컬에서 `/remote/pair/start`로 발급
- `HH_REMOTE_REQUIRE_AUTH=1` 유지
- `HH_REMOTE_TOKEN` 또는 device pairing token 없이 공인망/터널에 노출 금지

## 4. 전원 제어 설정

실제 파일은 사용자 데이터 디렉터리에 둔다.

- macOS/Linux 개발 환경 예: `~/.config/HomeworkHelper/homework_helper_data/remote_power_config.json`
- Windows 설치 환경 예: `%APPDATA%/HomeworkHelper/homework_helper_data/remote_power_config.json`

템플릿은 저장소 루트의 `remote_power_config.example.json`을 복사해 사용한다.

```bash
cp remote_power_config.example.json ~/.config/HomeworkHelper/homework_helper_data/remote_power_config.json
```

필드:

- `smartthings_device_id`: SmartThings WoL 장치 ID
- `smartthings_cli_path`: SmartThings CLI 경로
- `ssh_host`: Windows PC의 Tailscale host, DDNS, 또는 공인 IP
- `ssh_port`: Windows OpenSSH 포트
- `ssh_user`: Windows 사용자
- `ssh_key_path`: SSH private key 경로
- `status_timeout_seconds`: TCP 상태 확인 timeout

환경변수 override도 지원한다.

```bash
HH_REMOTE_SMARTTHINGS_DEVICE_ID=...
HH_REMOTE_SMARTTHINGS_CLI_PATH=/opt/homebrew/bin/smartthings
HH_REMOTE_SSH_HOST=...
HH_REMOTE_SSH_PORT=50022
HH_REMOTE_SSH_USER=...
HH_REMOTE_SSH_KEY_PATH=~/.ssh/id_ed25519
HH_REMOTE_STATUS_TIMEOUT_SECONDS=4
```

보안 주의:

- `remote_power_config.json`에는 개인 IP, 장치 ID, key path가 들어갈 수 있으므로 Git에 커밋하지 않는다.
- Remote API는 action enum만 받고 임의 shell 명령을 받지 않는다.
- 전원 명령 결과는 `remote_command_audit.jsonl`에 기록된다.

## 5. 현재 검증 명령

커밋 전 최소 검증:

```bash
./.venv/bin/python -m pytest tests/test_remote_routes.py
./.venv/bin/python -m pytest
cd remote_clients/macos/HomeworkHelperRemote && swift build
```
