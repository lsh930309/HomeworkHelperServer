# Host SSH Diagnostics and Remote Support Runbook

Last refreshed: 2026-05-22

이 문서는 macOS Remote Client에서 **Tailscale은 닿지만 Remote Agent HTTP가 응답하지 않거나**, Windows 호스트 앱이 켜져 있는데 **매우 느리고 굼뜬 상태**가 되었을 때 사용하는 원격 지원 절차다.

핵심 목표는 **호스트 앱을 재시작하거나 업데이트하기 전에 현재 문제 상태를 보존하고**, SSH로 증거를 수집한 뒤, DB 안전성을 확인하고, 필요한 경우 안전하게 종료하는 것이다.

## 1. 언제 이 runbook을 쓴다

다음 조합이면 이 문서를 우선 적용한다.

- 클라이언트에서 Tailscale ping 또는 TCP connect는 성공한다.
- `http://<host>:8000/docs`는 빠르게 열리거나 TCP listener는 살아 있다.
- `/api/gui/health`, `/remote/status`, `/remote/readiness`, `/processes`, `/settings` 같은 DB-backed route가 timeout된다.
- Windows 호스트의 `homework_helper.exe` 또는 GUI가 켜져 있지만 조작이 매우 느리다.
- 아직 호스트 앱을 재시작하지 않았고, 문제 상태를 바로 진단할 수 있다.

이 경우 네트워크/Tailscale 문제로 단정하지 않는다. **FastAPI/uvicorn은 살아 있지만 DB 접근 경로, SQLAlchemy connection, thread/gate, 또는 stale API server lifecycle이 고착된 상태**일 수 있다.

## 2. 절대 먼저 하지 말아야 할 일

1. **재시작/재패키징/업데이트를 먼저 하지 않는다.**
   - 현재 고착 상태의 PID, log, endpoint timing, DB/WAL 상태가 사라진다.
2. **`app_data.db-wal` 또는 `app_data.db-shm`를 삭제하지 않는다.**
   - WAL mode SQLite에서는 아직 checkpoint되지 않은 변경분이 WAL에 남아 있을 수 있다.
3. **DB 백업 없이 `Stop-Process -Force`를 먼저 실행하지 않는다.**
   - DB 파일 손상 가능성은 낮아도, app-level partial state를 확인할 기회를 잃는다.
4. **pairing token, SmartThings PAT, SSH private key 내용을 로그/문서/커밋에 남기지 않는다.**
5. **incident ZIP을 repo에 커밋하지 않는다.**
   - ZIP에는 실제 사용자 DB와 로그가 들어 있다.

## 3. 준비물

macOS 클라이언트에서 다음이 확인되어야 한다.

- SSH target host, user, port
- SSH private key path
- Tailscale host IP 또는 MagicDNS
- Windows OpenSSH 접속 가능 상태

macOS Remote Client 설정은 보통 다음 위치에서 확인한다.

```bash
defaults read dev.homeworkhelper.remote.macos remote.powerConfig
```

필드 예시:

```json
{
  "ssh_host": "<tailscale-host-ip-or-name>",
  "ssh_user": "<windows-user>",
  "ssh_port": 22,
  "ssh_key_path": "~/.ssh/homeworkhelper_remote_ed25519"
}
```

SSH 접속 테스트:

```bash
ssh -i ~/.ssh/homeworkhelper_remote_ed25519 \
  -p 22 \
  -o BatchMode=yes \
  -o ConnectTimeout=8 \
  <user>@<host> \
  powershell -NoProfile -Command '$env:COMPUTERNAME'
```

## 4. 클라이언트 측 1차 분류

먼저 Mac에서 HTTP endpoint별 응답을 나눈다.

```bash
python - <<'PY'
import time
import urllib.request

base = "http://<host>:8000"
paths = [
    "/docs",
    "/api/gui/ping",
    "/api/gui/health",
    "/remote/status",
    "/remote/readiness",
]

for path in paths:
    url = base + path
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read(200)
        print(path, "status", response.status, "ms", int((time.perf_counter() - started) * 1000), "sample", body[:80])
    except Exception as exc:
        print(path, "error", type(exc).__name__, str(exc), "ms", int((time.perf_counter() - started) * 1000))
PY
```

판단 기준:

| 관측 | 의미 |
| --- | --- |
| Tailscale ping OK + TCP 8000 open + `/docs` fast | 네트워크/Tailscale보다는 host API 내부 문제 가능성이 높다. |
| `/api/gui/ping` fast + `/api/gui/health` timeout | uvicorn event loop는 살아 있고 DB probe가 고착된 가능성이 높다. |
| `/docs`도 timeout 또는 connect refused | API server 자체가 멈췄거나 listener가 없다. |
| `/remote/status`만 실패 | 인증, remote router, DB route, token store를 추가 확인한다. |

## 5. SSH로 호스트 상태를 먼저 기록한다

PowerShell 스크립트가 길어질 때는 `-EncodedCommand` 대신 **원격 `%TEMP%`에 `.ps1` 파일을 올리고 `-File`로 실행**한다. Windows OpenSSH/PowerShell 조합에서는 긴 encoded command가 명령줄 길이 제한에 걸릴 수 있다.

### 5.1 최소 상태 스냅샷

```powershell
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DataDir = Join-Path $env:APPDATA 'HomeworkHelper\homework_helper_data'

"== data dir =="
$DataDir

"== port 8000 =="
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess

"== homework processes =="
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'homework_helper.exe' -or ($_.CommandLine -like '*HomeworkHelper*homework_helper.exe*') } |
  Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine,ExecutablePath

"== db files =="
foreach ($name in 'app_data.db','app_data.db-wal','app_data.db-shm','db_server.log','db_server.pid','db_server_meta.json') {
  $path = Join-Path $DataDir $name
  if (Test-Path -LiteralPath $path) {
    Get-Item -LiteralPath $path | Select-Object FullName,Length,LastWriteTime
    Get-FileHash -LiteralPath $path -Algorithm SHA256
  } else {
    "$name missing"
  }
}

"== log tail =="
Get-Content -LiteralPath (Join-Path $DataDir 'db_server.log') -Tail 80 -ErrorAction SilentlyContinue
```

### 5.2 호스트 로컬 endpoint timing

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

foreach ($path in '/docs','/api/gui/ping','/api/gui/health','/remote/status','/remote/readiness','/processes','/settings') {
  $url = "http://127.0.0.1:8000$path"
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 8 -ErrorAction Stop
    $sw.Stop()
    [pscustomobject]@{
      Path = $path
      Ok = $true
      Status = $response.StatusCode
      ElapsedMs = $sw.ElapsedMilliseconds
      Bytes = if ($response.Content) { $response.Content.Length } else { 0 }
    }
  } catch {
    $sw.Stop()
    [pscustomobject]@{
      Path = $path
      Ok = $false
      Status = $null
      ElapsedMs = $sw.ElapsedMilliseconds
      Error = $_.Exception.Message
    }
  }
}
```

## 6. 종료 전 DB 백업을 만든다

가능하면 SQLite online backup API를 쓴다. Windows host에 Python/sqlite CLI가 없을 수도 있으므로, 최소 안전선은 다음이다.

1. `app_data.db`, `app_data.db-wal`, `app_data.db-shm`를 **같이** 복사한다.
2. `db_server.log`, `db_server.pid`, `db_server_meta.json`도 같이 보존한다.
3. 복사본과 live file의 SHA256을 기록한다.
4. 종료 후 같은 파일들을 한 번 더 cold copy한다.
5. Mac으로 내려받아 `PRAGMA integrity_check`와 `PRAGMA quick_check`를 수행한다.

### 6.1 원격 백업 폴더 생성 및 hot copy

```powershell
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$DataDir = Join-Path $env:APPDATA 'HomeworkHelper\homework_helper_data'
$BackupRoot = Join-Path $DataDir 'incident_backups'
$PidFile = Join-Path $DataDir 'db_server.pid'
$PidText = if (Test-Path -LiteralPath $PidFile) { (Get-Content -LiteralPath $PidFile -Raw).Trim() } else { 'unknown' }
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$IncidentDir = Join-Path $BackupRoot "${Stamp}_api_stall_pid${PidText}"
$HotDir = Join-Path $IncidentDir 'pre_termination_hot_copy'

New-Item -ItemType Directory -Path $HotDir -Force | Out-Null

foreach ($name in 'app_data.db','app_data.db-wal','app_data.db-shm','db_server.log','db_server.pid','db_server_meta.json') {
  $src = Join-Path $DataDir $name
  if (Test-Path -LiteralPath $src) {
    Copy-Item -LiteralPath $src -Destination (Join-Path $HotDir $name) -Force
  }
}

Get-ChildItem -LiteralPath $HotDir -Force |
  ForEach-Object {
    [pscustomobject]@{
      Name = $_.Name
      Length = $_.Length
      LastWriteTime = $_.LastWriteTime
      SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
  } |
  ConvertTo-Json -Depth 4 |
  Set-Content -LiteralPath (Join-Path $IncidentDir 'pre_termination_hot_copy_manifest.json') -Encoding UTF8

$IncidentDir
```

`app_data.db` hot copy가 실패하면 **종료 단계로 넘어가지 않는다**.

## 7. 안전 종료 절차

종료 대상은 다음 순서로 모은다.

- `db_server.pid`에 기록된 PID
- `Get-NetTCPConnection -LocalPort 8000`의 `OwningProcess`
- GUI까지 굼뜬 경우, 명시적으로 확인된 `homework_helper.exe` GUI PID

종료는 부드럽게 시도하고, 남아 있을 때만 강제 종료한다.

```powershell
$DataDir = Join-Path $env:APPDATA 'HomeworkHelper\homework_helper_data'
$PidFile = Join-Path $DataDir 'db_server.pid'
$TargetPids = New-Object System.Collections.Generic.HashSet[int]

if (Test-Path -LiteralPath $PidFile) {
  $pidText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
  $parsed = 0
  if ([int]::TryParse($pidText, [ref]$parsed)) { [void]$TargetPids.Add($parsed) }
}

Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
  Where-Object { $_.OwningProcess -gt 0 } |
  ForEach-Object { [void]$TargetPids.Add([int]$_.OwningProcess) }

foreach ($targetPid in @($TargetPids | Sort-Object)) {
  try {
    $p = Get-Process -Id $targetPid -ErrorAction Stop
    if ($p.MainWindowHandle -ne 0) {
      $null = $p.CloseMainWindow()
    }
  } catch {}
}

Start-Sleep -Seconds 5

foreach ($targetPid in @($TargetPids | Sort-Object)) {
  if (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {
    Stop-Process -Id $targetPid -ErrorAction SilentlyContinue
  }
}

Start-Sleep -Seconds 5

foreach ($targetPid in @($TargetPids | Sort-Object)) {
  if (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {
    Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
  }
}

"== remaining =="
foreach ($targetPid in @($TargetPids | Sort-Object)) {
  [pscustomobject]@{
    ProcessId = $targetPid
    StillAlive = [bool](Get-Process -Id $targetPid -ErrorAction SilentlyContinue)
  }
}
```

## 8. 종료 후 재확인

```powershell
$DataDir = Join-Path $env:APPDATA 'HomeworkHelper\homework_helper_data'

"== post processes =="
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'homework_helper.exe' -or ($_.CommandLine -like '*HomeworkHelper*homework_helper.exe*') } |
  Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine

"== post port 8000 =="
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue

"== post db hashes =="
foreach ($name in 'app_data.db','app_data.db-wal','app_data.db-shm') {
  $path = Join-Path $DataDir $name
  if (Test-Path -LiteralPath $path) {
    Get-Item -LiteralPath $path | Select-Object FullName,Length,LastWriteTime
    Get-FileHash -LiteralPath $path -Algorithm SHA256
  }
}
```

종료 후 cold copy:

```powershell
# 새 PowerShell session에서 실행한다면 먼저 기존 incident 폴더를 다시 지정한다.
# $IncidentDir = 'C:\Users\<user>\AppData\Roaming\HomeworkHelper\homework_helper_data\incident_backups\<incident>'

$ColdDir = Join-Path $IncidentDir 'post_termination_cold_copy'
New-Item -ItemType Directory -Path $ColdDir -Force | Out-Null

foreach ($name in 'app_data.db','app_data.db-wal','app_data.db-shm','db_server.log','db_server.pid','db_server_meta.json') {
  $src = Join-Path $DataDir $name
  if (Test-Path -LiteralPath $src) {
    Copy-Item -LiteralPath $src -Destination (Join-Path $ColdDir $name) -Force
  }
}

Compress-Archive -Path (Join-Path $IncidentDir '*') -DestinationPath "$IncidentDir.zip" -Force
"$IncidentDir.zip"
```

## 9. Mac에서 백업 DB 무결성 확인

ZIP을 Mac으로 내려받는다.

```bash
scp -i ~/.ssh/homeworkhelper_remote_ed25519 \
  -P 22 \
  '<user>@<host>:C:/Users/<user>/AppData/Roaming/HomeworkHelper/homework_helper_data/incident_backups/<incident>.zip' \
  /private/tmp/
```

SQLite 확인:

```bash
python - <<'PY'
import pathlib
import shutil
import sqlite3
import zipfile

zip_path = pathlib.Path("/private/tmp/<incident>.zip")
extract_dir = pathlib.Path("/private/tmp/<incident>")
if extract_dir.exists():
    shutil.rmtree(extract_dir)
extract_dir.mkdir(parents=True)

with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(extract_dir)

for phase in ["pre_termination_hot_copy", "post_termination_cold_copy"]:
    # Windows-created zip entries may contain backslashes on macOS.
    candidates = [
        path
        for path in extract_dir.rglob("*")
        if path.is_file() and str(path).replace("\\", "/").endswith(f"{phase}/app_data.db")
    ]
    if not candidates:
        print(phase, "db not found")
        continue
    db = candidates[0]
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5) as conn:
        print(phase, "integrity_check", conn.execute("PRAGMA integrity_check").fetchall())
        print(phase, "quick_check", conn.execute("PRAGMA quick_check").fetchall())
        print(phase, "schema_count", conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0])
        print(phase, "journal_mode", conn.execute("PRAGMA journal_mode").fetchone()[0])
PY
```

합격 기준:

- `integrity_check = ok`
- `quick_check = ok`
- schema count가 정상 범위
- 종료 전/후 DB/WAL/SHM hash가 동일하거나, 종료 과정에서 checkpoint가 일어난 경우 변경 원인이 로그로 설명 가능
- 종료 후 target PID가 모두 사라짐
- 종료 후 port 8000 listener가 사라짐

## 10. 새 버전 적용 후 확인

호스트 앱을 새 빌드로 업데이트하고 실행한 뒤:

```bash
python - <<'PY'
import time
import urllib.request

base = "http://<host>:8000"
for path in ["/api/gui/ping", "/api/gui/health", "/remote/status", "/remote/readiness"]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            print(path, response.status, int((time.perf_counter() - started) * 1000), response.read(200))
    except Exception as exc:
        print(path, type(exc).__name__, exc, int((time.perf_counter() - started) * 1000))
PY
```

호스트 로그에서 다음도 확인한다.

- `db_server_meta.json` 생성 여부
- `parent watchdog 시작`
- `/api/gui/health`의 `db_probe_ms`
- `slow_api_request` 경고 유무
- GUI 종료 시 `PID 파일 삭제`, `메타데이터 파일 삭제`, `WAL checkpoint 완료`

## 11. 2026-05-22 incident record

이번 runbook의 기준이 된 실제 처리 기록이다.

### 증상

- macOS Remote Client에서 Tailscale ping은 성공했다.
- Host target의 TCP 8000 connect도 가능했다.
- Windows host app은 실행 중이었지만 매우 굼떴다.
- Remote Agent HTTP는 no response 상태였다.

### 원격 진단 증거

- Mac → host:
  - TCP connect는 약 4-5ms 수준으로 성공.
  - `/docs`는 빠르게 200 응답.
  - `/api/gui/health`, `/remote/status`, `/remote/readiness`는 8초 안팎 timeout.
- Windows host 로컬:
  - `0.0.0.0:8000` listener PID: `32068`
  - `/docs`: 200, 약 14-21ms
  - `/api/gui/health`, `/remote/status`, `/remote/readiness`: 약 5-8초 timeout
  - `/openapi.json`: 빠르게 200
  - `/processes`, `/settings`, `/api/beholder/incidents/active`: timeout
- Process:
  - API server PID `32068`, started `2026-05-20 16:38:51`
  - GUI/host app PID `4336`, started `2026-05-22 00:20:01`
  - parent PID `12884`는 더 이상 존재하지 않았다.
- DB:
  - 외부 SQLite read-only query는 빠르게 성공.
  - `sqlite_master` count: `25`
  - `db_server.log`의 주기적 WAL checkpoint 기록은 `2026-05-21 12:51:28` 이후 멈춰 있었다.

### 판단

DB 파일 자체가 전역 lock 또는 손상 상태였다고 보기 어렵다. `/docs`와 `/openapi.json`은 빠르지만 DB-backed route만 timeout되었고, read-only SQLite 접근은 빨랐다. 따라서 주 원인은 **장기 실행 API server process 내부의 DB connection/session/pool/gate 또는 stale lifecycle 고착**으로 판단했다.

### 조치

- 종료 전 hot copy와 종료 후 cold copy를 생성했다.
- `app_data.db`, `app_data.db-wal`, `app_data.db-shm`를 같이 보존했다.
- PID `4336`, `32068`을 graceful stop 후 확인했고 force kill은 필요 없었다.
- 종료 후 target PID는 모두 `still_alive=false`.
- 종료 후 port 8000 listener 없음.
- Mac에서 hot/cold copy 모두:
  - `PRAGMA integrity_check = ok`
  - `PRAGMA quick_check = ok`
  - schema count `25`
  - WAL mode 확인
  - DB/WAL/SHM SHA256 종료 전/후 동일

### 코드 후속 조치

Commit `f73bbe2`에서 다음을 반영했다.

- SQLite engine을 `NullPool`로 전환해 장기 실행 pooled connection 고착 가능성을 줄임.
- stale API server가 `/api/gui/health`에 실패하면 PID file과 port listener를 기준으로 회수 후 재시작.
- GUI parent process가 사라진 API server는 parent watchdog으로 스스로 종료.
- `db_server_meta.json`으로 PID, parent PID, 시작 시각, 포트를 기록.

## 12. 다음 재발 시 남길 최소 보고 항목

이 템플릿을 issue, PR, 작업 메모, 또는 채팅에 붙인다.

```text
Date/time:
Client:
Host:
Host app version/commit:

Client observations:
- Tailscale ping:
- TCP 8000:
- /docs:
- /api/gui/ping:
- /api/gui/health:
- /remote/status:
- /remote/readiness:

Host observations:
- port 8000 listener PID:
- homework_helper.exe process list:
- db_server.pid:
- db_server_meta.json:
- db_server.log last checkpoint:
- endpoint timing from 127.0.0.1:

DB safety:
- incident backup path:
- hot copy integrity_check:
- cold copy integrity_check:
- DB/WAL/SHM hashes:

Action:
- stopped PIDs:
- force kill used?:
- post port 8000:
- post processes:

Conclusion:
- network/Tailscale:
- API event loop:
- DB-backed route:
- suspected root cause:
```
