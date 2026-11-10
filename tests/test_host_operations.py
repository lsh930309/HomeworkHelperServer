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
from tools.version_policy import BuildVersion
from src.core.tailscale import TailscalePeer, TailscaleSnapshot


@pytest.mark.parametrize("scenario", ["spotify-window-observe", "spotify-window-open", "spotify-window-minimize", "spotify-window-close", "spotify-window-startup", "spotify-window-startup-close", "spotify-window-startup-delayed-close"])
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


def test_release_build_accepts_exact_older_main_revision(published_repository):
    _, command = published_repository
    start = command("rev-parse", "HEAD")
    command("switch", "-qc", "work")
    command("commit", "--allow-empty", "-qm", "feature fixture")
    work = command("rev-parse", "HEAD")
    command("switch", "-q", "main")
    command("merge", "--no-ff", "-qm", "merge fixture", "work")
    command("push", "-q", "origin", "main")
    assert ops.published_release_commit(start) == start
    with pytest.raises(ValueError, match="공개 main 이력"):
        ops.published_release_commit(work)


@pytest.mark.parametrize("event", ["minor", "patch"])
def test_release_build_forwards_only_the_issued_host_release(event, monkeypatch, tmp_path, capsys):
    commit = "a" * 40
    snapshot = BuildVersion("host", "1.7.0", commit, "1.7.0")
    monkeypatch.setattr(ops, "published_release_commit", lambda target: target)
    monkeypatch.setattr(ops.VersionLedger, "read_main", lambda _, target: (event, snapshot))
    calls = []

    def remote(config, script, *, timeout):
        calls.append(script)
        return subprocess.CompletedProcess([], 0, '{"ok":true,"assets":{}}', '')

    monkeypatch.setattr(ops, "run_remote_powershell", remote)
    assert ops.main(["release-build", "--host", "test.invalid", "--commit", commit,
                     "--release-tag", "H/v1.7.0", "--release-repo", "fixture/repo",
                     "--report-root", str(tmp_path)]) == (0 if event == "minor" else 1)
    if event == "patch":
        assert not calls
        assert "발급된 정식 버전과 태그가 필요합니다" in capsys.readouterr().err
    else:
        assert len(calls) == 1
        assert f"-VersionSnapshot {ops.ps_literal(snapshot.to_json())}" in calls[0]
        assert "-Branch 'main'" in calls[0]
        assert "-ReleaseRepo 'fixture/repo'" in calls[0]


@pytest.mark.parametrize(("status", "stdout", "expected"), [
    (0, '{"ok":true,"untrusted":"fixture secret"}', {"ok": True}),
    (0, '{"ok":false,"reason":"cli-missing","untrusted":"fixture secret"}', {"ok": False, "reason": "cli-missing"}),
    (1, 'fixture secret', {"ok": False, "reason": "transport"}),
])
def test_release_preflight_reports_only_known_result_without_build_or_state_write(status, stdout, expected, monkeypatch, tmp_path, capsys):
    calls = []

    def remote(config, script, *, timeout):
        calls.append(script)
        return subprocess.CompletedProcess([], status, stdout, "fixture secret")

    monkeypatch.setattr(ops, "run_remote_powershell", remote)
    monkeypatch.setattr(ops, "published_commit", lambda *_: pytest.fail("preflight must not select a source"))
    monkeypatch.setattr(ops, "VersionLedger", lambda *_: pytest.fail("preflight must not access the ledger"))
    code = ops.main(["release-preflight", "--host", "test.invalid", "--release-repo", "fixture/repo",
                     "--report-root", str(tmp_path)])
    assert code == (0 if expected["ok"] else 1)
    output = capsys.readouterr()
    assert json.loads(output.out) == expected
    assert "fixture secret" not in output.out + output.err
    assert not list(tmp_path.iterdir())
    assert len(calls) == 1
    assert "-Command 'release-preflight'" in calls[0] and "-ReleaseRepo 'fixture/repo'" in calls[0]


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


@pytest.mark.parametrize("command", ["logs", "media-qa"])
@pytest.mark.parametrize("stdout", ['{"누락":', 'null\n', '["잘못된 응답"]\n'])
def test_invalid_remote_response_preserves_outputs_without_retry(monkeypatch, tmp_path, capsys, command, stdout):
    calls = []
    stderr = "원격 진단 메시지\n"

    def remote(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 0, stdout, stderr)

    monkeypatch.setattr(ops, "published_commit", lambda _: ("a" * 40, "media-center"))
    monkeypatch.setattr(ops, "run_remote_powershell", remote)
    assert ops.main([command, "--host", "test.invalid", "--report-root", str(tmp_path)]) == 1

    report = next(tmp_path.glob("*/result.json"))
    failure = json.loads(report.read_text(encoding="utf-8"))
    assert failure == json.loads(capsys.readouterr().err) and failure["ok"] is False
    assert (report.parent / "stdout.log").read_bytes() == stdout.encode("utf-8")
    assert (report.parent / "stderr.log").read_bytes() == stderr.encode("utf-8")
    assert len(calls) == 1


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


@pytest.mark.parametrize("version,release_id", [("1.6.0", "v1.6.0"), ("dev.12", "dev.12")])
def test_install_release_selection_uses_synced_version(published_repository, monkeypatch, capsys, version, release_id):
    repo, command = published_repository
    (repo / ".gitignore").write_text("release/\nbuild.version.json\n")
    command("add", ".gitignore")
    command("commit", "-qm", "ignore local output")
    snapshot = BuildVersion("host", version, command("rev-parse", "HEAD"), "1.6.0")
    (repo / "build.version.json").write_text(snapshot.to_json(), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(repo / "isolated-appdata"))
    assert probe.main(["release", "--repo", str(repo), "--appdata", str(repo / "isolated-appdata"),
                       "--install", str(repo / "installed")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["release_id"] == release_id
    assert Path(result["setup"]) == repo / "release" / f"HomeworkHelper_{release_id}_Setup.exe"
    assert Path(result["portable"]) == repo / "release" / f"HomeworkHelper_{release_id}_Portable.zip"

    with pytest.raises(ValueError, match="패키지 선택의 요청 커밋 또는 버전과 다릅니다"):
        probe.main(["release", "--repo", str(repo), "--appdata", str(repo / "isolated-appdata"),
                    "--install", str(repo / "installed"), "--expected-commit", snapshot.commit,
                    "--expected-version", "1.6.1"])

    command("commit", "--allow-empty", "-qm", "move checkout")
    from build import BuildConfigError
    with pytest.raises(BuildConfigError, match="빌드 버전 스냅숏과 현재 제품 또는 소스 커밋이 다릅니다"):
        probe.main(["release", "--repo", str(repo), "--appdata", str(repo / "isolated-appdata"),
                    "--install", str(repo / "installed")])


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
                       "--install", str(tmp_path / "installed")]) == 0
    assert calls[0][0][1:] == ["build.py", "--no-prune-archives"]
    assert len(calls) == 1


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows PowerShell required")
@pytest.mark.parametrize("scenario", ["match", "wrong-digest", "wrong-tag"])
def test_windows_release_upload_preserves_existing_draft_asset(tmp_path, scenario):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    python = repo / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    snapshot = BuildVersion("host", "1.7.0", "a" * 40, "1.7.0")
    (repo / "build.version.json").write_text(snapshot.to_json(), encoding="utf-8")
    (repo / "release").mkdir()
    for suffix in ("Setup.exe", "Portable.zip"):
        (repo / "release" / f"HomeworkHelper_v1.7.0_{suffix}").write_bytes(suffix.encode())

    stubs = r'''
function Git-Checked($Arguments) {
    switch ($Arguments[0]) {
        'status' { return '' }
        'rev-parse' { return $Commit }
        'remote' { return 'https://github.com/fixture/repo.git' }
        'ls-remote' {
            $Target = if ($global:Scenario -eq 'wrong-tag') { 'b' * 40 } else { $Commit }
            return "$Target`trefs/tags/H/v1.7.0"
        }
        default { throw 'existing packages must not trigger a source checkout' }
    }
}
function Get-AuthenticodeSignature { return @{Status='Valid'} }
function Invoke-Probe($Kind, $Portable) {
    if ($Kind -eq 'release') { return @{setup=(Join-Path $Repo 'release/HomeworkHelper_v1.7.0_Setup.exe');portable=(Join-Path $Repo 'release/HomeworkHelper_v1.7.0_Portable.zip')} }
    if ($Kind -eq 'payload') { return @{} }
    throw 'existing packages must not trigger a rebuild'
}
function gh {
    $global:LASTEXITCODE = 0
    if ($args[1] -eq 'view') {
        $Digest = (Get-FileHash (Join-Path $Repo 'release/HomeworkHelper_v1.7.0_Setup.exe')).Hash.ToLowerInvariant()
        if ($global:Scenario -eq 'wrong-digest') { $Digest = '0' * 64 }
        return @{isDraft=$true;tagName=$ReleaseTag;assets=@(@{name='HomeworkHelper_v1.7.0_Setup.exe';state='uploaded';digest=('sha256:'+$Digest)})} | ConvertTo-Json -Depth 6
    }
    if ($args[1] -ne 'upload' -or $args -contains '--clobber') { throw 'unexpected mutation' }
    $global:Uploads = @($args | Where-Object {$_ -match '\.(zip|exe)\z'} | ForEach-Object {[IO.Path]::GetFileName($_)})
}
'''
    source = (ops.ROOT / "tools/windows_host_operations.ps1").read_text(encoding="utf-8")
    source = source.replace("switch ($Command) {", stubs + "\nswitch ($Command) {")
    arguments = {
        "Command": "release-build", "Repo": str(repo), "Owner": getpass.getuser(),
        "Commit": snapshot.commit, "Branch": "main", "VersionSnapshot": snapshot.to_json(),
        "ReleaseRepo": "fixture/repo", "ReleaseTag": snapshot.tag,
    }
    invocation = " ".join(f"-{key} {ops.ps_literal(value)}" for key, value in arguments.items())
    source = (f"$global:Scenario={ops.ps_literal(scenario)}\n$global:Uploads=@()\n$Failure=''\n"
              "try { & {\n" + source + "\n} " + invocation + " -ExpectedComputer $env:COMPUTERNAME\n"
              "} catch { $Failure=$_.Exception.Message }\n"
              "@{uploads=$global:Uploads;failure=$Failure} | ConvertTo-Json -Compress")
    bootstrap = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); & ([scriptblock]::Create([Console]::In.ReadToEnd()))"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("HH_")}
    result = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", base64.b64encode(bootstrap.encode("utf-16-le")).decode()],
                            input=source, text=True, encoding="utf-8", errors="strict", capture_output=True,
                            timeout=20, env=environment, check=True)
    trace = json.loads(result.stdout.strip().splitlines()[-1])
    if scenario == "match":
        assert trace == {"uploads": ["HomeworkHelper_v1.7.0_Portable.zip"], "failure": ""}
    elif scenario == "wrong-digest":
        assert trace["uploads"] == [] and "기존 초안 자산이 원본과 다릅니다" in trace["failure"]
    else:
        assert trace["uploads"] == [] and "릴리즈 태그와 빌드 커밋이 다릅니다" in trace["failure"]


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows PowerShell required")
@pytest.mark.parametrize("failure,expected", [
    ("dirty", []), ("source", []), ("snapshot", []), ("release", ["release"]), ("signature", ["release"]),
    ("payload", ["release", "payload"]), ("preflight", ["release", "payload", "preflight"]),
    ("backup", ["release", "payload", "preflight", "backup"]),
    ("quit", ["release", "payload", "preflight", "backup", "preflight", "quit"]),
    ("setup", ["release", "payload", "preflight", "backup", "preflight", "quit", "setup"]),
    ("service-account", ["release", "payload", "preflight", "backup", "preflight", "quit", "setup"]),
    ("none", ["release", "payload", "preflight", "backup", "preflight", "quit", "setup", "start", "inspect"]),
    ("archive-missing", []), ("archive-duplicate", []), ("archive-invalid", []),
    ("archive-ok", ["payload", "preflight", "backup", "preflight", "quit", "setup", "start", "inspect"]),
    ("archive-pair", ["payload", "preflight", "backup", "preflight", "quit", "setup", "start", "inspect"]),
    ("archive-incomplete-pair", []),
])
def test_windows_install_stops_before_mutation_on_preparation_failure(tmp_path, failure, expected):
    # Full PowerShell workflow, OS calls mocked in this disposable process only.
    # No production executable, DB, service or scheduled task is invoked.
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    python = repo / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    commit = "a" * 40
    version = BuildVersion("host", "1.6.0", commit, "1.6.0")
    stale = BuildVersion("host", "1.6.1", commit, "1.6.1")
    (repo / "build.version.json").write_text((stale if failure == "snapshot" else version).to_json(), encoding="utf-8")
    archived_release = "v1.0.0_b1_gabc1234"
    if failure in {"archive-ok", "archive-duplicate", "archive-pair", "archive-incomplete-pair"}:
        for folder in (["one", "two"] if failure == "archive-duplicate" else ["one"]):
            archive = repo / "release/archives/windows-host" / folder
            archive.mkdir(parents=True)
            for suffix in ("Setup.exe", "Portable.zip"):
                (archive / f"HomeworkHelper_{archived_release}_{suffix}").write_bytes(b"inert fixture")
        if failure in {"archive-pair", "archive-incomplete-pair"}:
            pair = repo / "release/archives/windows-host/by-version" / archived_release
            pair.mkdir(parents=True)
            (pair / f"HomeworkHelper_{archived_release}_Setup.exe").write_bytes(b"pair fixture")
            if failure == "archive-pair":
                (pair / f"HomeworkHelper_{archived_release}_Portable.zip").write_bytes(b"pair fixture")
    elif failure.startswith("archive-"):
        (repo / "release/archives/windows-host").mkdir(parents=True)
    source = (ops.ROOT / "tools/windows_host_operations.ps1").read_text(encoding="utf-8")
    stubs = r'''
function Git-Checked($Arguments) {
 if ($Arguments[0] -eq 'status') {if ($global:Failure -in @('dirty','archive-ok')) {return 'M changed'}; return ''}
 if ($global:Failure -eq 'source') {return 'other'}; return $Commit
}
function Require-InstallTime {}
function Get-AuthenticodeSignature {if ($global:Failure -eq 'signature') {return @{Status='NotSigned'}}; return @{Status='Valid'}}
function Invoke-Probe($Kind,$Portable) {
 $global:Events.Add($Kind)
 if ($Kind -eq $global:Failure) {throw ('expected '+$Kind+' failure')}
 if ($Kind -eq 'release') {return @{release_id='v1.6.0';setup='test_Setup.exe';portable='test_Portable.zip'}}
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
    arguments = ["-Commit " + ops.ps_literal(commit), "-VersionSnapshot " + ops.ps_literal(version.to_json())]
    if failure.startswith("archive-"):
        selected = "../invalid" if failure == "archive-invalid" else archived_release
        arguments.append("-ArchivedRelease " + ops.ps_literal(selected))
    text = "$global:Events=[Collections.Generic.List[string]]::new()\n$global:Failed=$false\n$global:Failure=" + ops.ps_literal(failure) + "\ntry {\n& {\n" + source + "\n} -Command install -Repo " + ops.ps_literal(str(repo)) + " -Owner " + ops.ps_literal(getpass.getuser()) + " -ExpectedComputer $env:COMPUTERNAME " + " ".join(arguments) + "\n} catch { $global:Failed=$true }\n@{events=@($global:Events.ToArray());failed=$global:Failed} | ConvertTo-Json -Compress"
    bootstrap = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); & ([scriptblock]::Create([Console]::In.ReadToEnd()))"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("HH_")}
    result = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", base64.b64encode(bootstrap.encode("utf-16-le")).decode()],
                            input=text, text=True, encoding="utf-8", errors="strict", capture_output=True,
                            timeout=20, env=environment, check=True)
    # A successful mocked workflow emits its result before the final trace.
    tail = result.stdout.strip().splitlines()[-1]
    trace = json.loads(tail)
    assert trace["events"] == expected, result.stdout + result.stderr
    assert trace["failed"] == (failure not in {"none", "archive-ok", "archive-pair"}), result.stdout + result.stderr


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
    pixels = b"\x89PNG\r\n\x1a\nfixture"
    payload = {"scenario": "preview", "ok": True,
               "images": [{"name": "sidebar-preview.png", "base64": base64.b64encode(pixels).decode()}]}
    monkeypatch.setattr(ops, "published_commit", lambda commit: selected.append(commit) or ("a" * 40, "media-center"))
    monkeypatch.setattr(ops, "run_remote_powershell", lambda config, script, **kwargs: (
        scripts.append(script) or subprocess.CompletedProcess([], 0, json.dumps(payload), '')))
    assert ops.main(["media-qa", "--scenario", "preview", "--host", "test.invalid",
                     "--report-root", str(tmp_path)]) == 0
    assert selected == [None] and "-Scenario 'preview'" in scripts[0]
    assert "'media-qa'" in scripts[0] and "Invoke-Session 'media-qa'" in scripts[0]
    summary = json.loads(capsys.readouterr().out)
    report = Path(summary["report"])
    assert summary["result"]["scenario"] == "preview"
    assert (report / "sidebar-preview.png").read_bytes() == pixels
    assert json.loads((report / "stdout.log").read_text(encoding="utf-8")) == summary["result"]
    assert "base64" not in summary["result"]["images"][0]


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
