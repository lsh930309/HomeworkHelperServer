"""Operational contracts with disposable Git/DB/package data; no live host mutations."""
import base64
from copy import deepcopy
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import zipfile

import pytest

from tools import host_operations as ops
from tools import ssh_host_testbench as transport
from tools import windows_host_probe as probe
from src.core.tailscale import TailscalePeer, TailscaleSnapshot


@pytest.mark.parametrize("scenario", ["spotify-window-observe", "spotify-window-open", "spotify-window-minimize", "spotify-window-close", "spotify-window-startup"])
def test_spotify_window_observation_is_a_fixed_media_scenario(scenario):
    args = ops.parser().parse_args(["media-qa", "--host", "test.invalid", "--scenario", scenario])
    assert args.scenario == scenario
    session_source = (ops.ROOT / "tools/windows_session_probe.py").read_text(encoding="utf-8")
    assert f'"{scenario}"' in session_source


@pytest.fixture
def published_repository(tmp_path, monkeypatch):
    repo, remote = tmp_path / "repo", tmp_path / "remote.git"
    repo.mkdir()
    def command(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    command("init", "-q", "-b", "main")
    command("config", "user.name", "Isolated Test")
    command("config", "user.email", "test@example.invalid")
    (repo / "file.txt").write_text("test")
    command("add", ".")
    command("commit", "-qm", "fixture")
    command("init", "--bare", "-q", str(remote))
    command("remote", "add", "origin", str(remote))
    monkeypatch.setattr(ops, "ROOT", repo)
    return repo, command


def test_unpublished_commit_cannot_prepare_build_or_install(published_repository):
    _, command = published_repository
    with pytest.raises(ValueError, match="공개되지"):
        ops.published_commit(None)
    command("push", "-q", "origin", "main")
    assert ops.published_commit(None) == (command("rev-parse", "HEAD"), "main")


def test_dirty_or_different_commit_cannot_deploy(published_repository):
    repo, command = published_repository
    command("push", "-q", "origin", "main")
    before = command("rev-parse", "HEAD")
    (repo / "file.txt").write_text("changed")
    with pytest.raises(ValueError, match="커밋한 뒤"):
        ops.published_commit(None)
    command("commit", "-am", "second fixture")
    with pytest.raises(ValueError, match="HEAD와 다릅니다"):
        ops.published_commit(before)


def test_inspect_never_requests_publication_or_host_changes(monkeypatch, tmp_path, capsys):
    captured = {}
    def remote(config, script, *, timeout):
        captured["script"] = script
        return subprocess.CompletedProcess([], 0, '{"api":{"health":{"error":"URLError"}}}', '')
    monkeypatch.setattr(ops, "run_remote_powershell", remote)
    monkeypatch.setattr(ops, "published_commit", lambda _: pytest.fail("inspect must not publish"))
    monkeypatch.setattr(ops, "source_state", lambda: {"published_head": None})
    assert ops.main(["inspect", "--host", "test.invalid",
                     "--report-root", str(tmp_path)]) == 0
    assert "-Command 'inspect'" in captured["script"]
    assert "-Repo 'C:\\VSCode\\Projects\\HomeworkHelperServer'" in captured["script"]
    assert json.loads(capsys.readouterr().out)["result"]["api"]["health"]["error"] == "URLError"


def test_archived_install_selects_original_package_without_source_publication(monkeypatch, tmp_path, capsys):
    calls = []
    monkeypatch.setattr(ops, "published_commit", lambda _: pytest.fail("archived package must not require current source"))
    def remote(config, script, *, timeout):
        calls.append(script)
        return subprocess.CompletedProcess([], 0, '{"ok":true,"release":"v1.4.0_b4_gfb92714"}', '')
    monkeypatch.setattr(ops, "run_remote_powershell", remote)
    assert ops.main(["install", "--host", "test.invalid", "--archived-release", "v1.4.0_b4_gfb92714",
                     "--report-root", str(tmp_path)]) == 0
    assert "-ArchivedRelease 'v1.4.0_b4_gfb92714'" in calls[0]
    result = json.loads(capsys.readouterr().out)
    assert result["commit"] is None and result["result"]["release"] == "v1.4.0_b4_gfb92714"


@pytest.mark.parametrize("arguments", [
    ["inspect", "--archived-release", "v1.4.0_b4_gfb92714"],
    ["install", "--archived-release", "v1.4.0_b4_gfb92714", "--commit", "fb92714"],
])
def test_archived_selection_rejects_conflicting_operation_before_ssh(monkeypatch, tmp_path, arguments):
    monkeypatch.setattr(ops, "run_remote_powershell", lambda *a, **kw: pytest.fail("must reject before SSH"))
    with pytest.raises(SystemExit) as error:
        ops.main(arguments + ["--host", "test.invalid", "--report-root", str(tmp_path)])
    assert error.value.code == 2 and not list(tmp_path.iterdir())


def test_named_inspect_uses_shared_peer_address_without_a_failed_first_ssh(monkeypatch, tmp_path, capsys):
    peer = TailscalePeer("LSH_Desktop", "lsh-desktop.example.ts.net.", ("100.64.0.42",), True, "windows")
    snapshot = TailscaleSnapshot(True, True, "Running", ("100.64.0.1",), "Mac", (peer,), "ready")
    monkeypatch.setattr(transport, "tailscale_status", lambda: snapshot)
    monkeypatch.setattr(ops, "source_state", lambda: {})
    calls = []
    def connected(command, **kwargs):
        calls.append(command)
        assert "HostName=100.64.0.42" in command
        assert "tester@lsh-desktop" in command
        assert "-Command 'inspect'" in kwargs["input"]
        return subprocess.CompletedProcess(command, 0, '{"computer":"LSH_DESKTOP"}', '')
    monkeypatch.setattr(transport.subprocess, "run", connected)
    assert ops.main(["inspect", "--host", "lsh-desktop", "--user", "tester", "--report-root", str(tmp_path)]) == 0
    assert len(calls) == 1 and json.loads(capsys.readouterr().out)["ok"]


def test_missing_named_peer_records_failure_before_ssh(monkeypatch, tmp_path, capsys):
    snapshot = TailscaleSnapshot(True, True, "Running", ("100.64.0.1",), "Mac", (), "ready")
    monkeypatch.setattr(transport, "tailscale_status", lambda: snapshot)
    monkeypatch.setattr(transport.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("No SSH or host changes"))
    assert ops.main(["inspect", "--host", "lsh-desktop", "--report-root", str(tmp_path)]) == 1
    result = json.loads(capsys.readouterr().err)
    assert not result["ok"] and "0개" in result["error"]
    assert not json.loads(next(tmp_path.glob("*/result.json")).read_text(encoding="utf-8"))["ok"]


def test_remote_failure_is_recorded_without_a_followup_mutation(monkeypatch, tmp_path, capsys):
    calls = []
    def remote(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 1, "", "준비 실패")
    monkeypatch.setattr(ops, "run_remote_powershell", remote)
    monkeypatch.setattr(ops, "source_state", lambda: {})
    assert ops.main(["inspect", "--host", "test.invalid",
                     "--report-root", str(tmp_path)]) == 1
    assert len(calls) == 1
    assert "준비 실패" in capsys.readouterr().err


@pytest.mark.parametrize("stdout,stderr", [
    (None, None),
    ("한글 출력", "진단 오류"),
    ("한글 출력".encode("utf-8"), "진단 오류".encode("utf-8")),
    (b"partial UTF-8: \xed\x95", b"error: \xec"),
])
def test_transport_timeout_has_a_failure_report_and_is_not_retried(monkeypatch, tmp_path, capsys, stdout, stderr):
    calls = []
    def remote(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(["ssh"], 20, output=stdout, stderr=stderr)
    monkeypatch.setattr(ops, "run_remote_powershell", remote)
    assert ops.main(["logs", "--host", "test.invalid",
                     "--report-root", str(tmp_path)]) == 1
    report = next(tmp_path.glob("*/result.json"))
    assert json.loads(report.read_text())["error"] == "SSH 작업 응답 시간 초과"
    for name, captured in (("stdout.log", stdout), ("stderr.log", stderr)):
        expected = captured.encode("utf-8") if isinstance(captured, str) else captured or b""
        assert (report.parent / name).read_bytes() == expected
    assert len(calls) == 1


@pytest.mark.parametrize("command", ["prepare-source", "build", "install"])
def test_update_cannot_select_a_temporary_or_alternative_checkout(command, monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "run_remote_powershell", lambda *a, **kw: pytest.fail("must reject before SSH"))
    with pytest.raises(SystemExit) as error:
        ops.main([command, "--host", "test.invalid", "--repo", r"C:\Temp\candidate",
                  "--report-root", str(tmp_path)])
    assert error.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("abbreviation", [4, 7, 12])
def test_install_release_selection_matches_builder_despite_git_abbreviation(published_repository, monkeypatch, capsys, abbreviation):
    import build
    repo, command = published_repository
    command("config", "core.abbrev", str(abbreviation))
    version = repo / "build.version.json"
    version.write_text('{"schema":1,"targets":{"windows-host":{"version":"1.4.0","build":3}}}')
    (repo / ".gitignore").write_text("release/\n")
    command("add", "build.version.json", ".gitignore")
    command("commit", "-qm", "version fixture")
    monkeypatch.setattr(build, "PROJECT_ROOT", repo)
    monkeypatch.setenv("APPDATA", str(repo / "isolated-appdata"))
    expected = "v1.4.0_b3_g" + command("rev-parse", "--short=7", "HEAD")
    package = repo / "release" / ("HomeworkHelper_" + expected + "_Setup.exe")
    package.parent.mkdir()
    package.write_bytes(b"inert package fixture")

    assert probe.main(["release", "--repo", str(repo), "--appdata", str(repo / "isolated-appdata"),
                       "--install", str(repo / "installed")]) == 0
    selected = json.loads(capsys.readouterr().out)["release_id"]
    assert (repo / "release" / ("HomeworkHelper_" + selected + "_Setup.exe")) == package
    source = (Path(__file__).parents[1] / "tools/windows_host_operations.ps1").read_text(encoding="utf-8")
    assert "$Release = (Invoke-Probe 'release').release_id" in source
    assert "Git-Checked @('rev-parse','--short'" not in source


def test_missing_db_is_not_created(tmp_path):
    db = tmp_path / "app_data.db"
    assert probe.database_state(db)["reason"] == "database_missing"
    assert not list(tmp_path.iterdir())


def test_database_observation_preserves_data_and_omits_credentials(tmp_path):
    db = tmp_path / "app_data.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE global_settings(run_on_startup INTEGER,obs_exe_path TEXT,obs_password TEXT,token TEXT)")
        connection.execute("INSERT INTO global_settings VALUES(1,'OBS','private-password','private-token')")
        connection.execute("CREATE TABLE process_sessions(id INTEGER,process_id TEXT,start_timestamp REAL,end_timestamp REAL)")
        connection.execute("INSERT INTO process_sessions VALUES(1,'game',10,NULL)")
    before = db.read_bytes()
    state = probe.database_state(db)
    assert state["open_sessions"] == [{"id": 1, "process_id": "game", "start_timestamp": 10.0}]
    assert state["settings"] == {"run_on_startup": 1, "obs_exe_path": "OBS"}
    assert "private" not in json.dumps(state)
    assert db.read_bytes() == before


def test_corrupt_database_is_reported_and_preserved(tmp_path):
    db = tmp_path / "app_data.db"
    db.write_bytes(b"broken database")
    assert probe.database_state(db)["available"] is False
    assert db.read_bytes() == b"broken database"


def test_log_collection_is_bounded_redacted_and_does_not_initialize_db(tmp_path):
    path = tmp_path / "HomeworkHelper/homework_helper_data/gui.log"
    path.parent.mkdir(parents=True)
    path.write_text("ignore\n감시 token=private-one\n감시 password='private-two'\n", encoding="utf-8")
    before = path.read_bytes()
    result = probe.gui_log(ops.ROOT, tmp_path, 1, "감시")
    assert result["lines"] == ["감시 password=[REDACTED]"]
    assert path.read_bytes() == before
    assert not (path.parent / "app_data.db").exists()


def idle_snapshot():
    return {"database": {"available": True, "open_sessions": []}, "api": {"health": {
        "ok": True, "db_ready": True, "mode": "normal"}}, "obs": {"running": False}, "processes": []}


@pytest.mark.parametrize("change", [
    {"database": {"available": False}},
    {"database": {"available": True, "open_sessions": [{"id": 1}]}},
    {"api": {"health": {"ok": True, "db_ready": False, "mode": "normal"}}},
    {"api": {"health": {"ok": True, "db_ready": True, "mode": "blocked"}}},
    {"obs": {"running": True, "outputs": {}}},
    {"obs": {"running": True, "outputs": {"GetRecordStatus": True}}},
    {"processes": [{"error": "AccessDenied"}]},
])
def test_usage_or_unknown_state_blocks_install(change):
    state = idle_snapshot()
    state.update(change)
    with pytest.raises(ValueError):
        probe.require_idle(state)


def test_no_obs_or_confirmed_idle_obs_allows_install_preflight():
    state = idle_snapshot()
    probe.require_idle(state)
    state["obs"] = {"running": True, "outputs": {"GetRecordStatus": False}}
    probe.require_idle(state)


def test_package_requires_both_unique_executables(tmp_path):
    path = tmp_path / "portable.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("app/homework_helper.exe", b"host")
        archive.writestr("app/homework_helper_service.exe", b"service")
    assert probe.payload_hashes(path)["homework_helper.exe"] == hashlib.sha256(b"host").hexdigest()
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("other/homework_helper.exe", b"ambiguous")
    with pytest.raises(ValueError, match="ambiguous"):
        probe.payload_hashes(path)


def test_build_invokes_single_authoritative_builder(monkeypatch, tmp_path, capsys):
    calls = []
    monkeypatch.setenv("APPDATA", str(tmp_path / "data"))
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    assert probe.main(["build", "--repo", str(tmp_path), "--appdata", str(tmp_path / "data"),
                       "--install", str(tmp_path / "installed"), "--bump", "none"]) == 0
    assert calls[0][0][1:] == ["build.py", "--no-gui", "--no-prune-archives", "--bump", "none"]
    assert len(calls) == 1


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows PowerShell required")
@pytest.mark.parametrize("failure,expected", [
    ("dirty", []), ("source", []), ("release", ["release"]), ("signature", ["release"]),
    ("payload", ["release", "payload"]), ("preflight", ["release", "payload", "preflight"]),
    ("backup", ["release", "payload", "preflight", "backup"]),
    ("quit", ["release", "payload", "preflight", "backup", "preflight", "quit"]),
    ("setup", ["release", "payload", "preflight", "backup", "preflight", "quit", "setup"]),
    ("service-account", ["release", "payload", "preflight", "backup", "preflight", "quit", "setup"]),
    ("none", ["release", "payload", "preflight", "backup", "preflight", "quit", "setup", "start", "inspect"]),
    ("archive-missing", []), ("archive-duplicate", []), ("archive-invalid", []),
    ("archive-ok", ["payload", "preflight", "backup", "preflight", "quit", "setup", "start", "inspect"]),
])
def test_windows_install_stops_before_mutation_on_preparation_failure(tmp_path, failure, expected):
    # Full PowerShell workflow, OS calls mocked in this disposable process only.
    # No production executable, DB, service or scheduled task is invoked.
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    python = repo / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    (repo / "build.version.json").write_text('{"targets":{"windows-host":{"version":"1.0.0","build":1}}}')
    archived_release = "v1.0.0_b1_gabc1234"
    if failure in {"archive-ok", "archive-duplicate"}:
        for folder in (["one", "two"] if failure == "archive-duplicate" else ["one"]):
            archive = repo / "release/archives/windows-host" / folder
            archive.mkdir(parents=True)
            for suffix in ("Setup.exe", "Portable.zip"):
                (archive / f"HomeworkHelper_{archived_release}_{suffix}").write_bytes(b"inert fixture")
    elif failure.startswith("archive-"):
        (repo / "release/archives/windows-host").mkdir(parents=True)
    source = (ops.ROOT / "tools/windows_host_operations.ps1").read_text(encoding="utf-8")
    stubs = r'''
function Git-Checked($Arguments) {
 if ($Arguments[0] -eq 'status') {if ($global:Failure -in @('dirty','archive-ok')) {return 'M changed'}; return ''}
 if ($global:Failure -eq 'source') {return 'other'}; return 'commit'
}
function Require-InstallTime {}
function Get-AuthenticodeSignature {if ($global:Failure -eq 'signature') {return @{Status='NotSigned'}}; return @{Status='Valid'}}
function Invoke-Probe($Kind,$Portable) {
 $global:Events.Add($Kind)
 if ($Kind -eq $global:Failure) {throw ('expected '+$Kind+' failure')}
 if ($Kind -eq 'release') {return @{release_id='v1.0.0_b1_gabc1234'}}
 if ($Kind -eq 'payload') {return @{'homework_helper.exe'='expected';'homework_helper_service.exe'='expected'}}
 if ($Kind -eq 'backup') {return @{backup='fixture'}}
 $Processes=@()
 if ($Kind -eq 'inspect') {$Processes=@(@{path='C:\Program Files\HomeworkHelper\homework_helper.exe';sid=$Sid;session=1;elevated=$false})}
 return [pscustomobject]@{processes=$Processes;database=@{settings=@{run_on_startup=1}}}
}
function Service-Status {return @{owner_sid=$Sid;user_session_ready=$true;user_sessions=@(@{owner_sid=$Sid;session_id=1})}}
function Start-Process($FilePath,$ArgumentList,[switch]$Wait,[switch]$PassThru) {
 $Stage=if ($FilePath.EndsWith('_Setup.exe')) {'setup'} else {'quit'}
 $global:Events.Add($Stage);return @{ExitCode=$(if ($global:Failure -eq $Stage) {1} else {0})}
}
function Get-CimInstance($ClassName) {
 if ($ClassName -eq 'Win32_Service') {return @{StartName=$(if ($global:Failure -eq 'service-account') {'user'} else {'LocalSystem'})}}
 return @()
}
function Get-FileHash {return @{Hash='expected'}}
function Get-Service {return @{Status='Running'}}
function Start-UserApp {$global:Events.Add('start')}
function Invoke-RestMethod {return @{ok=$true;db_ready=$true;database_access=@{mode='normal'}}}
'''
    source = source.replace("switch ($Command) {", stubs + "\nswitch ($Command) {")
    text = "$global:Events=[Collections.Generic.List[string]]::new()\n$global:Failed=$false\n$global:Failure=" + ops.ps_literal(failure) + "\ntry {\n& {\n" + source + "\n} -Command install -Repo " + ops.ps_literal(str(repo)) + " -Owner " + ops.ps_literal(getpass.getuser()) + " -ExpectedComputer $env:COMPUTERNAME -Commit commit\n} catch { $global:Failed=$true }\n@{events=@($global:Events.ToArray());failed=$global:Failed} | ConvertTo-Json -Compress"
    if failure.startswith("archive-"):
        selected = "../invalid" if failure == "archive-invalid" else archived_release
        text = text.replace(" -Commit commit\n}", " -Commit commit -ArchivedRelease " + ops.ps_literal(selected) + "\n}")
    bootstrap = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); & ([scriptblock]::Create([Console]::In.ReadToEnd()))"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("HH_")}
    result = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", base64.b64encode(bootstrap.encode("utf-16-le")).decode()],
                            input=text, text=True, encoding="utf-8", errors="strict", capture_output=True,
                            timeout=20, env=environment, check=True)
    # A successful mocked workflow emits its result before the final trace.
    tail = result.stdout.strip().splitlines()[-1]
    trace = json.loads(tail)
    assert trace["events"] == expected, result.stdout + result.stderr
    assert trace["failed"] == (failure not in {"none", "archive-ok"}), result.stdout + result.stderr


def test_media_preview_pixels_are_saved_once_and_cannot_escape_report(tmp_path):
    pixels = b"\x89PNG\r\n\x1a\nfixture"
    item = {"name": "sidebar-preview.png", "base64": base64.b64encode(pixels).decode()}
    payload = {"images": [item]}
    ops.save_preview_images(payload, tmp_path)
    assert (tmp_path / "sidebar-preview.png").read_bytes() == pixels
    assert item == {"name": "sidebar-preview.png", "path": str(tmp_path / "sidebar-preview.png")}
    for name in ("../outside.png", "..\\outside.png", "/outside.png", "outside.jpg"):
        with pytest.raises(ValueError):
            ops.save_preview_images({"images": [{"name": name, "base64": base64.b64encode(pixels).decode()}]}, tmp_path)


def test_media_qa_uses_published_canonical_source_and_explicit_interactive_scenario(monkeypatch, tmp_path, capsys):
    selected, scripts = [], []
    monkeypatch.setattr(ops, "published_commit", lambda commit: selected.append(commit) or ("a" * 40, "media-center"))
    monkeypatch.setattr(ops, "run_remote_powershell", lambda config, script, **kwargs: (
        scripts.append(script) or subprocess.CompletedProcess([], 0, '{"scenario":"observe","ok":true}', '')))
    assert ops.main(["media-qa", "--scenario", "observe", "--host", "test.invalid",
                     "--report-root", str(tmp_path)]) == 0
    assert selected == [None] and "-Scenario 'observe'" in scripts[0]
    assert "'media-qa'" in scripts[0] and "Invoke-Session 'media-qa'" in scripts[0]
    assert json.loads(capsys.readouterr().out)["result"]["scenario"] == "observe"


def test_media_runtime_preparation_only_installs_declared_dependencies(monkeypatch, tmp_path, capsys):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    assert probe.main(["prepare-runtime", "--repo", str(tmp_path),
                       "--appdata", str(tmp_path / "roaming"), "--install", str(tmp_path / "installed")]) == 0
    args, kwargs = calls[0]
    assert args[1:] == ["-m", "pip", "install", "-r", "requirements.txt"]
    assert kwargs["cwd"] == tmp_path and kwargs["check"] is True
    assert kwargs["stderr"] == subprocess.STDOUT
    assert "requirements_log" in json.loads(capsys.readouterr().out)


def test_native_media_failure_is_not_ssh_success(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ops, "published_commit", lambda _: ("a" * 40, "media-center"))
    monkeypatch.setattr(ops, "run_remote_powershell", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 0, '{"ok":false,"scenario":"bgm"}', ''))
    assert ops.main(["media-qa", "--host", "test.invalid", "--report-root", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
