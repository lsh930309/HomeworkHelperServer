"""OBS user flows with injected IPC and WebSocket; no real OBS/service/network."""

import os
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
        self.directory = "C:/Fixture/OBS"

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
    def get_record_directory(self): return self.directory
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
    monkeypatch.setattr(recording, "read_obs_connection", lambda:{"host":"localhost","port":1234,"password":"fixture"})
    monkeypatch.setattr(recording, "read_obs_output_directory", lambda:"C:/Fixture/OBS")
    monkeypatch.setattr(recording, "find_obs_executable", lambda:"C:/Fixture/obs64.exe")
    monkeypatch.setattr(recording, "OBSClient", FakeOBS)
    monkeypatch.setattr(recording.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(HostPrivilegeClient, "launch_obs",
                        lambda self:calls.append(get_ident()) or {"accepted":True,"pid":101,"already_running":True})
    return recording.RecordingManager(), calls


def settings(enabled):
    return SimpleNamespace(recording_enabled=enabled, run_on_startup=False)


def finish(manager):
    for _ in range(3):
        thread = manager._connect_thread
        if thread is None:
            return
        thread.join(1)
        assert not thread.is_alive()
    assert manager._connect_thread is None


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


@pytest.mark.parametrize("port,password", [(4456,"fixture"),(1234,"new-fixture")])
def test_obs_owned_connection_changes_apply_on_explicit_reconnect(isolated_obs, monkeypatch, port, password):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    monkeypatch.setattr(recording,"read_obs_connection",lambda:{"host":"localhost","port":port,"password":password})
    manager.reconnect(); finish(manager)
    connections = [c[1] for c in manager._client.calls if c[0] == "connect"]
    assert connections[-1] == {"host":"localhost","port":port,"password":password}
    assert len(launches)==2 and manager.get_state()=="idle"
    assert not any(c[0] in ("record","stop_record") for c in manager._client.calls)


def test_process_metadata_does_not_replace_an_unchanged_connection(isolated_obs):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    changed = settings(True); changed.obs_launch_hidden = False
    manager.apply_settings(changed); finish(manager)
    assert len(launches) == 1 and len(manager._client.calls) == 1


def test_reconnection_and_disable_preserve_the_ongoing_obs_recording(isolated_obs, monkeypatch):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    manager._client.record_status = {"outputActive": True, "outputDuration": 123000}
    monkeypatch.setattr(recording,"read_obs_connection",lambda:{"host":"localhost","port":4456,"password":"fixture"})
    manager.reconnect(); finish(manager)
    assert manager.get_state() == "recording" and manager.get_elapsed_sec() >= 123
    manager.apply_settings(settings(False)); finish(manager)
    assert not manager._client.connected and manager.get_state() == "obs_offline"
    assert manager._client.record_status["outputActive"] is True
    assert not any(c[0] in ("record", "stop_record") for c in manager._client.calls)
    assert len(launches) == 2


@pytest.mark.parametrize("disable", [False, True])
def test_recording_enable_changes_during_connection_use_only_latest_value(isolated_obs, monkeypatch, disable):
    manager, launches = isolated_obs
    entered, release = Event(), Event()
    connect = manager._client.connect
    def blocked(**kwargs):
        if kwargs["port"] == 1234:
            entered.set(); assert release.wait(2)
        return connect(**kwargs)
    monkeypatch.setattr(manager._client, "connect", blocked)
    manager.prepare_for_startup(settings(True)); assert entered.wait(1)
    manager.apply_settings(settings(False))
    manager.apply_settings(settings(not disable))
    release.set(); finish(manager)
    ports = [c[1]["port"] for c in manager._client.calls if c[0] == "connect"]
    assert ports == [1234]
    assert manager.get_state() == ("obs_offline" if disable else "idle")
    assert len(launches) == 1


def test_disable_does_not_receive_a_previous_record_request(isolated_obs, monkeypatch):
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
    manager.apply_settings(settings(False))
    release.set(); finish(manager)
    assert manager.get_state() == "obs_offline"
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
    from src.recording.obs_config_reader import read_obs_output_directory
    monkeypatch.setenv("APPDATA",str(tmp_path))
    obs = tmp_path/'obs-studio'; profile=obs/'basic/profiles/profile-dir'; profile.mkdir(parents=True)
    (obs/'user.ini').write_text('[Basic]\nProfile=Display Name\nProfileDir=profile-dir\n',encoding='utf-8')
    (profile/'basic.ini').write_text('[Output]\nMode='+mode+'\n[SimpleOutput]\nFilePath=simple\n[AdvOut]\nRecFilePath=advanced\n',encoding='utf-8')
    before={p:p.read_bytes() for p in obs.rglob('*') if p.is_file()}
    assert read_obs_output_directory()==expected
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


def test_disable_from_completion_is_consumed_by_the_same_worker(isolated_obs):
    manager, launches = isolated_obs
    states=[]
    def changed(state):
        states.append(state)
        if states==["connecting","idle"]:
            manager.apply_settings(settings(False))
    manager.set_on_state_changed(changed)
    manager.prepare_for_startup(settings(True)); finish(manager)
    assert manager.get_state()=="obs_offline" and not manager._client.connected and len(launches)==1


def test_real_directory_is_refreshed_before_each_record_request(isolated_obs):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    assert manager.get_output_directory()=="C:/Fixture/OBS"
    manager._client.directory="C:/Fixture/NewRecordings"
    seen=[]
    manager.set_on_info_changed(lambda:seen.append(manager.get_output_directory()))
    manager.start_recording(); finish(manager)
    assert seen==["C:/Fixture/NewRecordings"]
    assert manager.get_state()=="recording" and len(launches)==1
    assert manager._client.calls[-1]==("record",)


def test_directory_failure_prevents_recording_and_reports_error(isolated_obs):
    manager, launches = isolated_obs
    manager.prepare_for_startup(settings(True)); finish(manager)
    manager._client.directory=None
    manager.start_recording(); finish(manager)
    assert not any(call[0]=="record" for call in manager._client.calls)
    assert manager.get_state()=="obs_offline" and manager.get_last_error()


def test_viewing_settings_only_reads_and_does_not_reopen_obs(isolated_obs):
    manager, launches = isolated_obs
    manager.apply_settings(settings(False)); finish(manager)
    manager.refresh_info(); finish(manager)
    assert not launches and not any(call[0]=="connect" for call in manager._client.calls)
    assert manager.get_obs_info()["output_dir"]=="C:/Fixture/OBS"
    assert manager.get_state()=="obs_offline"


def test_reconnect_queued_during_read_only_view_is_not_lost(isolated_obs, monkeypatch):
    manager, launches = isolated_obs
    manager._set_settings(settings(True))
    entered, release=Event(), Event()
    def read_directory():
        entered.set(); assert release.wait(2)
        return "C:/Fixture/OBS"
    monkeypatch.setattr(recording,"read_obs_output_directory",read_directory)
    manager.refresh_info(); assert entered.wait(1)
    manager.reconnect()
    release.set(); finish(manager)
    assert len(launches)==1 and manager.get_state()=="idle"
    assert len([call for call in manager._client.calls if call[0]=="connect"])==1


def test_unreadable_obs_settings_fail_without_default_connection(isolated_obs, monkeypatch):
    manager, launches = isolated_obs
    def fail(): raise OSError("OBS fixture read failure")
    monkeypatch.setattr(recording,"read_obs_connection",fail)
    manager.prepare_for_startup(settings(True)); finish(manager)
    assert manager.get_state()=="obs_offline" and manager.get_last_error()=="OBS fixture read failure"
    assert not any(call[0]=="connect" for call in manager._client.calls)


@pytest.mark.parametrize("directory", [None,"",12])
def test_record_directory_response_must_be_a_nonempty_string(monkeypatch,directory):
    client=OBSClient()
    monkeypatch.setattr(client,"_request",lambda name:{"responseData":{"recordDirectory":directory}})
    assert client.get_record_directory() is None and client.get_last_error()


@pytest.mark.parametrize("update", [{"server_enabled":False},{"server_port":"4455"},{"server_port":0},
                                    {"auth_required":"true"},{"server_password":""}])
def test_obs_connection_configuration_error_is_not_a_default(tmp_path,monkeypatch,update):
    import json
    from src.recording.obs_config_reader import read_obs_connection
    monkeypatch.setenv("APPDATA",str(tmp_path))
    path=tmp_path/"obs-studio/plugin_config/obs-websocket/config.json"
    path.parent.mkdir(parents=True)
    values={"server_enabled":True,"server_port":4456,"auth_required":True,"server_password":"fixture"}
    values.update(update); path.write_text(json.dumps(values),encoding="utf-8")
    before=path.read_bytes()
    with pytest.raises((OSError,ValueError)): read_obs_connection()
    assert path.read_bytes()==before


@pytest.mark.parametrize("contents", [None,"{",'{}'])
def test_missing_or_corrupt_obs_configuration_fails_without_writes(tmp_path,monkeypatch,contents):
    from src.recording.obs_config_reader import read_obs_connection
    monkeypatch.setenv("APPDATA",str(tmp_path))
    path=tmp_path/"obs-studio/plugin_config/obs-websocket/config.json"
    if contents is not None:
        path.parent.mkdir(parents=True); path.write_text(contents,encoding="utf-8")
    with pytest.raises(OSError): read_obs_connection()
    assert (path.read_text(encoding="utf-8") if path.exists() else None)==contents


def test_obs_connection_reads_authentication_without_writing_it(tmp_path,monkeypatch):
    import json
    from src.recording.obs_config_reader import read_obs_connection
    monkeypatch.setenv("APPDATA",str(tmp_path))
    path=tmp_path/"obs-studio/plugin_config/obs-websocket/config.json"
    path.parent.mkdir(parents=True)
    values={"server_enabled":True,"server_port":4456,"auth_required":True,"server_password":"fixture"}
    path.write_text(json.dumps(values),encoding="utf-8")
    before=path.read_bytes()
    assert read_obs_connection()=={"host":"localhost","port":4456,"password":"fixture"}
    assert path.read_bytes()==before


@pytest.mark.skipif(os.name != "nt", reason="Widgets screenshot key labels require real Windows")
def test_obs_dialog_saves_only_app_choices_and_preserves_retired_db_values(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication, QLineEdit
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from src.data import models, schemas, crud
    from src.data.data_models import GlobalSettings
    from src.gui.sidebar_settings_dialog import SidebarSettingsDialog
    from src.api.client import ApiClient
    import src.api.client as client_module
    app=QApplication.instance() or QApplication([])
    engine=create_engine("sqlite:///"+str(tmp_path/"app.db"))
    models.Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(crud,"base_dir",str(tmp_path))
    with engine.begin() as db:
        db.execute(text("ALTER TABLE global_settings ADD COLUMN obs_port INTEGER DEFAULT 3999"))
    values=GlobalSettings(recording_enabled=True,obs_launch_hidden=False,obs_watch_output_dir=False,
                          recording_hold_threshold_ms=900,screenshot_save_dir="C:/Fixture/Captures")
    info={"state":"idle","exe_path":"C:/Installed/obs64.exe","output_dir":"C:/OBS/Recordings"}
    reconnects=[]
    dialog=SidebarSettingsDialog(values,obs_info_provider=lambda:info,obs_reconnect=lambda:reconnects.append(True))
    assert not reconnects
    assert dialog._obs_directory_label.text()=="C:/OBS/Recordings"
    assert dialog._obs_status_label.text()=="연결됨"
    assert not hasattr(dialog,"_obs_port_spin") and not hasattr(dialog,"_rec_output_dir_edit")
    updated=dialog.get_updated_settings()
    client=object.__new__(ApiClient); client.base_url="http://injected.invalid"
    client.global_settings=GlobalSettings(); client.latest_beholder_incident=None; client._pending_beholder_overrides={}
    retired={"obs_host","obs_port","obs_password","obs_exe_path","obs_recording_output_dir"}
    assert not (retired & set(updated.to_dict()))
    class Response:
        status_code=200
        def raise_for_status(self): pass
        def json(self): return self.data
    def patch(_url,*,json,headers,timeout):
        assert not (retired & set(json))
        with sessions() as db:
            saved=crud.patch_settings(db,json,actor="sidebar_settings_dialog")
            response=Response()
            response.data=schemas.GlobalSettingsSchema(**{c.name:getattr(saved,c.name) for c in models.GlobalSettings.__table__.columns}).model_dump()
            return response
    monkeypatch.setattr(client_module.requests,"patch",patch)
    assert client.save_global_settings(updated,actor="sidebar_settings_dialog")
    with sessions() as db:
        saved=crud.get_settings(db)
        for field in ("recording_enabled","obs_launch_hidden","obs_watch_output_dir","recording_hold_threshold_ms","screenshot_save_dir"):
            assert getattr(saved,field)==getattr(values,field)==getattr(client.global_settings,field)
        assert db.execute(text("SELECT obs_port FROM global_settings")).scalar()==3999
    fresh=SidebarSettingsDialog(client.global_settings,obs_info_provider=lambda:info)
    assert fresh._rec_hold_spin.value()==900 and not fresh._obs_watch_output_cb.isChecked()
    fresh._rec_hold_spin.setValue(200)
    assert fresh.get_updated_settings().recording_hold_threshold_ms==500
    assert fresh._ss_save_dir_edit.text()=="C:/Fixture/Captures"
    assert fresh._obs_directory_label.text()=="C:/OBS/Recordings"
    # Ordinary user choices must also be reversible back to their initial values.
    fresh._rec_enabled_cb.setChecked(False)
    fresh._obs_launch_hidden_cb.setChecked(True)
    fresh._obs_watch_output_cb.setChecked(True)
    fresh._rec_hold_spin.setValue(800)
    assert client.save_global_settings(fresh.get_updated_settings(),actor="sidebar_settings_dialog")
    with sessions() as db:
        saved=crud.get_settings(db)
        assert (saved.recording_enabled,saved.obs_launch_hidden,saved.obs_watch_output_dir,
                saved.recording_hold_threshold_ms)==(False,True,True,800)
    dialog.close(); fresh.close(); engine.dispose()


def test_settings_view_does_not_erase_a_service_launch_failure(isolated_obs,monkeypatch):
    manager,_=isolated_obs
    def fail(_self): raise PrivilegeServiceError("no elevated token")
    monkeypatch.setattr(HostPrivilegeClient,"launch_obs",fail)
    manager.prepare_for_startup(settings(True)); finish(manager)
    manager.refresh_info(); finish(manager)
    assert manager.get_last_error()=="no elevated token"
    assert manager.get_obs_info()["error"]=="no elevated token"


def test_shutdown_cancels_control_queued_behind_settings_view(isolated_obs,monkeypatch):
    manager,launches=isolated_obs
    manager._set_settings(settings(True))
    entered,release=Event(),Event()
    def read(): entered.set(); assert release.wait(2); return "C:/Fixture/OBS"
    monkeypatch.setattr(recording,"read_obs_output_directory",read)
    manager.refresh_info(); assert entered.wait(1)
    manager.start_recording()
    thread=manager._connect_thread
    manager.shutdown(); release.set(); thread.join(1)
    assert not thread.is_alive() and not launches and manager.get_state()=="obs_offline"
    assert not any(call[0] in ("record","connect") for call in manager._client.calls)
