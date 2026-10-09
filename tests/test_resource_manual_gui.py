"""수동 자원 조회의 등록 ID·미저장 선택·대화 상자 수명 계약을 검증한다."""
from __future__ import annotations

import datetime as dt
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from shiboken6 import Shiboken

from src.data.data_models import ManagedProcess
from src.gui.dialogs import ProcessDialog
import src.services.hoyolab as hoyolab_module
import src.services.nikke as nikke_module
import src.utils.game_preset_manager as preset_module


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=["hoyolab", "nikke"])
def manual(request, monkeypatch, app):
    monkeypatch.setattr(preset_module, "GamePresetManager", lambda: SimpleNamespace(get_all_presets=lambda: []))
    provider = request.param
    process = ManagedProcess(
        id="game", name="게임", monitoring_path="/game.exe", launch_path="/game.exe",
        stamina_tracking_enabled=provider == "hoyolab",
        hoyolab_game_id="honkai_starrail" if provider == "hoyolab" else None,
        stamina_current=100, stamina_max=240, stamina_updated_at=1000.0,
        resource_tracking_enabled=provider == "nikke",
        resource_provider="nikke_blablalink" if provider == "nikke" else None,
        resource_key="nikke_outpost_storage" if provider == "nikke" else None,
        resource_percent=25.0, resource_updated_at=1000.0, resource_status="ok",
    )
    processes = {process.id: process}

    class Manager:
        def get_process_by_id(self, pid):
            return processes.get(pid)

        def update_process_stamina(self, *args):
            raise AssertionError("GUI must not directly write stamina")

        def update_process_resource(self, *args):
            raise AssertionError("GUI must not directly write resource")

    class Coordinator:
        def __init__(self):
            self.requests = []
            self.accept = True

        def request_refresh(self, process_id, callback):
            self.requests.append((process_id, callback))
            return self.accept

        def cancel_changed_targets(self):
            pass

    coordinator = Coordinator()
    parent = QWidget()
    parent.data_manager = Manager()
    parent._hoyolab_reconcile = coordinator
    parent._nikke_resource_reconcile = coordinator
    observation = SimpleNamespace(
        current=120, max=240, recover_time=720, full_time=None,
        percent=35.0, status="ok", label="전초기지 방어 보상", message="",
        updated_at=dt.datetime.fromtimestamp(1300.0),
    )
    provider_calls = []

    class Service:
        def is_available(self):
            return True

        def is_configured(self):
            return True

        def get_stamina(self, game_id):
            provider_calls.append(game_id)
            return observation

        def get_outpost_storage(self):
            provider_calls.append("nikke_outpost_storage")
            return observation

    service = Service()
    monkeypatch.setattr(hoyolab_module, "get_hoyolab_service", lambda: service)
    monkeypatch.setattr(nikke_module, "get_nikke_service", lambda: service)
    popups = []
    monkeypatch.setattr(QMessageBox, "information", lambda owner, title, message: popups.append((title, message)))
    monkeypatch.setattr(QMessageBox, "warning", lambda owner, title, message: popups.append((title, message)))
    dialog = ProcessDialog(parent, existing_process=process)
    target = "honkai_starrail" if provider == "hoyolab" else "nikke_outpost_storage"
    dialog.hoyolab_game_combo.setCurrentIndex(dialog.hoyolab_game_combo.findData(target))

    def result(**overrides):
        row = (
            {"id": "game", "stamina_current": 100, "stamina_max": 240, "stamina_updated_at": 1000.0}
            if provider == "hoyolab" else
            {"id": "game", "resource_percent": 25.0, "resource_updated_at": 1000.0, "resource_status": "ok", "resource_label": observation.label}
        )
        payload = {
            "process_id": "game", "stamina" if provider == "hoyolab" else "snapshot": observation,
            "fetched_at": 1300.0, "process_row": row,
        }
        payload.update(overrides)
        return payload

    state = SimpleNamespace(
        dialog=dialog, process=process, parent=parent, coordinator=coordinator, provider=provider,
        target=target, observation=observation, provider_calls=provider_calls,
        popups=popups, processes=processes, result=result,
    )
    yield state
    if Shiboken.isValid(dialog):
        dialog.reject()
    if Shiboken.isValid(parent):
        parent.deleteLater()
    app.processEvents()


def test_registered_manual_query_uses_provider_queue_and_never_preupdates_shared_cache(manual):
    state = manual
    before = state.process.to_dict()
    state.dialog._test_stamina_connection()
    assert state.provider_calls == []
    assert len(state.coordinator.requests) == 1
    assert state.coordinator.requests[0][0] == state.process.id
    assert not state.dialog.stamina_test_button.isEnabled()
    assert state.process.to_dict() == before
    state.coordinator.requests[0][1](state.result())
    assert state.dialog.stamina_test_button.isEnabled()
    assert state.process.to_dict() == before
    assert "저장되었습니다" in state.popups[0][1]


def test_busy_provider_queue_restores_button_without_sync_fetch(manual):
    state = manual
    state.coordinator.accept = False
    state.dialog._test_stamina_connection()
    assert state.provider_calls == []
    assert state.dialog.stamina_test_button.isEnabled()
    assert not state.dialog._resource_query_pending
    assert state.popups[0][0] == "조회 진행 중"


def test_unsaved_provider_selection_is_read_only_preview(manual):
    state = manual
    before = state.process.to_dict()
    other_target = "nikke_outpost_storage" if state.provider == "hoyolab" else "honkai_starrail"
    state.dialog.hoyolab_game_combo.setCurrentIndex(state.dialog.hoyolab_game_combo.findData(other_target))
    state.dialog._test_stamina_connection()
    assert state.coordinator.requests == []
    assert state.provider_calls == [other_target]
    assert state.process.to_dict() == before
    assert "등록된 자원 값은 변경하지 않았습니다" in state.popups[0][1]


def test_new_registration_preview_never_mutates_existing_data(manual):
    state = manual
    before = state.process.to_dict()
    state.dialog.existing_process = None
    state.dialog._test_stamina_connection()
    assert state.coordinator.requests == []
    assert state.provider_calls == [state.target]
    assert state.process.to_dict() == before


def test_cancelled_dialog_ignores_late_callback(manual):
    state = manual
    state.dialog._test_stamina_connection()
    state.dialog.reject()
    state.coordinator.requests[0][1](state.result())
    assert state.popups == []


def test_destroyed_dialog_ignores_late_callback(manual):
    state = manual
    state.dialog._test_stamina_connection()
    Shiboken.delete(state.dialog)
    state.coordinator.requests[0][1](state.result())
    assert state.popups == []


def test_changed_form_target_ignores_late_callback_and_unlocks_button(manual):
    state = manual
    state.dialog._test_stamina_connection()
    other_target = "nikke_outpost_storage" if state.provider == "hoyolab" else "honkai_starrail"
    state.dialog.hoyolab_game_combo.setCurrentIndex(state.dialog.hoyolab_game_combo.findData(other_target))
    state.coordinator.requests[0][1](state.result())
    assert state.popups == []
    assert state.dialog.stamina_test_button.isEnabled()


def test_changed_canonical_target_ignores_late_callback(manual):
    state = manual
    state.dialog._test_stamina_connection()
    if state.provider == "hoyolab":
        state.process.hoyolab_game_id = "zenless_zone_zero"
    else:
        state.process.resource_key = "another_resource"
    state.coordinator.requests[0][1](state.result())
    assert state.popups == []
    assert state.dialog.stamina_test_button.isEnabled()


def test_wrong_process_result_and_deleted_registration_are_not_presented(manual):
    state = manual
    state.dialog._test_stamina_connection()
    state.coordinator.requests[0][1](state.result(process_id="other_game"))
    assert state.popups == []
    state.dialog._test_stamina_connection()
    state.processes.clear()
    state.coordinator.requests[-1][1](state.result())
    assert state.popups == []


def test_lookup_success_and_save_failure_are_reported_separately(manual):
    state = manual
    before = state.process.to_dict()
    state.dialog._test_stamina_connection()
    state.coordinator.requests[0][1](state.result(process_row=None, process_error="DB unavailable"))
    assert "저장 실패: DB unavailable" in state.popups[0][1]
    assert state.process.to_dict() == before
    assert state.dialog.stamina_test_button.isEnabled()


@pytest.mark.parametrize("failed_owner", [None, "hoyo", "nikke", "checkin", "work"])
def test_restore_admission_requires_all_writer_owners_drained(failed_owner, monkeypatch):
    import threading
    import src.gui.main_window as main_window

    calls = []

    class Owner:
        def __init__(self, name):
            self.name = name

        def shutdown(self, *args, **kwargs):
            calls.append((self.name, args, kwargs))
            return self.name != failed_owner

    window = SimpleNamespace(
        _beholder_restore_runtime_suspended=False,
        process_monitor=SimpleNamespace(active_monitored_processes={"game": {"session_id": 1}}),
        _timer_registry=SimpleNamespace(suspend=lambda *args: calls.append(("timers", args))),
        _work_coordinator=Owner("work"),
        _lifecycle_shutdown_event=threading.Event(),
        _hoyolab_reconcile=Owner("hoyo"),
        _nikke_resource_reconcile=Owner("nikke"),
        _daily_checkin=Owner("checkin"),
    )
    window._work_coordinator.invalidate_telemetry = lambda: calls.append(("invalidate",))
    allowed = main_window.MainWindow._suspend_runtime_after_beholder_restore(window)
    assert allowed is (failed_owner is None)
    assert window._beholder_restore_runtime_suspended
    assert window._lifecycle_shutdown_event.is_set()
    assert window.process_monitor.active_monitored_processes == {}
    assert [item[0] for item in calls] == ["timers", "invalidate", "hoyo", "nikke", "checkin", "work"]
    main_window.MainWindow._suspend_runtime_after_beholder_restore(window)
    assert len([item for item in calls if item[0] == "timers"]) == 1


def test_delayed_resource_lifecycle_and_checkin_finish_before_restore_is_admitted(manual, monkeypatch):
    import threading
    import time
    from src.core.daily_checkin_coordinator import DailyCheckInCoordinator
    from src.core.hoyolab_reconcile import HoYoStaminaReconcileCoordinator
    from src.core.resource_reconcile import NikkeResourceReconcileCoordinator
    from src.core.process_monitor import ProcessLifecycleEvent
    from src.gui.work_coordinator import GuiWorkCoordinator
    import src.gui.main_window as main_window

    state = manual
    monkeypatch.setattr(main_window, "_GUI_CLEANUP_DEADLINE_SECONDS", 0.02)
    release = threading.Event()
    resource_started = threading.Event()
    lifecycle_started = threading.Event()
    checkin_started = threading.Event()
    writes = []
    monitor = SimpleNamespace(active_monitored_processes={"game": {"session_id": 11}})

    class SlowService:
        def is_available(self):
            return True

        def is_configured(self):
            return True

        def get_stamina(self, target):
            resource_started.set()
            assert release.wait(2)
            return state.observation

        def get_outpost_storage(self):
            resource_started.set()
            assert release.wait(2)
            return state.observation

    service = SlowService()
    monkeypatch.setattr(hoyolab_module, "get_hoyolab_service", lambda: service)
    monkeypatch.setattr(nikke_module, "get_nikke_service", lambda: service)
    resource_type = HoYoStaminaReconcileCoordinator if state.provider == "hoyolab" else NikkeResourceReconcileCoordinator
    resource = resource_type(state.parent.data_manager, monitor)
    transport = SimpleNamespace(
        update_process_stamina=lambda *args: writes.append("stamina"),
        update_process_resource=lambda *args: writes.append("resource"),
    )
    resource._transport = transport
    assert resource.request_refresh("game")
    resource._start_attempt(resource._jobs[("game", None)])
    assert resource_started.wait(2)

    checkin = DailyCheckInCoordinator(state.parent.data_manager, None)

    def due_run(**kwargs):
        checkin_started.set()
        assert release.wait(2)
        writes.append("checkin")
        return {"logs": []}

    checkin._transport = SimpleNamespace(run_due_daily_checkins=due_run)
    checkin.schedule_startup_check()
    assert checkin_started.wait(2)

    work = GuiWorkCoordinator(max_threads=1)
    window = SimpleNamespace(
        _beholder_restore_runtime_suspended=False,
        process_monitor=monitor,
        _timer_registry=SimpleNamespace(suspend=lambda *args: None),
        _work_coordinator=work,
        _lifecycle_shutdown_event=threading.Event(),
        _lifecycle_session_lock=threading.Lock(),
        _lifecycle_session_ids={},
        _app_instance_id="test-app",
        _daily_checkin=checkin,
    )
    inactive = SimpleNamespace(shutdown=lambda *args: True)
    window._hoyolab_reconcile = resource if state.provider == "hoyolab" else inactive
    window._nikke_resource_reconcile = resource if state.provider == "nikke" else inactive

    def start_session(**kwargs):
        lifecycle_started.set()
        assert release.wait(2)
        writes.append("start")
        return {"id": 11}

    window._background_transport = SimpleNamespace(
        start_session=start_session,
        end_session=lambda **kwargs: writes.append("queued-stop"),
        patch_json=lambda *args, **kwargs: writes.append("queued-runtime"),
    )
    event = ProcessLifecycleEvent(
        process_id="game", process_name="게임", session_id=11, timestamp=1000,
        stamina_tracking_enabled=False, hoyolab_game_id=None,
    )
    start = main_window._LifecycleCommand("start", event, 1, 1000, "instance")
    stop = main_window._LifecycleCommand("stop", event, 1, 1000, "instance")
    work.submit_lifecycle("game", lambda: main_window.MainWindow._persist_lifecycle_command(window, start))
    assert lifecycle_started.wait(2)
    work.submit_lifecycle("game", lambda: main_window.MainWindow._persist_lifecycle_command(window, stop))

    assert main_window.MainWindow._suspend_runtime_after_beholder_restore(window) is False
    assert window._beholder_restore_runtime_suspended
    release.set()
    assert resource.shutdown(2000)
    assert checkin.shutdown(2000)
    assert work.shutdown(deadline_seconds=2)
    assert main_window.MainWindow._suspend_runtime_after_beholder_restore(window) is True
    writes.append("restore")
    state.dialog._resource_dialog_closed = True
    for _ in range(3):
        QApplication.instance().processEvents()
        time.sleep(0.002)
    assert writes[-1] == "restore"
    assert sorted(writes[:-1]) == ["checkin", "start"]
    assert "queued-stop" not in writes
    assert "queued-runtime" not in writes

    # 종료된 자원 timer의 lambda가 owner를 붙잡은 채 DeferredDelete에서
    # owner/child를 함께 소멸시키면 다음 복구 modal event loop가 충돌한다.
    import gc
    from PySide6.QtCore import QEventLoop, QTimer
    window._hoyolab_reconcile = inactive
    window._nikke_resource_reconcile = inactive
    del resource
    gc.collect()
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()


def test_manual_query_after_restore_pause_reports_restart_instead_of_busy(manual):
    state = manual
    state.parent._beholder_restore_runtime_suspended = True
    state.dialog._test_stamina_connection()
    assert state.coordinator.requests == []
    assert state.provider_calls == []
    assert state.popups[0][0] == "재시작 필요"
