"""User contracts for the headless authority boundary; no native effects execute."""

from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
from queue import SimpleQueue
import sqlite3
import sys
from threading import Event, Thread
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
        return {"accepted":True, "pid":100}

    def launch_obs(self, session, executable, hidden):
        return {"accepted":True, "pid":101}

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
    with pytest.raises(RequestDenied, match="로그온"):
        controller.handle({"operation":"power", "action":"sleep"}, caller)
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
    controller.process_session_events()
    controller.on_session_change("unlock", 4)
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    assert len(backend.effects) == 1
    controller.on_session_change("logoff", 4)
    backend.session = replace(backend.session, logon_id="logon-b")
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    assert len(backend.effects) == 2
    recovery = PrivilegeController(OWNER, INSTALL, backend, Repository())
    recovery.seed_logged_on_sessions()
    recovery.on_session_change("logon", 4)
    recovery.process_session_events()
    assert len(backend.effects) == 2


def test_disabled_startup_or_other_user_logon_does_not_start_app(system):
    controller, backend, repository, _caller = system
    repository.snapshot = replace(repository.snapshot, settings=SettingsSnapshot(True, False))
    controller.on_session_change("logon", 4)
    controller.on_session_change("logon", 7)
    controller.process_session_events()
    assert backend.effects == []


@pytest.fixture
def startup_system(system):
    controller, backend, repository, _caller = system
    clock = [0.0]
    errors = []
    controller._clock = lambda: clock[0]
    controller._log_error = errors.append
    return controller, backend, repository, clock, errors


def test_logon_callback_does_not_read_settings_or_create_process(startup_system):
    controller, backend, repository, _clock, _errors = startup_system
    controller.on_session_change("logon", 4)
    assert repository.reads == 0 and backend.effects == []
    controller.process_session_events()
    assert repository.reads == 1 and len(backend.effects) == 1


def test_logon_during_initialization_is_not_seeded_as_existing(startup_system):
    controller, backend, _repository, _clock, _errors = startup_system
    controller.on_session_change("logon", 4)
    controller.seed_logged_on_sessions()
    controller.process_session_events()
    assert len(backend.effects) == 1


def test_token_preparation_retries_once_per_second_then_starts_once(startup_system):
    controller, backend, repository, clock, errors = startup_system
    session = backend.session
    backend.session = None
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    clock[0] = 0.5
    backend.session = session
    controller.process_session_events()
    assert backend.effects == [] and repository.reads == 0
    clock[0] = 1
    controller.process_session_events()
    assert len(backend.effects) == 1
    controller.on_session_change("logon", 4)
    clock[0] = 20
    controller.process_session_events()
    assert len(backend.effects) == 1 and repository.reads == 1 and not errors


def test_missing_token_stops_retrying_at_120_seconds(startup_system):
    controller, backend, repository, clock, errors = startup_system
    session = backend.session
    backend.session = None
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    clock[0] = 120
    backend.session = session
    controller.process_session_events()
    controller.on_session_change("logon", 4)
    clock[0] = 121
    controller.process_session_events()
    assert repository.reads == 0 and backend.effects == []
    assert len(errors) == 1 and "120s" in errors[0]


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED])
def test_busy_settings_read_retries_without_consuming_logon(startup_system, code):
    controller, backend, repository, clock, errors = startup_system
    read = repository.read
    attempts = []
    def temporarily_busy(session, **kwargs):
        attempts.append(session)
        if len(attempts) == 1:
            error = sqlite3.OperationalError("database busy")
            error.sqlite_errorcode = code
            raise error
        return read(session, **kwargs)
    repository.read = temporarily_busy
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    assert backend.effects == []
    clock[0] = 1
    controller.process_session_events()
    assert len(attempts) == 2 and len(backend.effects) == 1 and not errors


@pytest.mark.parametrize("error", [LookupError("설정 없음"), sqlite3.DatabaseError("손상된 DB"),
                                   sqlite3.OperationalError("unable to open database file"),
                                   PermissionError("접근 거부")])
def test_permanent_settings_error_is_reported_without_guess_or_retry(startup_system, error):
    controller, backend, repository, clock, errors = startup_system
    attempts = []
    def failed_read(session, **_kwargs):
        attempts.append(session)
        raise error
    repository.read = failed_read
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    clock[0] = 1
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    assert len(attempts) == 1 and backend.effects == []
    assert len(errors) == 1 and str(error) in errors[0]


def test_first_createprocess_token_failure_retries_then_launches(startup_system):
    controller, backend, _repository, clock, errors = startup_system
    startup = backend.startup
    attempts = []
    def token_not_ready(session):
        attempts.append(session)
        if len(attempts) == 1:
            error = OSError("token not ready")
            error.winerror = 1008
            raise error
        return startup(session)
    backend.startup = token_not_ready
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    clock[0] = 1
    controller.process_session_events()
    assert len(attempts) == 2 and len(backend.effects) == 1 and not errors


@pytest.mark.parametrize("event", ["logoff", "disconnect"])
def test_ended_or_switched_session_cancels_pending_startup(startup_system, event):
    controller, backend, repository, clock, _errors = startup_system
    session = backend.session
    backend.session = None
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    controller.on_session_change(event, 4)
    backend.session = session
    clock[0] = 1
    controller.process_session_events()
    assert repository.reads == 0 and backend.effects == []


@pytest.mark.parametrize("change", [{"session_id":7}, {"owner_sid":"other"}, {"logon_id":"logon-b"}])
def test_bound_startup_does_not_rebind_after_temporary_failure(startup_system, change):
    controller, backend, repository, clock, errors = startup_system
    def locked(_session, **_kwargs):
        error = sqlite3.OperationalError("locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise error
    repository.read = locked
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    backend.session = replace(backend.session, **change)
    clock[0] = 1
    controller.process_session_events()
    assert backend.effects == [] and len(errors) == 1


def test_new_authentication_id_can_start_even_when_session_id_is_reused(startup_system):
    controller, backend, _repository, _clock, _errors = startup_system
    controller.seed_logged_on_sessions()
    backend.session = replace(backend.session, logon_id="logon-b")
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    assert len(backend.effects) == 1 and backend.effects[0][1].logon_id == "logon-b"


def test_logoff_arriving_during_settings_read_prevents_creation(startup_system):
    controller, backend, repository, _clock, _errors = startup_system
    read = repository.read
    def logoff_during_read(session, **kwargs):
        snapshot = read(session, **kwargs)
        controller.on_session_change("logoff", 4)
        return snapshot
    repository.read = logoff_during_read
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    assert backend.effects == []


def test_service_stop_during_settings_read_prevents_creation(startup_system):
    controller, backend, repository, _clock, _errors = startup_system
    stop = Event()
    read = repository.read
    def stop_during_read(session, **kwargs):
        snapshot = read(session, **kwargs)
        stop.set()
        return snapshot
    repository.read = stop_during_read
    controller.on_session_change("logon", 4)
    controller.process_session_events(stop)
    assert backend.effects == []


def test_expired_preparation_does_not_start_after_slow_settings_read(startup_system):
    controller, backend, repository, clock, errors = startup_system
    read = repository.read
    def slow_read(session, **kwargs):
        snapshot = read(session, **kwargs)
        clock[0] = 120
        return snapshot
    repository.read = slow_read
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    controller.process_session_events()
    assert backend.effects == [] and len(errors) == 1


def test_worker_can_stop_while_waiting_for_preparation(startup_system):
    controller, backend, _repository, _clock, _errors = startup_system
    backend.session = None
    controller.on_session_change("logon", 4)
    stop = Event()
    worker = Thread(target=controller.run_session_startup, args=(stop,))
    worker.start()
    stop.set()
    worker.join(timeout=2)
    assert not worker.is_alive() and backend.effects == []


def test_already_running_app_completes_logon_without_duplicate_creation(startup_system):
    controller, backend, repository, _clock, errors = startup_system
    existing = []
    backend.startup = lambda session: existing.append(session) or {
        "accepted":True, "pid":321, "already_running":True,
    }
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    assert len(existing) == 1 and repository.reads == 1 and not errors


def test_disabled_startup_decision_does_not_read_again_or_start_after_setting_change(startup_system):
    controller, backend, repository, _clock, errors = startup_system
    repository.snapshot = replace(repository.snapshot, settings=SettingsSnapshot(True, False))
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    repository.snapshot = replace(repository.snapshot, settings=SettingsSnapshot(True, True))
    controller.on_session_change("logon", 4)
    controller.on_session_change("unlock", 4)
    controller.process_session_events()
    assert repository.reads == 1 and backend.effects == [] and not errors


def test_unknown_launch_result_is_not_automatically_retried(startup_system):
    controller, backend, _repository, clock, errors = startup_system
    attempts = []
    backend.startup = lambda session: attempts.append(session) or {"accepted":True}
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    clock[0] = 1
    controller.process_session_events()
    assert len(attempts) == 1 and len(errors) == 1
    assert "실행 완료" in errors[0]


def test_scm_callback_retains_initial_events_and_stop_cancels_worker(monkeypatch):
    import homework_helper_service as entry
    class Framework:
        def __init__(self, _args):
            self.statuses = []
            self.SvcOtherEx(14, 5, (3,))
        def ReportServiceStatus(self, status):
            self.statuses.append(status)
    stop_handle = object()
    signalled = []
    monkeypatch.setitem(sys.modules, "servicemanager", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "win32serviceutil", SimpleNamespace(ServiceFramework=Framework))
    monkeypatch.setitem(sys.modules, "win32event", SimpleNamespace(
        CreateEvent=lambda *_args: stop_handle, SetEvent=signalled.append,
    ))
    monkeypatch.setitem(sys.modules, "win32service", SimpleNamespace(
        SERVICE_CONTROL_SESSIONCHANGE=14, SERVICE_STOP_PENDING=3,
    ))
    service = entry.service_class()([])
    assert service.controller is None
    service.SvcOtherEx(14, 5, (4,))
    # A configured controller must not be invoked by the callback either.
    service.controller = SimpleNamespace(on_session_change=lambda *_args: pytest.fail("blocking callback"))
    service.SvcOtherEx(14, 2, (4,))
    service.SvcOtherEx(14, 6, (4,))
    assert [service.session_events.get_nowait()[:2] for _ in range(4)] == [
        ("logon", 3), ("logon", 4), ("disconnect", 4), ("logoff", 4),
    ]
    service.SvcStop()
    assert service.startup_stop.is_set() and signalled == [stop_handle]


def _create_db(appdata, *, wal=False):
    directory = appdata / "homework_helper_data"
    directory.mkdir(parents=True)
    database = directory / "app_data.db"
    connection = sqlite3.connect(database)
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE global_settings (id, run_as_admin, run_on_startup, obs_exe_path DEFAULT '', obs_launch_hidden DEFAULT 1)")
    connection.execute("INSERT INTO global_settings (id,run_as_admin,run_on_startup) VALUES (1, 1, 0)")
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
    connection.execute("CREATE TABLE global_settings (id,run_as_admin,run_on_startup, obs_exe_path DEFAULT '', obs_launch_hidden DEFAULT 1)")
    connection.execute("INSERT INTO global_settings (id,run_as_admin,run_on_startup) VALUES (1,0,1)")
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


@pytest.mark.parametrize("mode", ["status", "power", "error"])
def test_control_json_preserves_unicode_over_a_windows_code_page(monkeypatch, mode):
    import io
    import sys
    import homework_helper_service

    message = "권한 서비스 응답입니다. 🔌"
    payload = {"accepted": True, "status": "ready", "message": message}
    def status(_client):
        if mode == "error":
            raise PrivilegeServiceUnavailable(message)
        return payload
    def power(client, action):
        reply = dict(payload, status="accepted", action=action)
        client._before_ack(reply)
        return reply
    monkeypatch.setattr(HostPrivilegeClient, "status", status)
    monkeypatch.setattr(HostPrivilegeClient, "control_power", power)
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp949", write_through=True)
    monkeypatch.setattr(sys, "stdout", stream)
    args = ["--control", "power", "sleep"] if mode == "power" else ["--control", "status"]
    assert homework_helper_service.main(args) == (1 if mode == "error" else 0)
    received = json.loads(raw.getvalue().decode("utf-8"))
    assert received["message"] == message
    assert received["accepted"] is (mode != "error")


def test_obs_logon_launch_is_independent_of_disabled_gui_and_is_not_reopened(startup_system):
    controller, backend, repository, clock, errors = startup_system
    repository.snapshot = replace(repository.snapshot, settings=SettingsSnapshot(False, False, r"C:\OBS\obs64.exe", True))
    launches = []
    backend.launch_obs = lambda *args: launches.append(args) or {"accepted":True,"pid":101}
    controller.on_session_change("logon",4)
    controller.process_session_events()
    controller.on_session_change("logon",4)
    controller.process_session_events()
    controller.seed_logged_on_sessions()
    controller.process_session_events()
    assert len(launches) == 1 and backend.effects == [] and not errors


def test_obs_failure_does_not_block_gui_startup(startup_system):
    controller, backend, repository, clock, errors = startup_system
    def fail(*args): raise PermissionError("no elevated token")
    backend.launch_obs = fail
    controller.on_session_change("logon",4)
    controller.process_session_events()
    assert len(backend.effects) == 1 and len(errors) == 1


def test_power_rechecks_logon_before_native_effect(system):
    controller, backend, repository, caller = system
    reply = controller.handle({"operation":"power","action":"restart"}, replace(caller, session_id=0))
    backend.session = None
    with pytest.raises(RequestDenied): reply.after_send()
    assert backend.effects == []


def test_app_token_retry_does_not_relaunch_successful_obs(startup_system):
    controller, backend, repository, clock, errors = startup_system
    obs=[]; app=[]
    backend.launch_obs = lambda *args:obs.append(args) or {"accepted":True,"pid":101}
    def start(session):
        app.append(session)
        if len(app) == 1:
            error = OSError("token preparing"); error.winerror=1008; raise error
        return {"accepted":True,"pid":100}
    backend.startup=start
    controller.on_session_change("logon",4); controller.process_session_events()
    clock[0]=1; controller.process_session_events()
    assert len(obs)==1 and len(app)==2 and not errors


class _ObservedOBSQueue(SimpleQueue):
    def __init__(self):
        super().__init__()
        self.queued = Event()

    def put(self, request):
        super().put(request)
        self.queued.set()


def _queued_obs_call(controller, caller):
    """Observe IPC enqueue without doing Windows effects or starting the worker."""
    if not isinstance(controller._obs_requests, _ObservedOBSQueue):
        controller._obs_requests = _ObservedOBSQueue()
    queued = controller._obs_requests.queued
    queued.clear()
    replies, errors = [], []
    def request():
        try:
            replies.append(controller.handle({"operation":"launch_obs"}, caller).payload)
        except Exception as error:
            errors.append(error)
    thread = Thread(target=request, daemon=True)
    thread.start()
    assert queued.wait(1), "The caller must enqueue without performing a launch"
    return thread, replies, errors


def test_logon_and_app_requests_have_one_native_obs_owner(system):
    from threading import get_ident
    controller, backend, repository, caller = system
    repository.snapshot = replace(repository.snapshot, settings=SettingsSnapshot(False, False, r"C:\OBS\obs64.exe", True))
    created = []
    alive = [False]
    def launch(*_args):
        existing = alive[0]
        if not existing:
            created.append(get_ident())
            alive[0] = True
        return {"accepted":True, "pid":101, "already_running":existing}
    backend.launch_obs = launch
    controller.on_session_change("logon", 4)
    thread, replies, errors = _queued_obs_call(controller, caller)
    controller.process_session_events()
    thread.join(1)
    assert not thread.is_alive() and not errors and replies[0]["pid"] == 101
    assert created == [get_ident()] and backend.effects == []
    # OBS closed: observations, duplicate logon and service recovery cannot reopen it.
    alive[0] = False
    controller.handle({"operation":"status"}, caller)
    controller.on_session_change("logon", 4)
    controller.process_session_events()
    controller.seed_logged_on_sessions()
    controller.process_session_events()
    assert len(created) == 1
    # A new app-start/manual request is an allowed new trigger.
    thread, replies, errors = _queued_obs_call(controller, caller)
    controller.process_session_events()
    thread.join(1)
    assert not errors and replies[0]["pid"] == 101 and len(created) == 2


@pytest.mark.parametrize("cancel_reason", ["session", "logoff", "read_logoff", "stop", "read_stop", "deadline", "read_deadline"])
def test_obs_request_cancellation_prevents_late_native_launch(startup_system, cancel_reason):
    controller, backend, repository, clock, _errors = startup_system
    caller = Caller(10, OWNER, 4, str(INSTALL / "homework_helper.exe"), "logon-a")
    created = []
    backend.launch_obs = lambda *args: created.append(args) or {"accepted":True,"pid":101}
    thread, replies, errors = _queued_obs_call(controller, caller)
    stop = Event()
    if cancel_reason == "session":
        backend.session = replace(backend.session, logon_id="logon-b")
    elif cancel_reason == "stop":
        stop.set()
    elif cancel_reason == "deadline":
        clock[0] = 4
    elif cancel_reason == "logoff":
        controller.on_session_change("logoff", 4)  # Native token enumeration can lag this event.
    else:
        original_read = repository.read
        def delayed_read(*args, **kwargs):
            if cancel_reason == "read_logoff":
                controller.on_session_change("logoff", 4)
            elif cancel_reason == "read_stop":
                stop.set()
            else:
                clock[0] = 4
            return original_read(*args, **kwargs)
        repository.read = delayed_read
    controller.process_session_events(stop)
    thread.join(1)
    controller.process_session_events(stop)
    assert not thread.is_alive() and errors and not replies and not created


def test_obs_ipc_times_out_within_existing_pipe_limit_and_is_not_executed_later(system):
    import time
    controller, backend, repository, caller = system
    created = []
    backend.launch_obs = lambda *args:created.append(args) or {"accepted":True,"pid":101}
    started = time.monotonic()
    thread, replies, errors = _queued_obs_call(controller, caller)
    thread.join(4.8)
    assert not thread.is_alive() and isinstance(errors[0], TimeoutError) and not replies
    assert time.monotonic() - started < 5
    controller.process_session_events()
    assert not created and repository.reads == 0


def test_unknown_started_obs_result_is_not_retried_and_next_request_reuses_process(system):
    controller, backend, _repository, caller = system
    entered, release = Event(), Event()
    created = []
    def launch(*_args):
        if not created:
            created.append(101)
            entered.set()
            assert release.wait(6)
            return {"accepted":True,"pid":101}
        return {"accepted":True,"pid":101,"already_running":True}
    backend.launch_obs = launch
    caller_thread, replies, errors = _queued_obs_call(controller, caller)
    worker = Thread(target=controller.process_session_events, daemon=True)
    worker.start()
    assert entered.wait(1)
    try:
        caller_thread.join(4.8)
        assert not caller_thread.is_alive() and isinstance(errors[0], TimeoutError) and not replies
    finally:
        release.set()
        worker.join(1)
    assert not worker.is_alive() and created == [101]
    next_thread, replies, errors = _queued_obs_call(controller, caller)
    controller.process_session_events()
    next_thread.join(1)
    assert not errors and replies[0]["already_running"] and created == [101]
