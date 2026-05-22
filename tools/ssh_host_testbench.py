#!/usr/bin/env python3
"""Isolated SSH real-device testbench for the Windows HomeworkHelper host.

This tool is intentionally agent-oriented: it prepares a disposable shadow copy
of the installed host package, starts a renamed server-only process on a random
loopback port with isolated AppData/mutex values, exercises logic/API paths, then
writes a local report and removes the remote test root.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import random
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_EXE = r"C:\Program Files\HomeworkHelper\homework_helper.exe"
DEFAULT_ARTIFACT_ROOT = Path("artifacts/ssh-host-testbench")
DEFAULT_ENDPOINTS = [
    "/api/gui/ping",
    "/api/gui/health",
    "/remote/status",
    "/remote/readiness",
    "/remote/local-store/health",
    "/processes",
    "/settings",
]
MANUAL_TEST_ITEMS = [
    "Registry modification or installer registration checks",
    "UAC/admin privilege transition and elevation prompts",
    "Windows scheduled tasks or service registration changes",
    "Firewall/OpenSSH/Tailscale system configuration changes",
    "Actual sleep/restart/shutdown/power actions",
    "Real game, browser, or OBS launches that create user-visible side effects",
]
PRODUCTION_SAFETY_RULES = [
    "Run a renamed shadow executable from %TEMP%, never the installed production executable in place.",
    "Use a random HH_API_PORT and HH_SERVER_MUTEX_NAME so the production API server can keep running.",
    "Set HH_TEST_APPDATA_DIR, APPDATA, and LOCALAPPDATA to a session root under %TEMP%.",
    "Stop only the testbench PID that this tool started; never kill by the production image name.",
    "Remove only the generated %TEMP%\\HHHostTestbench\\<session> root unless --keep-remote is used.",
]


@dataclass(frozen=True)
class SSHConfig:
    host: str
    user: str | None
    port: int
    identity: str | None
    connect_timeout: int = 8

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


@dataclass(frozen=True)
class TestbenchConfig:
    session_id: str
    exe: str
    remote_port: int
    keep_remote: bool
    timeout: int
    artifact_dir: Path


def _safe_token(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-_")
    return cleaned[:64] or "session"


def default_session_id() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"hh-tb-{stamp}-{random.randrange(16**4):04x}"


def default_remote_port() -> int:
    return random.randrange(18000, 25000)


def _ssh_args(config: SSHConfig) -> list[str]:
    args = [
        "ssh",
        "-p",
        str(config.port),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={config.connect_timeout}",
    ]
    if config.identity:
        args.extend(["-i", config.identity])
    args.append(config.target)
    return args


def run_remote_powershell(config: SSHConfig, script: str, *, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a PowerShell script over SSH without writing a production-host file."""
    command = _ssh_args(config) + [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "-",
    ]
    return subprocess.run(  # noqa: S603 - target/identity are explicit CLI inputs for an SSH support tool.
        command,
        input=script,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _json_b64(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def build_remote_script(config: TestbenchConfig) -> str:
    """Return the remote PowerShell script used for the isolated real-device run."""
    payload = {
        "SessionId": config.session_id,
        "Exe": config.exe,
        "RemotePort": config.remote_port,
        "KeepRemote": config.keep_remote,
        "ProbeTimeoutSec": config.timeout,
        "Endpoints": DEFAULT_ENDPOINTS,
        "SeedProcess": {
            "id": f"testbench-{config.session_id}",
            "name": "SSH Testbench Sample",
            "monitoring_path": r"C:\Windows\System32\notepad.exe",
            "launch_path": r"C:\Windows\System32\notepad.exe",
            "preferred_launch_type": "direct",
        },
    }
    encoded = _json_b64(payload)
    return textwrap.dedent(
        fr"""
        $ErrorActionPreference = 'Stop'
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        # Logic endpoint scope: /api/gui/ping, /api/gui/health, /remote/status, /remote/readiness, /remote/local-store/health, /processes, /settings
        # Disposable seed scope: one managed_process row with preferred_launch_type=direct; no remote launch call is made.
        $ConfigJson = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded}'))
        $Config = $ConfigJson | ConvertFrom-Json
        $Result = [ordered]@{{
          session_id = $Config.SessionId
          started_at = (Get-Date).ToString('o')
          mode = 'isolated-shadow-server'
          ok = $false
          production_probe = $null
          shadow = $null
          start = $null
          endpoints = @()
          seed = $null
          files = @()
          cleanup = $null
          error = $null
        }}

        function Add-EndpointResult($Path, $Ok, $Status, $ElapsedMs, $Bytes, $ErrorMessage) {{
          $script:Result.endpoints += [ordered]@{{
            path = $Path
            ok = $Ok
            status = $Status
            elapsed_ms = $ElapsedMs
            bytes = $Bytes
            error = $ErrorMessage
          }}
        }}

        function Test-Endpoint($BaseUrl, $Path, $TimeoutSec) {{
          $sw = [Diagnostics.Stopwatch]::StartNew()
          try {{
            $response = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + $Path) -TimeoutSec $TimeoutSec -ErrorAction Stop
            $sw.Stop()
            $length = 0
            if ($null -ne $response.Content) {{ $length = $response.Content.Length }}
            Add-EndpointResult $Path $true $response.StatusCode $sw.ElapsedMilliseconds $length $null
            return $true
          }} catch {{
            $sw.Stop()
            Add-EndpointResult $Path $false $null $sw.ElapsedMilliseconds 0 $_.Exception.Message
            return $false
          }}
        }}

        $Root = Join-Path $env:TEMP (Join-Path 'HHHostTestbench' $Config.SessionId)
        $ShadowDir = Join-Path $Root 'shadow'
        $AppDataDir = Join-Path $Root 'appdata'
        $LocalAppDataDir = Join-Path $Root 'localappdata'
        $DataDir = Join-Path $AppDataDir 'homework_helper_data'
        $TestProcess = $null

        try {{
          $InstallExe = [string]$Config.Exe
          if (!(Test-Path -LiteralPath $InstallExe)) {{ throw "Installed exe not found: $InstallExe" }}
          $InstallDir = Split-Path -Parent $InstallExe
          $InstallExeName = Split-Path -Leaf $InstallExe
          $ProductionDataDir = Join-Path $env:APPDATA 'HomeworkHelper\homework_helper_data'
          $ProductionDb = Join-Path $ProductionDataDir 'app_data.db'
          $Port8000 = @()
          try {{
            $Port8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
              Select-Object LocalAddress,LocalPort,State,OwningProcess
          }} catch {{
            $Port8000 = @([ordered]@{{ error = $_.Exception.Message }})
          }}
          $Result.production_probe = [ordered]@{{
            installed_exe = $InstallExe
            installed_dir = $InstallDir
            production_data_dir = $ProductionDataDir
            production_db_exists = (Test-Path -LiteralPath $ProductionDb)
            port_8000_listeners = @($Port8000)
          }}

          New-Item -ItemType Directory -Path $ShadowDir,$AppDataDir,$LocalAppDataDir -Force | Out-Null
          Get-ChildItem -LiteralPath $InstallDir -Force | Copy-Item -Destination $ShadowDir -Recurse -Force
          $SourceShadowExe = Join-Path $ShadowDir $InstallExeName
          if (!(Test-Path -LiteralPath $SourceShadowExe)) {{ throw "Shadow exe missing after copy: $SourceShadowExe" }}
          $ShadowExe = Join-Path $ShadowDir ("hh_testbench_" + $Config.SessionId + ".exe")
          Copy-Item -LiteralPath $SourceShadowExe -Destination $ShadowExe -Force
          $Result.shadow = [ordered]@{{
            root = $Root
            exe = $ShadowExe
            appdata = $AppDataDir
            data_dir = $DataDir
            port = [int]$Config.RemotePort
            mutex = ("Local\HomeworkHelperDBServerMutex_" + $Config.SessionId)
          }}

          $psi = New-Object System.Diagnostics.ProcessStartInfo
          $psi.FileName = $ShadowExe
          $psi.Arguments = '--testbench-server'
          $psi.WorkingDirectory = $ShadowDir
          $psi.UseShellExecute = $false
          $psi.CreateNoWindow = $true
          $psi.EnvironmentVariables['HH_TESTBENCH_SESSION_ID'] = [string]$Config.SessionId
          $psi.EnvironmentVariables['HH_TEST_APPDATA_DIR'] = $AppDataDir
          $psi.EnvironmentVariables['HH_SERVER_MUTEX_NAME'] = ("Local\HomeworkHelperDBServerMutex_" + $Config.SessionId)
          $psi.EnvironmentVariables['HH_API_HOST'] = '127.0.0.1'
          $psi.EnvironmentVariables['HH_API_PORT'] = [string]$Config.RemotePort
          $psi.EnvironmentVariables['HH_REMOTE_REQUIRE_AUTH'] = '0'
          $psi.EnvironmentVariables['APPDATA'] = $AppDataDir
          $psi.EnvironmentVariables['LOCALAPPDATA'] = $LocalAppDataDir
          $TestProcess = [Diagnostics.Process]::Start($psi)
          $Result.start = [ordered]@{{ pid = $TestProcess.Id; process_name = $TestProcess.ProcessName }}

          $BaseUrl = 'http://127.0.0.1:' + $Config.RemotePort
          $Ready = $false
          $Deadline = (Get-Date).AddSeconds([int]$Config.ProbeTimeoutSec)
          while ((Get-Date) -lt $Deadline) {{
            try {{
              $ping = Invoke-RestMethod -Uri ($BaseUrl + '/api/gui/ping') -TimeoutSec 2 -ErrorAction Stop
              if ($ping.ok -eq $true) {{ $Ready = $true; break }}
            }} catch {{ Start-Sleep -Milliseconds 500 }}
          }}
          if (-not $Ready) {{ throw "testbench server did not become ready on $BaseUrl" }}

          foreach ($Path in $Config.Endpoints) {{ [void](Test-Endpoint $BaseUrl $Path 8) }}

          $SeedJson = ($Config.SeedProcess | ConvertTo-Json -Compress)
          $seedSw = [Diagnostics.Stopwatch]::StartNew()
          try {{
            $seedResponse = Invoke-RestMethod -Method Post -Uri ($BaseUrl + '/processes') -ContentType 'application/json' -Body $SeedJson -TimeoutSec 8 -ErrorAction Stop
            $seedSw.Stop()
            $Result.seed = [ordered]@{{ ok = $true; elapsed_ms = $seedSw.ElapsedMilliseconds; id = $seedResponse.id; name = $seedResponse.name }}
          }} catch {{
            $seedSw.Stop()
            $Result.seed = [ordered]@{{ ok = $false; elapsed_ms = $seedSw.ElapsedMilliseconds; error = $_.Exception.Message }}
          }}

          foreach ($Name in 'app_data.db','app_data.db-wal','app_data.db-shm','db_server.log','db_server.pid','db_server_meta.json') {{
            $File = Join-Path $DataDir $Name
            if (Test-Path -LiteralPath $File) {{
              $Item = Get-Item -LiteralPath $File
              $Hash = Get-FileHash -LiteralPath $File -Algorithm SHA256
              $Result.files += [ordered]@{{ name = $Name; length = $Item.Length; sha256 = $Hash.Hash; last_write_time = $Item.LastWriteTime.ToString('o') }}
            }} else {{
              $Result.files += [ordered]@{{ name = $Name; missing = $true }}
            }}
          }}

          $Result.ok = (($Result.endpoints | Where-Object {{ $_.ok -eq $false }}).Count -eq 0) -and ($Result.seed.ok -eq $true)
        }} catch {{
          $Result.error = [ordered]@{{ message = $_.Exception.Message; type = $_.Exception.GetType().FullName }}
        }} finally {{
          if ($null -ne $TestProcess) {{
            try {{
              if (-not $TestProcess.HasExited) {{
                $TestProcess.CloseMainWindow() | Out-Null
                if (-not $TestProcess.WaitForExit(3000)) {{ $TestProcess.Kill(); $TestProcess.WaitForExit(5000) | Out-Null }}
              }}
              $Result.stop = [ordered]@{{ pid = $TestProcess.Id; exited = $TestProcess.HasExited }}
            }} catch {{
              $Result.stop = [ordered]@{{ pid = $TestProcess.Id; error = $_.Exception.Message }}
            }}
          }}

          if ([bool]$Config.KeepRemote) {{
            $Result.cleanup = [ordered]@{{ kept = $true; root = $Root }}
          }} else {{
            try {{
              if (Test-Path -LiteralPath $Root) {{ Remove-Item -LiteralPath $Root -Recurse -Force }}
              $Result.cleanup = [ordered]@{{ kept = $false; removed = $true; root = $Root }}
            }} catch {{
              $Result.cleanup = [ordered]@{{ kept = $false; removed = $false; root = $Root; error = $_.Exception.Message }}
            }}
          }}
          $Result.finished_at = (Get-Date).ToString('o')
          $Result | ConvertTo-Json -Depth 12
        }}
        """
    ).strip() + "\n"


def planned_actions(config: TestbenchConfig) -> list[str]:
    return [
        f"Create remote temp root %TEMP%\\HHHostTestbench\\{config.session_id}",
        f"Shadow-copy the installed package from {config.exe}",
        f"Run renamed executable hh_testbench_{config.session_id}.exe --testbench-server",
        f"Set isolated env: HH_TEST_APPDATA_DIR, HH_SERVER_MUTEX_NAME, HH_API_PORT={config.remote_port}, APPDATA, LOCALAPPDATA",
        "Probe loopback logic endpoints without launching games or power actions",
        "Seed one sample managed_process row in the disposable SQLite DB",
        "Collect endpoint timings, test DB file hashes, log/pid/meta summaries",
        "Stop only the started testbench PID",
        "Remove the remote temp root unless --keep-remote is set",
    ]


def build_summary(
    *,
    ssh: SSHConfig | None,
    testbench: TestbenchConfig,
    mode: str,
    dry_run: bool,
    remote_result: dict[str, Any] | None = None,
    ssh_returncode: int | None = None,
    ssh_stderr: str | None = None,
) -> dict[str, Any]:
    return {
        "session_id": testbench.session_id,
        "mode": mode,
        "dry_run": dry_run,
        "created_at": dt.datetime.now().isoformat(),
        "ssh_target": None if ssh is None else {"host": ssh.host, "user": ssh.user, "port": ssh.port, "identity": ssh.identity},
        "testbench": {
            "installed_exe": testbench.exe,
            "remote_port": testbench.remote_port,
            "keep_remote": testbench.keep_remote,
            "timeout": testbench.timeout,
        },
        "safety_rules": PRODUCTION_SAFETY_RULES,
        "manual_test_items": MANUAL_TEST_ITEMS,
        "planned_actions": planned_actions(testbench),
        "remote_result": remote_result,
        "ssh_returncode": ssh_returncode,
        "ssh_stderr_tail": (ssh_stderr or "")[-4000:] if ssh_stderr else "",
    }


def write_reports(summary: dict[str, Any], artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary_path = artifact_dir / "summary.json"
    report_path = artifact_dir / "report.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    remote = summary.get("remote_result") or {}
    endpoints = remote.get("endpoints") or []
    endpoint_lines = "\n".join(
        f"| `{item.get('path')}` | {item.get('ok')} | {item.get('status') or ''} | {item.get('elapsed_ms') or ''} | {item.get('error') or ''} |"
        for item in endpoints
    ) or "| _not run_ |  |  |  |  |"
    manual_lines = "\n".join(f"- {item}" for item in summary["manual_test_items"])
    safety_lines = "\n".join(f"- {item}" for item in summary["safety_rules"])
    action_lines = "\n".join(f"{idx + 1}. {item}" for idx, item in enumerate(summary["planned_actions"]))

    report = f"""# SSH Host Testbench Report

Session: `{summary['session_id']}`
Mode: `{summary['mode']}`
Dry run: `{summary['dry_run']}`
Created: `{summary['created_at']}`

## Result

- Remote ok: `{remote.get('ok') if remote else None}`
- SSH return code: `{summary.get('ssh_returncode')}`
- Remote error: `{(remote.get('error') or {}).get('message') if isinstance(remote.get('error'), dict) else remote.get('error')}`
- Cleanup: `{remote.get('cleanup') if remote else None}`

## Endpoint timings

| Path | OK | Status | Elapsed ms | Error |
| --- | --- | --- | ---: | --- |
{endpoint_lines}

## Safety rules

{safety_lines}

## Planned/actual action sequence

{action_lines}

## Manual-only test items

These items are intentionally excluded from the SSH testbench and must be checked by the user after package update when needed.

{manual_lines}
"""
    report_path.write_text(report, encoding="utf-8")


def parse_remote_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("remote command produced no stdout")
    # PowerShell or imported modules can print incidental lines.  The final line
    # is expected to be the ConvertTo-Json payload from the finally block.
    for start in (text.rfind("\n{"), text.find("{")):
        if start == -1:
            continue
        candidate = text[start + 1 :] if text[start] == "\n" else text[start:]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"could not parse remote JSON stdout tail: {text[-500:]}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an isolated HomeworkHelper Windows host testbench over SSH.")
    parser.add_argument("--host", help="SSH host or MagicDNS/Tailscale address. Required unless --dry-run with a placeholder is acceptable.")
    parser.add_argument("--user", help="SSH username. Omit if --host already contains user@host.")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port (default: 22).")
    parser.add_argument("--identity", help="SSH private key path.")
    parser.add_argument("--exe", default=DEFAULT_EXE, help=f"Installed host exe path (default: {DEFAULT_EXE}).")
    parser.add_argument("--session-id", default=default_session_id(), help="Stable session id for the remote temp root.")
    parser.add_argument("--remote-port", type=int, default=default_remote_port(), help="Loopback API port for the testbench server.")
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT, help="Local artifact root for reports.")
    parser.add_argument("--timeout", type=int, default=45, help="Remote probe timeout in seconds.")
    parser.add_argument("--keep-remote", action="store_true", help="Keep the remote temp test root for manual forensics.")
    parser.add_argument("--dry-run", action="store_true", help="Write a local plan/report without connecting over SSH.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    session_id = _safe_token(args.session_id)
    artifact_dir = args.artifact_root / session_id
    testbench = TestbenchConfig(
        session_id=session_id,
        exe=args.exe,
        remote_port=args.remote_port,
        keep_remote=args.keep_remote,
        timeout=args.timeout,
        artifact_dir=artifact_dir,
    )
    ssh = SSHConfig(host=args.host or "<host>", user=args.user, port=args.ssh_port, identity=args.identity)

    if args.dry_run:
        summary = build_summary(ssh=ssh, testbench=testbench, mode="dry-run", dry_run=True)
        summary["remote_script_preview"] = build_remote_script(testbench)[:6000]
        write_reports(summary, artifact_dir)
        print(json.dumps({"ok": True, "dry_run": True, "session_id": session_id, "artifact_dir": str(artifact_dir)}, ensure_ascii=False))
        return 0

    if not args.host:
        print("--host is required for a real SSH testbench run", file=sys.stderr)
        return 2

    script = build_remote_script(testbench)
    completed = run_remote_powershell(ssh, script, timeout=max(args.timeout + 90, 120))
    remote_result: dict[str, Any] | None = None
    parse_error: str | None = None
    if completed.stdout:
        try:
            remote_result = parse_remote_json(completed.stdout)
        except Exception as exc:  # pragma: no cover - exercised with real SSH failures.
            parse_error = str(exc)
    if remote_result is None:
        remote_result = {"ok": False, "error": {"message": parse_error or "remote result missing"}, "stdout_tail": completed.stdout[-4000:]}

    summary = build_summary(
        ssh=ssh,
        testbench=testbench,
        mode="isolated-shadow-server",
        dry_run=False,
        remote_result=remote_result,
        ssh_returncode=completed.returncode,
        ssh_stderr=completed.stderr,
    )
    write_reports(summary, artifact_dir)
    print(json.dumps({"ok": bool(remote_result.get("ok")) and completed.returncode == 0, "session_id": session_id, "artifact_dir": str(artifact_dir)}, ensure_ascii=False))
    return 0 if bool(remote_result.get("ok")) and completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
