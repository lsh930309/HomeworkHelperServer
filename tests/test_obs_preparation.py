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
        self.connection_settings = {}
        self.record_status = {"outputActive": False, "outputDuration": 0}

    def set_on_connection_closed(self, callback): self.closed = callback
    def set_on_record_state_changed(self, callback): self.record_changed = callback
    def is_connected(self): return self.connected
    def get_last_error(self): return "WebSocket unavailable"
    def connect(self, **kwargs):
        self.calls.append(("connect", kwargs))
        self.connection_settings = kwargs
        self.connected = self.connect_succeeds
        return self.connected
    def connection_matches(self, **kwargs): return self.connected and self.connection_settings == kwargs
    def get_record_status(self):
        self.record_changed(self.record_status["outputActive"], elapsed_seconds=self.record_status["outputDuration"] / 1000)
        return dict(self.record_status)
    def start_record(self):
        self.calls.append(("record",))
        self.record_status["outputActive"] = True
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
    thread = manager._connect_thread
    if thread is not None:
        thread.join(1)
        assert not thread.is_alive()


@pytest.mark.parametrize("enabled", [False, True])
def test_app_initialization_prepares_once_regardless_of_recording_or_app_autostart(isolated_obs, enabled):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(enabled))
    finish(manager)
    manager.prepare_for_startup(settings(enabled))
    manager.apply_settings(settings(enabled))
    finish(manager)
    assert len(launches) == 1 and launches[0] != get_ident()
    assert [call[0] for call in manager._client.calls if call[0] != "disconnect"] == (["connect"] if enabled else [])
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
    assert len(launches) == 1 and len([c for c in manager._client.calls if c[0] == "connect"]) == 2
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
    assert [call[0] for call in manager._client.calls if call[0] != "disconnect"] == (["connect"] if enabled else [])


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


def test_close_error_is_available_when_offline_notification_arrives():
    client = OBSClient()
    client._ws = object()
    errors = []
    client.set_on_connection_closed(lambda:errors.append(client.get_last_error()))
    client._on_close(client._ws, 4009, "fixture")
    assert errors and "4009" in errors[0]


def test_request_during_thread_handoff_does_not_start_second_worker(isolated_obs):
    manager, launches = isolated_obs
    # The existing lock also covers the interval before Thread.start(): callbacks
    # can synchronously request reconnect when the state becomes connecting.
    manager.set_on_state_changed(lambda state: manager.reconnect() if state == "connecting" else None)
    manager.prepare_for_startup(settings(True))
    finish(manager)
    assert len(launches) == 1 and len(manager._client.calls) == 1


@pytest.mark.parametrize("field,value", [("obs_host", "new.example"), ("obs_port", 4456), ("obs_password", "new-fixture")])
def test_saved_connection_changes_apply_without_launching_or_recording(isolated_obs, field, value):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    changed = settings(True); setattr(changed, field, value)
    manager.apply_settings(changed); finish(manager)
    connections = [c[1] for c in manager._client.calls if c[0] == "connect"]
    assert len(connections) == 2
    assert connections[-1][field.removeprefix("obs_")] == value
    assert len(launches) == 1 and manager.get_state() == "idle"
    assert not any(c[0] in ("record", "stop_record") for c in manager._client.calls)
    manager.apply_settings(changed); finish(manager)
    assert len([c for c in manager._client.calls if c[0] == "connect"]) == 2


def test_process_metadata_does_not_replace_an_unchanged_connection(isolated_obs):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    changed = settings(True); changed.obs_exe_path = "new-path"; changed.obs_launch_hidden = False
    manager.apply_settings(changed); finish(manager)
    assert len(launches) == 1 and len(manager._client.calls) == 1


def test_reconnection_and_disable_preserve_the_ongoing_obs_recording(isolated_obs):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    manager._client.record_status = {"outputActive": True, "outputDuration": 123000}
    changed = settings(True); changed.obs_port = 4456
    manager.apply_settings(changed); finish(manager)
    assert manager.get_state() == "recording" and manager.get_elapsed_sec() >= 123
    manager.apply_settings(settings(False)); finish(manager)
    assert not manager._client.connected and manager.get_state() == "obs_offline"
    assert manager._client.record_status["outputActive"] is True
    assert not any(c[0] in ("record", "stop_record") for c in manager._client.calls)
    assert len(launches) == 1


@pytest.mark.parametrize("disable", [False, True])
def test_settings_saved_during_connection_use_only_the_latest_value(isolated_obs, monkeypatch, disable):
    manager, launches = isolated_obs
    entered, release = Event(), Event()
    connect = manager._client.connect
    def blocked(**kwargs):
        if kwargs["port"] == 1234:
            entered.set(); assert release.wait(2)
        return connect(**kwargs)
    monkeypatch.setattr(manager._client, "connect", blocked)
    manager.prepare_for_startup(settings(True)); assert entered.wait(1)
    changed = settings(True); changed.obs_port = 4456; manager.apply_settings(changed)
    latest = settings(not disable); latest.obs_port = 4457; manager.apply_settings(latest)
    release.set(); finish(manager)
    ports = [c[1]["port"] for c in manager._client.calls if c[0] == "connect"]
    assert ports == ([1234] if disable else [1234, 4457])
    assert manager.get_state() == ("obs_offline" if disable else "idle")
    assert len(launches) == 1


def test_changed_connection_does_not_receive_a_previous_record_request(isolated_obs, monkeypatch):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    manager._client.connected = False
    entered, release = Event(), Event(); connect = manager._client.connect
    def blocked(**kwargs):
        if kwargs["port"] == 1234:
            entered.set(); assert release.wait(2)
        return connect(**kwargs)
    monkeypatch.setattr(manager._client, "connect", blocked)
    manager.start_recording(); assert entered.wait(1)
    latest = settings(True); latest.obs_port = 4456; manager.apply_settings(latest)
    release.set(); finish(manager)
    assert manager._client.connection_settings["port"] == 4456
    assert not any(c[0] == "record" for c in manager._client.calls)


def test_status_failure_does_not_claim_idle_or_relaunch(isolated_obs, monkeypatch):
    manager, launches = isolated_obs
    monkeypatch.setattr(manager._client, "get_record_status", lambda: None)
    manager.prepare_for_startup(settings(True)); finish(manager)
    assert manager.get_state() == "obs_offline" and not manager._client.connected
    assert len(launches) == 1 and len([c for c in manager._client.calls if c[0] == "connect"]) == 1


@pytest.mark.parametrize("phase", ["launch", "connect"])
def test_shutdown_revokes_pending_connection_and_late_completion(isolated_obs, monkeypatch, phase):
    manager, launches = isolated_obs
    entered, release = Event(), Event()
    if phase == "launch":
        def blocked(_self):
            entered.set(); assert release.wait(2)
            return {"accepted": True, "pid": 101, "already_running": True}
        monkeypatch.setattr(HostPrivilegeClient, "launch_obs", blocked)
    else:
        connect = manager._client.connect
        def blocked(**kwargs):
            entered.set(); assert release.wait(2)
            return connect(**kwargs)
        monkeypatch.setattr(manager._client, "connect", blocked)
    states = []; manager.set_on_state_changed(states.append)
    manager.prepare_for_startup(settings(True)); assert entered.wait(1)
    thread = manager._connect_thread
    manager.shutdown(); release.set(); thread.join(1)
    assert not thread.is_alive() and not manager._client.connected
    assert states == ["connecting"]
    assert manager.get_state() == "obs_offline"


def test_record_status_response_and_next_event_are_applied_in_stream_order():
    import json
    client = OBSClient(); ws = object(); client._ws = ws
    client._identified = True
    seen = []; client.set_on_record_state_changed(lambda active, **kw: seen.append((active, kw)))
    response = {"op": 7, "d": {"requestId": "status", "requestType": "GetRecordStatus",
               "requestStatus": {"result": True}, "responseData": {"outputActive": True, "outputDuration": 42000}}}
    ready = Event(); client._pending["status"] = ready
    client._on_message(ws, json.dumps(response))
    client._on_message(ws, json.dumps({"op":5,"d":{"eventType":"RecordStateChanged","eventData":{"outputActive":False}}}))
    assert ready.is_set() and seen == [(True, {"elapsed_seconds": 42}), (False, {})]


def test_disconnect_invalidates_the_socket_and_releases_pending_calls():
    import json
    client = OBSClient(); old = SimpleNamespace(close=lambda: None); client._ws = old; client._identified = True
    seen = []; client.set_on_record_state_changed(seen.append)
    ready = Event(); client._pending["request"] = ready
    client.disconnect()
    client._on_message(old,json.dumps({"op":5,"d":{"eventType":"RecordStateChanged","eventData":{"outputActive":True}}}))
    assert ready.is_set() and not client.is_connected() and seen == []


@pytest.mark.parametrize("status", [None, {}, {"outputActive":False}, {"outputActive":False,"outputDuration":-1}])
def test_invalid_record_status_is_an_error_and_not_a_false_idle_event(status):
    import json
    client = OBSClient(); ws = object(); client._ws = ws
    seen = []; client.set_on_record_state_changed(lambda *args,**kwargs: seen.append(args))
    ready = Event(); client._pending["status"] = ready
    client._on_message(ws,json.dumps({"op":7,"d":{"requestId":"status","requestType":"GetRecordStatus",
                      "requestStatus":{"result":True},"responseData":status}}))
    assert ready.is_set() and client._pending_results["status"] is None and seen == []
    assert client.get_last_error()


@pytest.mark.parametrize("mode,expected", [("Advanced", "advanced"), ("Simple", "simple")])
def test_obs_output_directory_uses_selected_profile_and_current_output_mode(tmp_path,monkeypatch,mode,expected):
    from src.recording.obs_config_reader import read_obs_config
    monkeypatch.setenv("APPDATA",str(tmp_path))
    obs = tmp_path/'obs-studio'; profile=obs/'basic/profiles/profile-dir'; profile.mkdir(parents=True)
    (obs/'user.ini').write_text('[Basic]\nProfile=Display Name\nProfileDir=profile-dir\n',encoding='utf-8')
    (profile/'basic.ini').write_text('[Output]\nMode='+mode+'\n[SimpleOutput]\nFilePath=simple\n[AdvOut]\nRecFilePath=advanced\n',encoding='utf-8')
    before={p:p.read_bytes() for p in obs.rglob('*') if p.is_file()}
    assert read_obs_config()['output_dir']==expected
    assert all(p.read_bytes()==data for p,data in before.items())


def test_rejected_record_command_does_not_report_success():
    import json
    client = OBSClient()
    def send(message):
        request = json.loads(message)["d"]
        client._on_message(ws,json.dumps({"op":7,"d":{"requestId":request["requestId"],
            "requestType":request["requestType"],"requestStatus":{"result":False,"comment":"fixture rejection"}}}))
    ws = SimpleNamespace(send=send); client._ws=ws; client._identified=True
    assert client.start_record() is False and "fixture rejection" in client.get_last_error()


def test_connect_closes_the_previous_socket_before_creating_another(monkeypatch):
    import json
    client=OBSClient(); closed=[]
    old=SimpleNamespace(close=lambda:closed.append("old")); client._ws=old; client._identified=True
    class Socket:
        def __init__(self,*_args,**_kwargs):
            assert closed==["old"]
        def run_forever(self):
            client._on_open(self); client._on_message(self,json.dumps({"op":2,"d":{}}))
        def close(self): closed.append("new")
    monkeypatch.setattr("src.recording.obs_client.websocket.WebSocketApp",Socket)
    assert client.connect(host="isolated.example",port=1234,password="fixture")
    assert client.connection_matches(host="isolated.example",port=1234,password="fixture")
    client.disconnect(); assert closed==["old","new"]
