"""OBS user flows with injected IPC and WebSocket; no real OBS/service/network."""

from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from src.host_service.client import HostPrivilegeClient, PrivilegeServiceError
from src.recording import manager as recording
from src.recording.obs_client import OBSClient


class FakeOBS:
    def __init__(self):
        self.connected = False
        self.connect_succeeds = True
        self.calls = []
        self.closed = None
        self.record_changed = None

    def set_on_connection_closed(self, callback): self.closed = callback
    def set_on_record_state_changed(self, callback): self.record_changed = callback
    def is_connected(self): return self.connected
    def get_last_error(self): return "WebSocket unavailable"
    def connect(self, **kwargs):
        self.calls.append(("connect", kwargs))
        self.connected = self.connect_succeeds
        return self.connected
    def start_record(self):
        self.calls.append(("record",))
        self.record_changed(True)
    def stop_record(self): self.calls.append(("stop_record",))
    def disconnect(self):
        self.calls.append(("disconnect",))
        self.connected = False


@pytest.fixture
def isolated_obs(monkeypatch):
    calls = []
    monkeypatch.setattr(recording, "OBSClient", FakeOBS)
    monkeypatch.setattr(recording.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(HostPrivilegeClient, "launch_obs",
                        lambda self:calls.append(get_ident()) or {"accepted":True,"pid":101,"already_running":True})
    return recording.RecordingManager(), calls


def settings(enabled):
    return SimpleNamespace(recording_enabled=enabled, run_on_startup=False,
                           obs_host="isolated.example", obs_port=1234, obs_password="fixture")


def finish(manager):
    manager._connect_thread.join(1)
    assert not manager._connect_thread.is_alive()


@pytest.mark.parametrize("enabled", [False, True])
def test_app_initialization_prepares_once_regardless_of_recording_or_app_autostart(isolated_obs, enabled):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(enabled))
    finish(manager)
    manager.prepare_for_startup(settings(enabled))
    manager.apply_settings(settings(enabled))
    finish(manager)
    assert len(launches) == 1 and launches[0] != get_ident()
    assert [call[0] for call in manager._client.calls] == (["connect"] if enabled else [])
    assert manager.get_state() == ("idle" if enabled else "obs_offline")
    # Enabling recording afterward connects but does not relaunch the process.
    manager.apply_settings(settings(True))
    finish(manager)
    assert len(launches) == 1 and manager.get_state() == "idle"
    assert not any(call[0] == "record" for call in manager._client.calls)


def test_obs_closed_is_offline_and_only_explicit_record_request_relaunches(isolated_obs):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True))
    finish(manager)
    manager._client.connected = False
    manager._client.connect_succeeds = False
    manager._client.closed()
    assert manager.get_state() == "obs_offline" and len(launches) == 1
    manager.apply_settings(settings(True))
    finish(manager)
    assert manager.get_state() == "obs_offline" and len(launches) == 1
    manager._client.connect_succeeds = True
    manager.start_recording()
    finish(manager)
    assert len(launches) == 2 and manager.get_state() == "recording"


def test_websocket_failure_does_not_relaunch_obs_and_manual_reconnect_is_new_trigger(isolated_obs):
    manager, launches = isolated_obs
    manager._client.connect_succeeds = False
    manager.prepare_for_startup(settings(True))
    finish(manager)
    assert len(launches) == 1 and len(manager._client.calls) == 2
    assert manager.get_state() == "obs_offline" and manager.get_last_error() == "WebSocket unavailable"
    manager._client.connect_succeeds = True
    manager.reconnect()
    finish(manager)
    assert len(launches) == 2 and manager.get_state() == "idle"
    assert not any(call[0] == "record" for call in manager._client.calls)


def test_obs_startup_is_off_gui_thread_and_does_not_block_app(isolated_obs, monkeypatch):
    manager, launches = isolated_obs
    entered, release = Event(), Event()
    def launch(_self):
        launches.append(get_ident())
        entered.set()
        assert release.wait(1)
        return {"accepted":True,"pid":101,"already_running":True}
    monkeypatch.setattr(HostPrivilegeClient, "launch_obs", launch)
    manager.prepare_for_startup(settings(False))
    assert entered.wait(1) and manager._connect_thread.is_alive()
    release.set()
    finish(manager)
    assert launches[0] != get_ident()


@pytest.mark.parametrize("enabled", [False, True])
def test_connection_uses_setting_selected_while_obs_preparation_was_pending(isolated_obs, monkeypatch, enabled):
    manager, launches = isolated_obs
    entered, release = Event(), Event()
    def launch(_self):
        launches.append(get_ident())
        entered.set()
        assert release.wait(1)
        return {"accepted":True,"pid":101,"already_running":True}
    monkeypatch.setattr(HostPrivilegeClient, "launch_obs", launch)
    manager.prepare_for_startup(settings(not enabled))
    assert entered.wait(1)
    manager.apply_settings(settings(enabled))
    release.set()
    finish(manager)
    assert len(launches) == 1
    assert [call[0] for call in manager._client.calls] == (["connect"] if enabled else [])


@pytest.mark.parametrize("message", ["service unavailable", "invalid OBS path", "no elevated token", "close non-admin OBS"])
def test_obs_preparation_failure_is_reported_without_retry(isolated_obs, monkeypatch, message):
    manager, launches = isolated_obs
    def fail(_self):
        launches.append(get_ident())
        raise PrivilegeServiceError(message)
    monkeypatch.setattr(HostPrivilegeClient, "launch_obs", fail)
    manager.prepare_for_startup(settings(True))
    finish(manager)
    assert len(launches) == 1 and manager.get_state() == "obs_offline"
    assert manager.get_last_error() == message and manager._client.calls == []


def test_host_app_shutdown_disconnects_only_and_preserves_obs(isolated_obs):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True))
    finish(manager)
    manager.shutdown()
    assert len(launches) == 1 and manager._client.calls[-1] == ("disconnect",)
    assert manager._client.closed is None and manager._client.record_changed is None


def test_real_websocket_close_notifies_offline_only_for_current_connection():
    client = OBSClient()
    current = object()
    client._ws = current
    closed = []
    client.set_on_connection_closed(lambda:closed.append(True))
    client._identified = True
    client._on_close(object(), None, None)
    assert not closed and client.is_connected()
    client._on_close(current, None, None)
    assert closed == [True] and not client.is_connected()
