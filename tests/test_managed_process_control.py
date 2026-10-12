"""관리 프로세스의 관측·종료를 사용자 권한과 정확한 OS identity로 검증합니다."""
from types import SimpleNamespace
import os

import psutil
import pytest

import src.core.process_monitor as monitor_module
from src.core.process_monitor import ProcessMonitor, ProcessScanTarget, scan_running_processes, terminate_managed_process
from src.data.data_models import ManagedProcess


class RuntimeProcess:
    def __init__(self, pid=42, path="/games/game.exe", created=123.0, owner="owner", session=1):
        self.pid = pid
        self.path = path
        self.created = created
        self.owner = owner
        self.session = session
        self.terminated = False
        self.info = {"pid": pid, "exe": path, "create_time": created}

    def exe(self):
        return self.path

    def create_time(self):
        return self.created

    def username(self):
        return self.owner

    def is_running(self):
        return True

    def terminate(self):
        self.terminated = True


@pytest.fixture
def game():
    return ManagedProcess(id="game", name="Game", monitoring_path="/games/game.exe", launch_path="/games/game.exe")


def install_processes(monkeypatch, runtime, *, windows=True):
    current = RuntimeProcess(pid=os.getpid())
    processes = {os.getpid(): current, runtime.pid: runtime}
    monkeypatch.setattr(monitor_module, "_is_windows", lambda: windows)
    monkeypatch.setattr(monitor_module.psutil, "Process", lambda pid: processes[pid])
    monkeypatch.setattr(monitor_module.psutil, "process_iter", lambda _attrs: [runtime])
    monkeypatch.setattr(monitor_module, "_windows_process_session", lambda pid: processes[pid].session)


def test_ordinary_scan_does_not_depend_on_privilege_service(monkeypatch):
    runtime = RuntimeProcess()
    install_processes(monkeypatch, runtime)
    client = SimpleNamespace(inspect_managed=lambda _ids: pytest.fail("ordinary scan must not contact service"))

    snapshot = scan_running_processes((ProcessScanTarget("game", runtime.path),), privilege_client=client)

    assert [(item.process_id, item.pid, item.create_time) for item in snapshot.detected] == [("game", 42, 123.0)]


def test_broker_detects_elevated_process_without_writing_data(monkeypatch, game):
    monkeypatch.setattr(monitor_module, "_is_windows", lambda: True)
    monkeypatch.setattr(monitor_module.psutil, "process_iter", lambda _attrs: [])
    calls = []
    client = SimpleNamespace(inspect_managed=lambda ids: calls.append(ids) or {
        "processes": [{"process_id": "game", "pid": 87, "exe": game.monitoring_path, "create_time": 456.0, "session_id": 1}],
        "observed_at": 789.0,
    })

    snapshot = scan_running_processes((ProcessScanTarget(game.id, game.monitoring_path),), run_as_admin=True, privilege_client=client)

    assert calls == [["game"]]
    assert snapshot.observed_at == 789.0
    assert [(item.process_id, item.pid, item.create_time) for item in snapshot.detected] == [("game", 87, 456.0)]
    assert game.last_played_timestamp is None


def test_broker_snapshot_replaces_local_identity_for_same_registered_target(monkeypatch):
    runtime = RuntimeProcess()
    install_processes(monkeypatch, runtime)
    client = SimpleNamespace(inspect_managed=lambda _ids: {
        "processes": [{"process_id": "game", "pid": 43, "exe": runtime.path, "create_time": 124.0}],
        "observed_at": 125.0,
    })

    snapshot = scan_running_processes((ProcessScanTarget("game", runtime.path),), run_as_admin=True, privilege_client=client)

    assert len(snapshot.detected) == 1
    assert snapshot.detected[0].pid == 43
    assert snapshot.detected[0].create_time == 124.0


def test_failed_privilege_scan_preserves_existing_session(monkeypatch, game):
    class UnavailableClient:
        def inspect_managed(self, _ids):
            raise RuntimeError("service unavailable")

    monkeypatch.setattr(monitor_module, "_is_windows", lambda: True)
    monkeypatch.setattr(monitor_module, "_privilege_client", lambda _client=None: UnavailableClient())
    monkeypatch.setattr(monitor_module.psutil, "process_iter", lambda _attrs: [])
    data = SimpleNamespace(managed_processes=[game], global_settings=SimpleNamespace(run_as_admin=True))
    monitor = ProcessMonitor(data)
    monitor.active_monitored_processes[game.id] = {"pid": 42, "start_time_approx": 123.0, "session_id": 7}

    with pytest.raises(RuntimeError, match="service unavailable"):
        monitor.check_and_update_statuses()

    assert monitor.active_monitored_processes[game.id]["session_id"] == 7
    assert game.last_played_timestamp is None


@pytest.mark.parametrize("difference", ["path", "creation", "owner", "session"])
def test_stop_rejects_wrong_runtime_identity(monkeypatch, game, difference):
    runtime = RuntimeProcess()
    if difference == "path":
        runtime.path = "/other/program.exe"
    elif difference == "creation":
        runtime.created = 124.0
    elif difference == "owner":
        runtime.owner = "other-user"
    else:
        runtime.session = 2
    install_processes(monkeypatch, runtime)

    result = terminate_managed_process(game, pid=42, create_time=123.0)

    assert result["accepted"] is False
    assert result["status"] == "not_running"
    assert runtime.terminated is False


def test_stop_ordinary_matching_process_works_without_service(monkeypatch, game):
    runtime = RuntimeProcess()
    install_processes(monkeypatch, runtime)
    client = SimpleNamespace(stop_managed=lambda *_args, **_kwargs: pytest.fail("ordinary stop must not contact service"))

    result = terminate_managed_process(game, pid=42, create_time=123.0, privilege_client=client)

    assert result["accepted"] is True
    assert result["status"] == "accepted"
    assert runtime.terminated is True
    assert result["stopped"][0]["process_id"] == game.id
    assert result["stopped"][0]["create_time"] == 123.0


def test_path_stop_ignores_unreadable_unrelated_system_process(monkeypatch, game):
    runtime = RuntimeProcess()
    install_processes(monkeypatch, runtime)

    class SystemProcess:
        def exe(self):
            raise psutil.AccessDenied(999)

    monkeypatch.setattr(monitor_module.psutil, "process_iter", lambda _attrs: [SystemProcess(), runtime])

    result = terminate_managed_process(game)

    assert result["accepted"] is True
    assert runtime.terminated is True


def test_stop_requires_creation_time_when_pid_is_selected(monkeypatch, game):
    monkeypatch.setattr(monitor_module.psutil, "Process", lambda _pid: pytest.fail("must not read or kill unspecified PID identity"))

    result = terminate_managed_process(game, pid=42)

    assert result["status"] == "identity_required"


def test_stop_handles_disappeared_pid_as_observation_change(monkeypatch, game):
    monkeypatch.setattr(monitor_module, "_is_windows", lambda: False)

    def missing(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(monitor_module.psutil, "Process", missing)
    result = terminate_managed_process(game, pid=42, create_time=123.0)
    assert result["status"] == "not_running"


def test_admin_stop_sends_only_registered_id_and_captured_identity(monkeypatch, game):
    monkeypatch.setattr(monitor_module, "_is_windows", lambda: True)
    monkeypatch.setattr(monitor_module.psutil, "Process", lambda _pid: pytest.fail("admin stop must not use local process control"))
    calls = []
    client = SimpleNamespace(stop_managed=lambda *args, **kwargs: calls.append((args, kwargs)) or {"accepted": True, "status": "stopped"})

    assert terminate_managed_process(game, run_as_admin=True, pid=42, create_time=123.0, privilege_client=client)["accepted"]
    assert calls == [(("game",), {"pid": 42, "create_time": 123.0})]


def test_admin_stop_unavailable_never_falls_back_to_direct_termination(monkeypatch, game):
    monkeypatch.setattr(monitor_module, "_is_windows", lambda: True)
    monkeypatch.setattr(monitor_module.psutil, "Process", lambda _pid: pytest.fail("service errors must not fall back to local termination"))

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("service unavailable")

    with pytest.raises(RuntimeError, match="service unavailable"):
        terminate_managed_process(game, run_as_admin=True, pid=42, create_time=123.0,
                                  privilege_client=SimpleNamespace(stop_managed=unavailable))


@pytest.mark.parametrize("status", ["unknown", "denied", "error"])
def test_service_stop_failure_status_is_shared_by_sidebar_and_remote_api(monkeypatch, game, status):
    from src.host_service.client import PrivilegeServiceError
    from src.api.remote_routes import _terminate_matching_managed_processes
    monkeypatch.setattr(monitor_module, "_is_windows", lambda: True)
    def failed(*_args, **_kwargs):
        raise PrivilegeServiceError("native stop outcome", status=status)
    client = SimpleNamespace(stop_managed=failed)
    monkeypatch.setattr(monitor_module, "_privilege_client", lambda _client: client)
    result = terminate_managed_process(game, run_as_admin=True)
    assert result == {"accepted":False,"status":status,"message":"native stop outcome","stopped":[]}
    remote = _terminate_matching_managed_processes(game, run_as_admin=True)
    assert not remote.accepted and remote.status == status and remote.message == result["message"]


@pytest.mark.parametrize("run_as_admin", [False, True])
def test_accepted_stop_keeps_session_open_until_os_observation_disappears(monkeypatch, game, run_as_admin):
    runtime = RuntimeProcess()
    install_processes(monkeypatch, runtime)
    ended = []
    data = SimpleNamespace(
        managed_processes=[game], global_settings=SimpleNamespace(run_as_admin=run_as_admin),
        end_session=lambda session_id, timestamp: ended.append((session_id, timestamp)) or SimpleNamespace(session_duration=60.0),
        update_process_runtime_state=lambda _process: True,
    )
    monitor = ProcessMonitor(data)
    monitor.active_monitored_processes[game.id] = {
        "pid": runtime.pid, "exe": runtime.path, "start_time_approx": runtime.created, "session_id": 7,
    }
    client = SimpleNamespace(stop_managed=lambda *_args, **_kwargs: {"accepted": True, "status": "accepted"})
    result = terminate_managed_process(game, run_as_admin=run_as_admin, privilege_client=client)
    assert result["accepted"]
    # The same OS process remains during driver/I/O cleanup after termination.
    from src.core.process_monitor import DetectedRuntimeProcess, ProcessScanSnapshot
    observations = [
        ProcessScanSnapshot((DetectedRuntimeProcess(game.id, runtime.pid, monitor._normalize_path(runtime.path), runtime.created),), 180.0),
        ProcessScanSnapshot((), 240.0),
    ]
    monkeypatch.setattr(monitor, "scan_running_processes", lambda _targets: observations.pop(0))
    first = monitor.check_and_update_statuses()
    assert first.stopped == [] and ended == []
    assert monitor.active_monitored_processes[game.id]["session_id"] == 7
    assert game.last_played_timestamp is None
    second = monitor.check_and_update_statuses()
    assert [event.session_id for event in second.stopped] == [7]
    assert len(ended) == 1 and game.id not in monitor.active_monitored_processes
    assert game.last_played_timestamp == ended[0][1]
