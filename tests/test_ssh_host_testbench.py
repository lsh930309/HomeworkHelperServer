import base64
import json
import subprocess
from pathlib import Path

from tools import ssh_host_testbench as tb


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
