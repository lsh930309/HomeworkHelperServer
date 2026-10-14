import base64
import json
import subprocess
from pathlib import Path

import pytest

from src.core.tailscale import TailscalePeer, TailscaleSnapshot

from tools import ssh_host_testbench as tb


@pytest.fixture
def tailscale_peer_snapshot(monkeypatch):
    peer = TailscalePeer("LSH_Desktop", "lsh-desktop.example.ts.net.", ("100.64.0.42", "fd7a:115c:a1e0::42"), True, "windows")
    snapshot = TailscaleSnapshot(True, True, "Running", ("100.64.0.1",), "Mac", (peer,), "ready")
    calls = []
    monkeypatch.setattr(tb, "tailscale_status", lambda: calls.append("status") or snapshot)
    return snapshot, calls


@pytest.mark.parametrize("name", ["lsh-desktop", "LSH-DESKTOP", "LSH_Desktop", "lsh-desktop.example.ts.net", "LSH-DESKTOP.EXAMPLE.TS.NET."])
def test_named_ssh_uses_exact_tailscale_peer_before_dns(monkeypatch, tailscale_peer_snapshot, name):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: pytest.fail("OS DNS must not be needed"))
    captured = []
    monkeypatch.setattr(tb.subprocess, "run", lambda command, **kwargs: captured.append(command) or subprocess.CompletedProcess(command, 0, '{}', ''))
    result = tb.run_remote_powershell(tb.SSHConfig(name, "tester", 2222, "/isolated/key"), "Write-Output '{}';", timeout=10)
    command = captured[0]
    assert result.returncode == 0
    assert "HostName=100.64.0.42" in command
    assert "tester@" + name in command
    assert command[command.index("-p") + 1] == "2222"
    assert command[command.index("-i") + 1] == "/isolated/key"
    assert "BatchMode=yes" in command and "ConnectTimeout=8" in command
    assert not any("StrictHostKeyChecking" in argument or "UserKnownHostsFile" in argument for argument in command)
    assert len(captured) == 1 and tailscale_peer_snapshot[1] == ["status"]


@pytest.mark.parametrize("host", ["100.64.0.42", "fd7a:115c:a1e0::42"])
def test_literal_ip_keeps_existing_ssh_and_needs_no_tailscale(monkeypatch, host):
    monkeypatch.setattr(tb, "tailscale_status", lambda: pytest.fail("Literal IP must not query Tailscale"))
    command = tb._ssh_args(tb.SSHConfig(host, "tester", 22, None))
    assert command[-1] == "tester@" + host
    assert not any(argument.startswith("HostName=") for argument in command)


@pytest.mark.parametrize("host", ["tester@100.64.0.42", "tester@fd7a:115c:a1e0::42", "tester@server.example.org"])
def test_embedded_user_and_external_fqdn_keep_existing_ssh_target(monkeypatch, host):
    monkeypatch.setattr(tb, "tailscale_status", lambda: pytest.fail("Explicit IP/external DNS must not query Tailscale"))
    command = tb._ssh_args(tb.SSHConfig(host, None, 22, None))
    assert command[-1] == host
    assert not any(argument.startswith("HostName=") for argument in command)


def test_embedded_user_keeps_named_tailscale_address_resolution(tailscale_peer_snapshot):
    command = tb._ssh_args(tb.SSHConfig("tester@lsh-desktop", None, 22, None))
    assert command[-1] == "tester@lsh-desktop" and "HostName=100.64.0.42" in command


def test_named_ssh_can_use_ipv6_without_an_ipv4(monkeypatch, tailscale_peer_snapshot):
    from dataclasses import replace
    snapshot, _calls = tailscale_peer_snapshot
    peer = replace(snapshot.peers[0], ips=("fd7a:115c:a1e0::42",))
    monkeypatch.setattr(tb, "tailscale_status", lambda: replace(snapshot, peers=(peer,)))
    assert "HostName=fd7a:115c:a1e0::42" in tb._ssh_args(tb.SSHConfig("lsh-desktop", None, 22, None))


@pytest.mark.parametrize("condition", ["missing", "substring", "duplicate", "no_address", "stopped"])
def test_named_ssh_does_not_choose_another_host_or_send_on_invalid_selection(monkeypatch, tailscale_peer_snapshot, condition):
    from dataclasses import replace
    snapshot, _calls = tailscale_peer_snapshot
    peer = snapshot.peers[0]
    if condition == "missing":
        snapshot = replace(snapshot, peers=())
    elif condition == "substring":
        snapshot = replace(snapshot, peers=(replace(peer, hostname="lsh-desktop-extra", dns_name="lsh-desktop-extra.example.ts.net."),))
    elif condition == "duplicate":
        snapshot = replace(snapshot, peers=(peer, replace(peer, online=False, ips=("100.64.0.43",))))
    elif condition == "no_address":
        snapshot = replace(snapshot, peers=(replace(peer, ips=()),))
    else:
        snapshot = replace(snapshot, running=False, backend_state="Stopped", message="Tailscale stopped")
    monkeypatch.setattr(tb, "tailscale_status", lambda: snapshot)
    monkeypatch.setattr(tb.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("SSH must not run"))
    with pytest.raises(ValueError, match="Tailscale|연결 주소"):
        tb.run_remote_powershell(tb.SSHConfig("lsh-desktop", "tester", 22, None), "must not run", timeout=10)


def test_offline_named_peer_is_not_replaced_by_an_online_host(monkeypatch, tailscale_peer_snapshot):
    from dataclasses import replace
    snapshot, _calls = tailscale_peer_snapshot
    target = replace(snapshot.peers[0], online=False)
    other = TailscalePeer("Other", "other.example.ts.net.", ("100.64.0.99",), True, "windows")
    monkeypatch.setattr(tb, "tailscale_status", lambda: replace(snapshot, peers=(target, other)))
    calls = []
    def denied(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 255, "", "Permission denied")
    monkeypatch.setattr(tb.subprocess, "run", denied)
    result = tb.run_remote_powershell(tb.SSHConfig("lsh-desktop", "tester", 22, None), "must not run", timeout=10)
    assert result.returncode == 255
    assert len(calls) == 1 and "HostName=100.64.0.42" in calls[0]
    assert "HostName=100.64.0.99" not in calls[0]


def test_named_dry_run_does_not_resolve_or_connect(monkeypatch, tmp_path):
    monkeypatch.setattr(tb, "tailscale_status", lambda: pytest.fail("Dry run must not query Tailscale"))
    monkeypatch.setattr(tb.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("Dry run must not connect"))
    assert tb.main(["--host", "lsh-desktop", "--dry-run", "--artifact-root", str(tmp_path), "--session-id", "dry"]) == 0


def test_unresolved_testbench_has_a_failure_report_without_remote_actions(monkeypatch, tailscale_peer_snapshot, tmp_path, capsys):
    monkeypatch.setattr(tb.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("SSH must not run"))
    assert tb.main(["--host", "unknown", "--artifact-root", str(tmp_path), "--session-id", "missing"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert not result["ok"] and "0개" in result["error"]
    summary = json.loads((tmp_path / "missing/summary.json").read_text(encoding="utf-8"))
    assert summary["ssh_returncode"] is None and not summary["remote_result"]["ok"]


def test_remote_runner_sends_one_program_with_strict_utf8(monkeypatch):
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 1, '', 'blocked')
    monkeypatch.setattr(tb.subprocess, 'run', run)
    result = tb.run_remote_powershell(
        tb.SSHConfig('100.64.0.1', 'tester', 22, None),
        "throw '준비 실패'\nWrite-Output 'must not continue'", timeout=10,
    )
    assert result.returncode == 1
    program = base64.b64decode(captured['command'][-1]).decode('utf-16-le')
    assert captured['command'][-2] == '-EncodedCommand'
    assert '[scriptblock]::Create([Console]::In.ReadToEnd())' in program
    assert captured['kwargs']['input'] == "throw '준비 실패'\nWrite-Output 'must not continue'"
    assert '$ErrorActionPreference = \'Stop\'' in program
    assert 'exit 1' in program
    assert captured['kwargs']['encoding'] == 'utf-8'
    assert captured['kwargs']['errors'] == 'strict'
    assert 'shell' not in captured['kwargs']


def test_large_remote_program_stays_in_stdin(monkeypatch):
    captured = {}
    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(tb.subprocess, 'run', run)
    script = "Write-Output '한글'\n" * 2000
    tb.run_remote_powershell(tb.SSHConfig('100.64.0.1', 'tester', 22, None), script, timeout=10)
    assert captured['kwargs']['input'] == script
    assert len(captured['command'][-1]) < 4096


def test_dry_run_writes_agent_report_and_manual_exclusions(tmp_path, capsys):
    artifact_root = tmp_path / "artifacts"

    rc = tb.main(
        [
            "--dry-run",
            "--host",
            "100.64.0.1",
            "--user",
            "tester",
            "--identity",
            str(tmp_path / "id_ed25519"),
            "--session-id",
            "case-1",
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    summary_path = artifact_root / "case-1" / "summary.json"
    report_path = artifact_root / "case-1" / "report.md"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")

    assert summary["dry_run"] is True
    assert summary["ssh_target"]["host"] == "100.64.0.1"
    assert "Run a renamed shadow executable" in summary["safety_rules"][0]
    assert "Registry modification" in report
    assert "Manual-only test items" in report
    assert "hh_testbench_case-1.exe --testbench-server" in report


def test_remote_script_isolated_from_production_process_and_paths(tmp_path):
    config = tb.TestbenchConfig(
        session_id="case-2",
        exe=r"C:\Program Files\HomeworkHelper\homework_helper.exe",
        remote_port=19432,
        keep_remote=False,
        timeout=30,
        artifact_dir=Path("unused"),
    )

    script = tb.build_remote_script(config)

    assert "hh_testbench_" in script
    assert "--testbench-server" in script
    assert "HH_TEST_APPDATA_DIR" in script
    assert "HH_SERVER_MUTEX_NAME" in script
    assert "HH_API_PORT" in script
    assert "APPDATA" in script
    assert "LOCALAPPDATA" in script
    assert "Remove-Item -LiteralPath $Root -Recurse -Force" in script
    assert "Stop-Process -Name" not in script
    assert "taskkill" not in script.lower()
    assert "Remove-Item -LiteralPath $Production" not in script


def test_remote_script_exercises_logic_endpoints_without_manual_only_actions():
    config = tb.TestbenchConfig(
        session_id="case-3",
        exe=tb.DEFAULT_EXE,
        remote_port=19001,
        keep_remote=False,
        timeout=30,
        artifact_dir=Path("unused"),
    )

    script = tb.build_remote_script(config)

    for endpoint in ["/api/gui/health", "/remote/status", "/remote/readiness", "/processes", "/settings"]:
        assert endpoint in script
    assert "preferred_launch_type" in script
    assert "/remote/processes/" not in script
    assert "/launch" not in script
    assert "shutdown" not in script.lower()
    assert "restart-computer" not in script.lower()
