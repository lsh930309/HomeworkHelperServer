"""User contracts for the headless authority boundary; no native effects execute."""

from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from src.host_service.client import HostPrivilegeClient, PrivilegeServiceError, PrivilegeServiceUnavailable
from src.host_service.constants import MAX_MESSAGE_BYTES, SYSTEM_SID
from src.host_service.controller import Caller, PrivilegeController, ProcessIdentity, RequestDenied, Session
from src.host_service.repository import ReadOnlyUserRepository, SettingsSnapshot, UserSnapshot, preset_launch_inputs
from src.host_service.transport import decode_message, encode_message


OWNER = "S-1-5-21-100"
INSTALL = Path(r"C:\Program Files\HomeworkHelper")


class Backend:
    def __init__(self):
        self.session = Session(OWNER, 4, Path("unused"), "logon-a")
        self.effects = []
        self.identities = [ProcessIdentity(20, 5.0, r"C:\Games\game.exe", OWNER, 4)]

    def sessions(self, _owner):
        return [self.session] if self.session else []

    def current_session(self, _owner):
        return self.session

    def read_as_user(self, session):
        assert session == self.session
        return nullcontext()

    def launch(self, session, target, args, *, elevated):
        self.effects.append(("launch", session, target, args, elevated))
        return {"worker_pid":100}

    def processes(self, _session):
        return self.identities

    def terminate(self, identity):
        self.effects.append(("terminate", identity))

    def startup(self, session):
        self.effects.append(("startup", session))

    def power(self, action):
        self.effects.append(("power", action))

    def prepare_power(self, action):
        assert action in {"sleep", "shutdown", "restart"}


class Repository:
    def __init__(self):
        self.snapshot = UserSnapshot(SettingsSnapshot(True, True), (
            SimpleNamespace(id="game", name="Game", monitoring_path=r"C:\Games\game.exe",
                            launch_path=r"C:\Games\launcher.exe", original_launch_path="",
                            preferred_launch_type="shortcut", launch_args_enabled=True,
                            launch_args="--profile sample", user_preset_id=None),
        ))
        self.reads = 0

    def read(self, _session, *, settings_only=False):
        self.reads += 1
        return self.snapshot


@pytest.fixture
def system():
    from src.core.launch_target import resolve_launch_args, resolve_launch_target
    backend = Backend()
    repository = Repository()
    controller = PrivilegeController(OWNER, INSTALL, backend, repository,
                                    resolver=resolve_launch_target, argument_resolver=resolve_launch_args,
                                    admin_required=lambda _target: True)
    caller = Caller(10, OWNER, 4, str(INSTALL / "homework_helper.exe"), "logon-a")
    return controller, backend, repository, caller


def test_login_precedes_all_data_reads_but_status_and_power_work_without_login(system):
    controller, backend, repository, caller = system
    backend.session = None
    caller = replace(caller, session_id=0)
    status = controller.handle({"operation":"status"}, caller).payload
    assert status["accepted"] and not status["user_session_ready"]
    reply = controller.handle({"operation":"power", "action":"sleep"}, caller)
    assert reply.payload["status"] == "accepted"
    assert backend.effects == []  # An acceptance response must precede the power effect.
    reply.after_send()
    assert backend.effects == [("power", "sleep")]
    with pytest.raises(RequestDenied, match="로그인"):
        controller.handle({"operation":"launch_managed", "process_id":"game", "mode":"direct"}, caller)
    assert repository.reads == 0


@pytest.mark.parametrize("changes", [{"sid":"S-1-5-21-999"}, {"image_path":r"C:\Temp\homework_helper.exe"},
                                    {"image_path":r"C:\Program Files\HomeworkHelper\fake.exe"}])
def test_endpoint_identity_is_not_supplied_by_request(system, changes):
    controller, backend, repository, caller = system
    with pytest.raises(RequestDenied):
        controller.handle({"operation":"status"}, replace(caller, **changes))
    assert repository.reads == 0 and backend.effects == []


@pytest.mark.parametrize("payload", [
    {"operation":"status", "sid":OWNER},
    {"operation":"power", "action":"hibernate"},
    {"operation":"power", "action":"shutdown", "force":True},
    {"operation":"execute", "target":"cmd.exe"},
    {"operation":"launch_managed", "process_id":"game", "path":"cmd.exe"},
    {"operation":"launch_managed", "process_id":"game", "mode":"invalid"},
])
def test_no_free_form_command_or_power_flags(system, payload):
    controller, backend, _repository, caller = system
    with pytest.raises(RequestDenied):
        controller.handle(payload, caller)
    assert backend.effects == []


def test_launch_uses_registered_target_and_arguments_with_basic_or_high_token(system):
    controller, backend, _repository, caller = system
    reply = controller.handle({"operation":"launch_managed", "process_id":"game", "mode":"direct"}, caller)
    assert reply.payload["elevated"] is True
    assert backend.effects[0][2:] == (r"C:\Games\game.exe", "--profile sample", True)
    controller.admin_required = lambda target: False
    controller.handle({"operation":"launch_managed", "process_id":"game", "mode":"shortcut"}, caller)
    assert backend.effects[1][-1] is False


def test_unregistered_target_and_disabled_admin_features_do_not_run(system):
    controller, backend, repository, caller = system
    with pytest.raises(LookupError):
        controller.handle({"operation":"launch_managed", "process_id":"missing"}, caller)
    repository.snapshot = replace(repository.snapshot, settings=SettingsSnapshot(False, True))
    with pytest.raises(RequestDenied, match="꺼져"):
        controller.handle({"operation":"launch_managed", "process_id":"game"}, caller)
    assert backend.effects == []


@pytest.mark.parametrize("change", [{"session_id":7}, {"logon_id":"logon-b"}, {"owner_sid":"other"}])
def test_late_request_does_not_rebind_to_new_user_session(system, change):
    controller, backend, repository, caller = system
    read = repository.read
    def read_then_switch(session):
        snapshot = read(session)
        backend.session = replace(backend.session, **change)
        return snapshot
    repository.read = read_then_switch
    with pytest.raises(RequestDenied, match="변경"):
        controller.handle({"operation":"launch_managed", "process_id":"game"}, caller)
    assert backend.effects == []


@pytest.mark.parametrize("change", [{"session_id":7}, {"logon_id":"old-logon"}, {"sid":SYSTEM_SID}])
def test_data_request_requires_actual_owner_logon_identity(system, change):
    controller, backend, repository, caller = system
    with pytest.raises(RequestDenied):
        controller.handle({"operation":"inspect_managed", "process_ids":["game"]}, replace(caller, **change))
    assert repository.reads == 0 and backend.effects == []


def test_inspection_excludes_other_user_session_and_different_executable(system):
    controller, backend, _repository, caller = system
    backend.identities.extend([
        ProcessIdentity(21, 6.0, r"C:\Games\game.exe", "other", 4),
        ProcessIdentity(22, 7.0, r"C:\Games\game.exe", OWNER, 8),
        ProcessIdentity(23, 8.0, r"C:\Games\different.exe", OWNER, 4),
    ])
    result = controller.handle({"operation":"inspect_managed", "process_ids":["game"]}, caller).payload
    assert [entry["pid"] for entry in result["processes"]] == [20]
    assert result["processes"][0]["process_id"] == "game"


@pytest.mark.parametrize("extra", [{"pid":20}, {"pid":True, "create_time":5.0},
                                  {"pid":20, "create_time":6.0}, {"create_time":5.0}])
def test_pid_reuse_and_incomplete_identity_cannot_terminate(system, extra):
    controller, backend, _repository, caller = system
    with pytest.raises(RequestDenied):
        controller.handle({"operation":"stop_managed", "process_id":"game", **extra}, caller)
    assert backend.effects == []


def test_exact_observed_identity_terminates_only_registered_process(system):
    controller, backend, _repository, caller = system
    result = controller.handle({"operation":"stop_managed", "process_id":"game",
                                "pid":20, "create_time":5.0}, caller).payload
    assert result["stopped"][0]["pid"] == 20
    assert backend.effects == [("terminate", backend.identities[0])]


def test_logon_starts_once_unlock_and_recovery_do_not_reopen_app(system):
    controller, backend, _repository, _caller = system
    controller.on_session_change("logon", 4)
    controller.on_session_change("unlock", 4)
    controller.on_session_change("logon", 4)
    assert len(backend.effects) == 1
    controller.on_session_change("logoff", 4)
    backend.session = replace(backend.session, logon_id="logon-b")
    controller.on_session_change("logon", 4)
    assert len(backend.effects) == 2
    recovery = PrivilegeController(OWNER, INSTALL, backend, Repository())
    recovery.seed_logged_on_sessions()
    recovery.on_session_change("logon", 4)
    assert len(backend.effects) == 2


def test_disabled_startup_or_other_user_logon_does_not_start_app(system):
    controller, backend, repository, _caller = system
    repository.snapshot = replace(repository.snapshot, settings=SettingsSnapshot(True, False))
    controller.on_session_change("logon", 4)
    controller.on_session_change("logon", 7)
    assert backend.effects == []


def _create_db(appdata, *, wal=False):
    directory = appdata / "homework_helper_data"
    directory.mkdir(parents=True)
    database = directory / "app_data.db"
    connection = sqlite3.connect(database)
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE global_settings (id, run_as_admin, run_on_startup)")
    connection.execute("INSERT INTO global_settings VALUES (1, 1, 0)")
    connection.execute("CREATE TABLE managed_processes (id, name, monitoring_path, launch_path, "
                       "original_launch_path, preferred_launch_type, launch_args_enabled, launch_args, user_preset_id)")
    connection.execute("INSERT INTO managed_processes VALUES ('game', 'Game', 'game.exe', 'launcher.exe', "
                       "'launcher.exe', 'shortcut', 1, '--profile sample', NULL)")
    connection.commit()
    connection.close()
    return database


@pytest.mark.parametrize("wal", [False, True])
def test_read_only_repository_reads_canonical_rows_without_main_file_changes(tmp_path, wal):
    appdata = tmp_path / "HomeworkHelper"
    database = _create_db(appdata, wal=wal)
    before = database.read_bytes()
    mtime = database.stat().st_mtime_ns
    snapshot = ReadOnlyUserRepository().read(Session(OWNER, 4, appdata))
    assert snapshot.settings == SettingsSnapshot(True, False)
    assert snapshot.process("game").launch_args == "--profile sample"
    assert database.read_bytes() == before and database.stat().st_mtime_ns == mtime
    check = sqlite3.connect(database)
    assert check.execute("SELECT run_as_admin,run_on_startup FROM global_settings").fetchall() == [(1,0)]
    assert check.execute("SELECT COUNT(*) FROM managed_processes").fetchone()[0] == 1
    check.close()


def test_reader_never_creates_profile_or_database_when_absent(tmp_path):
    appdata = tmp_path / "absent" / "HomeworkHelper"
    with pytest.raises(sqlite3.OperationalError):
        ReadOnlyUserRepository().read(Session(OWNER, 4, appdata))
    assert list(tmp_path.iterdir()) == []


def test_login_startup_reads_settings_without_requiring_game_schema(tmp_path):
    appdata = tmp_path / "HomeworkHelper"
    (appdata / "homework_helper_data").mkdir(parents=True)
    database = appdata / "homework_helper_data" / "app_data.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE global_settings (id,run_as_admin,run_on_startup)")
    connection.execute("INSERT INTO global_settings VALUES (1,0,1)")
    connection.commit()
    connection.close()
    snapshot = ReadOnlyUserRepository().read(Session(OWNER,4,appdata), settings_only=True)
    assert snapshot.settings.run_on_startup and not snapshot.processes


def test_user_preset_is_canonical_and_candidate_presence_is_observed(tmp_path):
    folder = tmp_path / "games"
    folder.mkdir()
    (folder / "HYP.exe").touch()
    preset_file = tmp_path / "game_presets_user.json"
    preset_file.write_text(json.dumps({"presets":[{"id":"custom", "launcher_patterns":["HYP.exe"]}]}))
    process = SimpleNamespace(user_preset_id="custom", launch_path=str(folder / "Game.exe"), monitoring_path="")
    before = preset_file.read_bytes()
    patterns, existing = preset_launch_inputs(process, Session(OWNER, 4, tmp_path))
    assert patterns == ("HYP.exe",) and existing == frozenset({str(folder / "HYP.exe")})
    assert preset_file.read_bytes() == before


def test_client_rejects_failed_or_malformed_response_and_does_not_retry():
    requests = []
    def transport(request):
        requests.append(request)
        return {"accepted":False, "status":"denied", "message":"로그인 필요"}
    with pytest.raises(PrivilegeServiceError, match="로그인"):
        HostPrivilegeClient(transport=transport).launch_managed("game")
    assert len(requests) == 1
    with pytest.raises(PrivilegeServiceError):
        HostPrivilegeClient(transport=lambda _: {"accepted":"true"}).status()
    def unavailable(_request):
        raise OSError("absent")
    with pytest.raises(PrivilegeServiceUnavailable):
        HostPrivilegeClient(transport=unavailable).status()


def test_client_uses_id_and_observed_identity_without_privileged_path_input():
    requests = []
    client = HostPrivilegeClient(transport=lambda request: requests.append(request) or {"accepted":True})
    client.launch_managed("game", "direct")
    client.inspect_managed(["game"])
    client.stop_managed("game", pid=20, create_time=5.0)
    assert requests == [{"operation":"launch_managed", "process_id":"game", "mode":"direct"},
                        {"operation":"inspect_managed", "process_ids":["game"]},
                        {"operation":"stop_managed", "process_id":"game", "pid":20,"create_time":5.0}]


def test_ipc_size_type_and_non_finite_values_are_rejected():
    assert decode_message(encode_message({"accepted":True, "message":"준비"}))["message"] == "준비"
    for data in (b"[]", b'{"value":NaN}', b"x" * (MAX_MESSAGE_BYTES + 1)):
        with pytest.raises(ValueError):
            decode_message(data)
    with pytest.raises(ValueError):
        encode_message({"value":float("inf")})


def test_control_cli_exits_after_inert_status_or_power_result(monkeypatch, capsys):
    import homework_helper_service
    requests = []
    monkeypatch.setattr(HostPrivilegeClient, "status", lambda _: {"accepted":True, "status":"ready"})
    monkeypatch.setattr(HostPrivilegeClient, "control_power", lambda _, action: requests.append(action) or
                        {"accepted":True, "status":"accepted", "action":action})
    assert homework_helper_service.main(["--control", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert homework_helper_service.main(["--control", "power", "sleep"]) == 0
    assert requests == ["sleep"]


def test_ssh_visible_power_receipt_flushes_before_ack_releases_action(monkeypatch):
    """Exercise CLI → client → pipe boundary, with inert handles and power effect."""
    import io
    import sys
    import homework_helper_service
    from src.host_service import transport

    order = []
    class Output(io.StringIO):
        def flush(self):
            order.append(("flushed", self.getvalue()))
    output = Output()
    monkeypatch.setattr(sys, "stdout", output)
    api = SimpleNamespace(CloseHandle=lambda _handle: None)
    con = SimpleNamespace(OPEN_EXISTING=3, FILE_FLAG_OVERLAPPED=0x40000000)
    files = SimpleNamespace(CreateFile=lambda *args: "inert-handle")
    pipes = SimpleNamespace(PIPE_READMODE_MESSAGE=2, WaitNamedPipe=lambda *args: None,
                            SetNamedPipeHandleState=lambda *args: None)
    monkeypatch.setattr(transport, "_windows", lambda: (None, api, con, None, files, pipes, None))
    def exchange(_handle, *, data=None, **kwargs):
        if data is None:
            order.append(("reply", None))
            return encode_message({"accepted":True, "status":"accepted", "action":"sleep"})
        message = decode_message(data)
        if message == {"received":True}:
            order.append(("ack", None))
            order.append(("inert-power-effect", None))
        else:
            order.append(("request", message))
        return len(data)
    monkeypatch.setattr(transport, "_overlapped_io", exchange)
    assert homework_helper_service.main(["--control", "power", "sleep"]) == 0
    assert [item[0] for item in order] == ["request", "reply", "flushed", "ack", "inert-power-effect"]
    assert json.loads(order[2][1])["accepted"] is True
    assert json.loads(output.getvalue())["status"] == "accepted"


def test_s3_preflight_denial_never_accepts_or_schedules_power(system):
    controller, backend, _repository, caller = system
    def unsupported(_action):
        raise NotImplementedError("UnsupportedS3")
    backend.prepare_power = unsupported
    with pytest.raises(NotImplementedError, match="UnsupportedS3"):
        controller.handle({"operation":"power", "action":"sleep"}, caller)
    assert backend.effects == []
