"""명조 연결과 읽기 전용 preview의 작업 수명·저장 권한을 검증한다."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from src.data.data_models import ManagedProcess
from src.gui.dialogs import ProcessDialog
from src.utils.resource_tracking import GameResourceSnapshot


pytestmark = pytest.mark.usefixtures("wuwa_config_memory")
KEY = "waveplate"
OTHER_KEY = "waveplate@Asia@799900002"


@pytest.fixture
def gui(monkeypatch, wuwa_config_memory):
    import src.utils.game_preset_manager as preset_module
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(preset_module, "GamePresetManager", lambda: SimpleNamespace(get_all_presets=lambda: []))
    class Work(QObject):
        result_ready = Signal(object)
        error_ready = Signal(object)
        def __init__(self):
            super().__init__()
            self.submitted, self.invalidated = [], []
        def submit_telemetry(self, key, function, *args):
            self.submitted.append((key, function, args))
            return len(self.submitted)
        def invalidate_telemetry(self, key):
            self.invalidated.append(key)
    work = Work()
    requests, popups = [], []
    parent = QWidget()
    process = ManagedProcess(id="wuwa", name="명조", monitoring_path="/fixture/wuwa.exe", launch_path="/fixture/wuwa.exe",
                             resource_tracking_enabled=True, resource_provider="wuwa", resource_key=KEY,
                             resource_current=239, resource_max=240, resource_reserve_current=7, resource_reserve_max=480)
    parent.data_manager = SimpleNamespace(get_process_by_id=lambda pid: process if pid == process.id else None)
    parent._work_coordinator = work
    parent._resource_reconcilers = {
        "wuwa": SimpleNamespace(request_refresh=lambda pid, callback: requests.append((pid, callback)) or True),
    }
    monkeypatch.setattr(QMessageBox, "information", lambda *args: popups.append(args[1:]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: popups.append(args[1:]))
    dialog = ProcessDialog(parent, existing_process=process)
    state = SimpleNamespace(app=app, dialog=dialog, process=process, parent=parent, work=work, requests=requests,
                            popups=popups, config=wuwa_config_memory)
    yield state
    dialog.reject()
    parent.deleteLater()
    app.processEvents()


def payload(process):
    fetched_at = dt.datetime(2026, 11, 19, 1, tzinfo=dt.timezone.utc).timestamp()
    row = {**process.to_dict(), "resource_current": 239, "resource_max": 240,
           "resource_updated_at": fetched_at - 360,
           "resource_reserve_current": 120, "resource_reserve_max": 480}
    return {"process_id": "wuwa", "observation_succeeded": True, "provider_status": "ok",
            "fetched_at": fetched_at, "process_row": row}


def test_registered_wuwa_query_uses_existing_writer_queue_and_never_edits_shared_values(gui):
    before = gui.process.to_dict()
    gui.dialog._test_stamina_connection()
    assert len(gui.requests) == 1 and gui.requests[0][0] == "wuwa"
    assert gui.work.submitted == [] and gui.process.to_dict() == before
    gui.requests[0][1](payload(gui.process))
    assert "저장" in gui.popups[0][1] and gui.process.to_dict() == before
    assert "웨이브플레이트: 240 / 240" in gui.popups[0][1]


@pytest.mark.parametrize("change", ["close", "account", "target"])
def test_registered_wuwa_query_discards_late_result_after_identity_or_lifetime_change(gui, change):
    gui.dialog._test_stamina_connection()
    if change == "close":
        gui.dialog.reject()
    elif change == "account":
        gui.config.selected = OTHER_KEY
    else:
        gui.dialog.hoyolab_game_combo.setCurrentIndex(gui.dialog.hoyolab_game_combo.findData("honkai_starrail"))
    gui.requests[0][1](payload(gui.process))
    assert gui.popups == []


def test_unsaved_wuwa_account_uses_read_only_background_preview_and_discards_changed_selection(gui):
    before = gui.process.to_dict()
    gui.dialog.existing_process = None
    gui.dialog._test_stamina_connection()
    assert gui.requests == [] and gui.process.to_dict() == before
    assert gui.work.submitted[0][2] == (KEY,)
    gui.config.selected = OTHER_KEY
    snapshot = GameResourceSnapshot(
        "wuwa", KEY, "웨이브플레이트", 100.0, "ok",
        dt.datetime(2026, 11, 19, 1, tzinfo=dt.timezone.utc),
        current=240, maximum=240, reserve_current=120, reserve_max=480,
    )
    gui.work.result_ready.emit(SimpleNamespace(key=gui.dialog._wuwa_work_key, value=snapshot))
    assert gui.popups == [] and gui.process.to_dict() == before


def test_game_editor_only_selects_resource_target_without_an_account_picker(gui):
    assert not hasattr(gui.dialog, 'wuwa_account_combo')
    assert not hasattr(gui.dialog, 'wuwa_connect_button')
    assert gui.dialog.hoyolab_game_combo.currentData() == 'wuwa_waveplate'


def test_simultaneous_wuwa_workers_use_separate_service_instances_and_close_them(monkeypatch):
    import src.gui.dialogs as dialogs
    import src.services.wuwa as wuwa
    barrier = threading.Barrier(2)
    instances = []
    class Service:
        def __init__(self):
            self.closed = False
            instances.append(self)
        def discover_accounts(self):
            barrier.wait(timeout=2)
            assert len(instances) == 2 and all(not instance.closed for instance in instances)
            barrier.wait(timeout=2)
            return "discover"
        def close(self):
            self.closed = True
    monkeypatch.setattr(wuwa, "WuwaService", Service)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: dialogs._query_wuwa_account(), range(2))) == ["discover", "discover"]
    assert len(instances) == 2 and instances[0] is not instances[1]
    assert all(instance.closed for instance in instances)
