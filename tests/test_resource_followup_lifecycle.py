"""종료별 독립 관측·저장 계약을 제공자 구현과 무관한 입력 흐름으로 검증한다."""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
from types import SimpleNamespace

import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

import src.core.resource_reconcile as resource_module
from src.core.hoyolab_reconcile import HoYoStaminaReconcileCoordinator
from src.core.process_monitor import ProcessLifecycleEvent
from src.core.resource_reconcile import NikkeResourceReconcileCoordinator
from src.data.data_models import ManagedProcess


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeTimer:
    def __init__(self, parent):
        self.timeout = SimpleNamespace(connect=lambda receiver: setattr(self, "receiver", receiver), disconnect=lambda: None)
        self.stopped = False

    def setSingleShot(self, single):
        pass

    def setTimerType(self, timer_type):
        pass

    def start(self, delay):
        self.delay = delay

    def stop(self):
        self.stopped = True

    def deleteLater(self):
        self.stopped = True


class QueuedPool:
    def __init__(self):
        self.tasks = []

    def start(self, task):
        self.tasks.append(task)

    def run_next(self):
        self.tasks.pop(0).run()

    def clear(self):
        self.tasks.clear()

    def waitForDone(self, timeout):
        return True


@pytest.fixture(params=["hoyolab", "nikke"])
def tracking(request, monkeypatch, app):
    monkeypatch.setattr(resource_module, "QTimer", FakeTimer)
    clock = SimpleNamespace(monotonic=1000.0)
    monkeypatch.setattr(resource_module.time, "monotonic", lambda: clock.monotonic)
    process = ManagedProcess(
        id="game", name="동일 게임", monitoring_path="/game.exe", launch_path="/game.exe",
        stamina_tracking_enabled=request.param == "hoyolab",
        hoyolab_game_id="honkai_starrail" if request.param == "hoyolab" else None,
        stamina_current=100, stamina_max=240, stamina_updated_at=100.0,
        resource_tracking_enabled=request.param == "nikke",
        resource_provider="nikke_blablalink" if request.param == "nikke" else None,
        resource_key="nikke_outpost_storage" if request.param == "nikke" else None,
        resource_percent=25.0, resource_updated_at=100.0, resource_status="ok",
    )
    manager = SimpleNamespace(
        managed_processes=[process],
        get_process_by_id=lambda pid: next((p for p in manager.managed_processes if p.id == pid), None),
    )
    monitor = SimpleNamespace(active_monitored_processes={})
    calls = []
    observation = SimpleNamespace(
        current=120, max=240, percent=30.0, status="ok", label="전초기지 방어 보상",
        updated_at=dt.datetime.fromtimestamp(1360.0), message="",
    )

    class Service:
        def is_available(self):
            return True

        def is_configured(self):
            return True

        def get_stamina(self, game_id):
            calls.append(("fetch", game_id))
            return observation

        def get_outpost_storage(self):
            calls.append(("fetch", "nikke"))
            return observation

    service = Service()
    current_service = SimpleNamespace(value=service)
    coordinator_type = HoYoStaminaReconcileCoordinator if request.param == "hoyolab" else NikkeResourceReconcileCoordinator
    monkeypatch.setattr(coordinator_type, "_get_service", lambda self: current_service.value)
    coordinator = coordinator_type(manager, monitor)
    coordinator._pool = QueuedPool()
    coordinator._health_pool = QueuedPool()

    class Transport:
        fail_process = False
        fail_session = False

        def update_process_stamina(self, pid, current, maximum, updated_at):
            calls.append(("process", pid, current, maximum, updated_at))
            if self.fail_process:
                raise RuntimeError("current write failed")
            # DB에서 유지한 타이머가 조회 시각과 달라도 그대로 GUI에 전달해야 한다.
            return {"id": pid, "stamina_current": 100, "stamina_max": 240, "stamina_updated_at": 100.0}

        def update_process_resource(self, pid, percent, updated_at, status, label):
            calls.append(("process", pid, percent, updated_at, status, label))
            if self.fail_process:
                raise RuntimeError("current write failed")
            return {"id": pid, "resource_percent": 25.0, "resource_updated_at": 100.0, "resource_status": status, "resource_label": label}

        def update_session_stamina(self, sid, current):
            calls.append(("session", sid, current))
            if self.fail_session:
                raise RuntimeError("session write failed")

        def update_session_resource(self, sid, percent):
            calls.append(("session", sid, percent))
            if self.fail_session:
                raise RuntimeError("session write failed")

    transport = Transport()
    coordinator._transport = transport

    def event(sid, timestamp=1000.0):
        return ProcessLifecycleEvent(
            process_id=process.id, process_name=process.name, session_id=sid, timestamp=timestamp,
            stamina_tracking_enabled=process.stamina_tracking_enabled, hoyolab_game_id=process.hoyolab_game_id,
            stamina_at_end=100, stamina_max=240,
            resource_tracking_enabled=process.resource_tracking_enabled,
            resource_provider=process.resource_provider, resource_key=process.resource_key,
            resource_percent_at_end=25.0,
        )

    state = SimpleNamespace(
        coordinator=coordinator, clock=clock, process=process, manager=manager, monitor=monitor,
        calls=calls, service=service, current_service=current_service, observation=observation,
        transport=transport, event=event, provider=request.param, app=app,
    )
    yield state
    coordinator.shutdown()


def start_registered_job(state, sid=11, timestamp=1000.0):
    state.coordinator.handle_process_stopped(state.event(sid, timestamp))
    job = state.coordinator._jobs[("game", sid)]
    assert job.timer.delay == 0
    state.coordinator._start_attempt(job)
    return job


def test_each_end_session_survives_restart_and_additional_stop(tracking):
    state = tracking
    first = start_registered_job(state, 11)
    state.monitor.active_monitored_processes["game"] = object()
    state.coordinator.handle_process_started(state.event(12))
    second = start_registered_job(state, 12, timestamp=1060.0)
    assert state.coordinator._jobs[("game", 11)] is first
    assert state.coordinator._jobs[("game", 12)] is second

    while state.coordinator._pool.tasks:
        state.coordinator._pool.run_next()
    corrections = [call for call in state.calls if call[0] == "session"]
    assert [call[1] for call in corrections] == [11, 12]
    assert first.timer.delay == 60_000
    assert second.timer.delay == 60_000
    assert not first.cancelled.is_set()


def test_same_values_never_finish_followup_before_all_slots(tracking):
    state = tracking
    job = start_registered_job(state)
    for elapsed in (0.0, 60.0, 120.0):
        state.clock.monotonic = job.registered_at + elapsed
        if elapsed:
            state.coordinator._start_attempt(job)
        state.coordinator._pool.run_next()
        if elapsed < 120:
            assert state.coordinator._jobs[job.key] is job
            assert job.timer.delay == 60_000
    assert state.coordinator._jobs[job.key] is job
    state.clock.monotonic = job.registered_at + 180.0
    state.coordinator._start_attempt(job)
    assert job.key not in state.coordinator._jobs
    assert len([call for call in state.calls if call[0] == "fetch"]) == 3
    assert len([call for call in state.calls if call[0] == "session"]) == 3


def test_registration_clock_not_old_exit_time_controls_window(tracking):
    state = tracking
    job = start_registered_job(state, timestamp=-1000.0)
    state.coordinator._pool.run_next()
    assert any(call[0] == "fetch" for call in state.calls)
    assert job.timer.delay == 60_000


def test_queued_task_expiring_before_actual_start_never_calls_provider(tracking):
    state = tracking
    job = start_registered_job(state)
    state.clock.monotonic += 180.0
    state.coordinator._pool.run_next()
    assert state.calls == []
    assert job.key not in state.coordinator._jobs


def test_request_started_before_deadline_completes_both_writes_after_deadline(tracking, monkeypatch):
    state = tracking
    job = start_registered_job(state)
    fetch = state.coordinator._pool.tasks[0]._fetch

    def delayed_fetch(current_job):
        result = fetch(current_job)
        state.clock.monotonic += 60.0
        return result

    state.coordinator._pool.tasks[0]._fetch = delayed_fetch
    state.clock.monotonic += 179.0
    state.coordinator._pool.run_next()
    assert [call[0] for call in state.calls] == ["fetch", "process", "session"]
    assert job.key not in state.coordinator._jobs


def test_queue_delay_skips_past_slots_without_catchup(tracking):
    state = tracking
    job = start_registered_job(state)
    state.clock.monotonic += 70.0
    state.coordinator._pool.run_next()
    assert job.next_slot == 2
    assert job.timer.delay == 50_000
    state.clock.monotonic += 50.0
    state.coordinator._start_attempt(job)
    state.coordinator._pool.run_next()
    assert state.coordinator._jobs[job.key] is job
    assert job.timer.delay == 60_000
    state.clock.monotonic += 60.0
    state.coordinator._start_attempt(job)
    assert job.key not in state.coordinator._jobs
    assert len([call for call in state.calls if call[0] == "fetch"]) == 2


def test_unchanged_timer_comes_from_canonical_row_not_response_time(tracking):
    state = tracking
    start_registered_job(state)
    state.coordinator._pool.run_next()
    field = "stamina_updated_at" if state.provider == "hoyolab" else "resource_updated_at"
    assert getattr(state.process, field) == 100.0
    assert state.observation.updated_at.timestamp() == 1360.0


def test_current_write_failure_does_not_prevent_own_session_correction(tracking):
    state = tracking
    state.transport.fail_process = True
    start_registered_job(state)
    state.coordinator._pool.run_next()
    corrections = [call for call in state.calls if call[0] == "session"]
    assert len(corrections) == 1
    assert corrections[0][1] == 11
    expected = 119 if state.provider == "hoyolab" else 30.0 - 360 * 100.0 / 86400.0
    assert corrections[0][2] == pytest.approx(expected)


def test_session_failure_preserves_successful_current_write_and_future_attempt(tracking):
    state = tracking
    state.transport.fail_session = True
    state.observation.current = 130
    state.observation.percent = 40.0
    job = start_registered_job(state)
    state.coordinator._pool.run_next()
    assert [call[0] for call in state.calls] == ["fetch", "process", "session"]
    assert state.coordinator._jobs[job.key] is job
    assert job.timer.delay == 60_000


def test_failed_provider_response_keeps_future_slots(tracking):
    state = tracking
    job = start_registered_job(state)
    if state.provider == "hoyolab":
        state.service.is_configured = lambda: False
    else:
        state.observation.status = "auth_required"
        state.observation.percent = None
    state.coordinator._pool.run_next()
    assert not any(call[0] in {"process", "session"} for call in state.calls)
    assert state.coordinator._jobs[job.key] is job
    assert job.timer.delay == 60_000


def test_path_edit_keeps_game_identity_but_provider_change_cancels(tracking):
    state = tracking
    job = start_registered_job(state)
    state.process.monitoring_path = "/other_launcher/game.exe"
    state.coordinator.cancel_changed_targets()
    assert state.coordinator._jobs[job.key] is job
    if state.provider == "hoyolab":
        state.process.hoyolab_game_id = "zenless_zone_zero"
    else:
        state.process.resource_key = "other_resource"
    state.coordinator.cancel_changed_targets()
    state.coordinator._pool.run_next()
    assert state.calls == []
    assert job.cancelled.is_set()


def test_account_service_reset_during_fetch_prevents_writes(tracking):
    state = tracking
    job = start_registered_job(state)
    fetch = state.coordinator._pool.tasks[0]._fetch

    def changing_account(current_job):
        result = fetch(current_job)
        state.current_service.value = object()
        return result

    state.coordinator._pool.tasks[0]._fetch = changing_account
    state.coordinator._pool.run_next()
    assert [call[0] for call in state.calls] == ["fetch"]
    assert job.key not in state.coordinator._jobs


def test_deleted_process_and_shutdown_cancel_pending_writes(tracking):
    state = tracking
    job = start_registered_job(state)
    state.manager.managed_processes.clear()
    state.coordinator.cancel_changed_targets()
    state.coordinator._pool.run_next()
    assert state.calls == []
    assert job.cancelled.is_set()


def test_one_shot_refresh_and_startup_use_same_pool_and_callback_canonical_row(tracking):
    state = tracking
    results = []
    assert state.coordinator.request_refresh("game", results.append)
    assert not state.coordinator.request_refresh("game", results.append)
    state.coordinator.schedule_startup_refreshes()
    assert len(state.coordinator._jobs) == 1
    job = state.coordinator._jobs[("game", None)]
    state.coordinator._start_attempt(job)
    state.coordinator._pool.run_next()
    assert [call[0] for call in state.calls] == ["fetch", "process"]
    assert len(results) == 1
    assert results[0]["process_row"]["id"] == "game"
    assert state.coordinator._jobs == {}


def test_real_provider_pool_keeps_fetch_and_both_writes_contiguous(tracking, monkeypatch):
    state = tracking
    # 시간 제어 시험과 분리하여 실제 스레드 큐의 조회/저장 끼어들기를 검증한다.
    monkeypatch.setattr(resource_module.time, "monotonic", time.perf_counter)
    state.coordinator._pool = QThreadPool()
    state.coordinator._pool.setMaxThreadCount(1)
    entered = threading.Event()
    release = threading.Event()
    original_fetch = state.coordinator._fetch_observation
    fetch_count = 0

    def blocked_fetch(job):
        nonlocal fetch_count
        fetch_count += 1
        if fetch_count == 1:
            entered.set()
            assert release.wait(2)
        return original_fetch(job)

    state.coordinator._fetch_observation = blocked_fetch
    first = start_registered_job(state, 11)
    assert entered.wait(2)
    second = start_registered_job(state, 12)
    release.set()
    assert state.coordinator._pool.waitForDone(2000)
    state.app.processEvents()
    assert [call[0] for call in state.calls] == ["fetch", "process", "session", "fetch", "process", "session"]
    assert [call[1] for call in state.calls if call[0] == "session"] == [11, 12]
    assert first.key in state.coordinator._jobs
    assert second.key in state.coordinator._jobs


def test_early_timer_does_not_add_a_request_before_slot(tracking):
    state = tracking
    job = start_registered_job(state)
    state.coordinator._pool.run_next()
    state.clock.monotonic += 59.999
    state.coordinator._start_attempt(job)
    assert state.coordinator._pool.tasks == []
    assert job.timer.delay in {1, 2}
    assert len([call for call in state.calls if call[0] == "fetch"]) == 1


def test_stored_exit_target_cannot_be_reinterpreted_after_edit(tracking):
    state = tracking
    event = state.event(11)
    if state.provider == "hoyolab":
        state.process.hoyolab_game_id = "zenless_zone_zero"
    else:
        state.process.resource_key = "another_resource"
    state.coordinator.handle_process_stopped(event)
    assert state.coordinator._jobs == {}


def test_stop_without_persisted_session_id_does_not_schedule_correction(tracking):
    state = tracking
    state.coordinator.handle_process_stopped(state.event(None))
    assert state.coordinator._jobs == {}
