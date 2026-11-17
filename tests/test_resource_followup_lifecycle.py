"""종료별 독립 관측·저장 계약을 제공자 구현과 무관한 입력 흐름으로 검증한다."""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("resource_test_isolation")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

import src.core.resource_reconcile as resource_module
from src.core.hoyolab_reconcile import HoYoStaminaReconcileCoordinator
from src.core.process_monitor import ProcessLifecycleEvent
from src.core.resource_reconcile import NikkeResourceReconcileCoordinator, WuwaResourceReconcileCoordinator
from src.data.data_models import ManagedProcess


# Windows CRT는 1970년 초의 naive datetime.timestamp()를 거부할 수 있다.
# 관측 시각은 실제 제공자처럼 현대 epoch를 사용하고 monotonic 기간은 별도로 유지한다.
_TIMESTAMP_BASE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()


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


@pytest.fixture(params=["hoyolab", "nikke", "wuwa"])
def tracking(request, monkeypatch, app):
    monkeypatch.setattr(resource_module, "QTimer", FakeTimer)
    clock = SimpleNamespace(monotonic=1000.0, wall=_TIMESTAMP_BASE + 1000.0)
    monkeypatch.setattr(resource_module.time, "monotonic", lambda: clock.monotonic)
    monkeypatch.setattr(resource_module.time, "time", lambda: clock.wall)
    process = ManagedProcess(
        id="game", name="동일 게임", monitoring_path="/game.exe", launch_path="/game.exe",
        stamina_tracking_enabled=request.param == "hoyolab",
        hoyolab_game_id="honkai_starrail" if request.param == "hoyolab" else None,
        stamina_current=100, stamina_max=240, stamina_updated_at=_TIMESTAMP_BASE + 100.0,
        resource_tracking_enabled=request.param != "hoyolab",
        resource_provider="wuwa" if request.param == "wuwa" else "nikke_blablalink" if request.param == "nikke" else None,
        resource_key="waveplate@Asia@799900001" if request.param == "wuwa" else "nikke_outpost_storage" if request.param == "nikke" else None,
        resource_percent=25.0, resource_updated_at=_TIMESTAMP_BASE + 100.0, resource_status="ok",
        resource_current=60 if request.param == "wuwa" else None,
        resource_max=240 if request.param == "wuwa" else None,
        resource_reserve_current=7 if request.param == "wuwa" else None,
        resource_reserve_max=480 if request.param == "wuwa" else None,
    )
    manager = SimpleNamespace(
        managed_processes=[process],
        get_process_by_id=lambda pid: next((p for p in manager.managed_processes if p.id == pid), None),
    )
    monitor = SimpleNamespace(active_monitored_processes={})
    calls = []
    current_service = SimpleNamespace(value=object())
    coordinator_type = {"hoyolab": HoYoStaminaReconcileCoordinator, "nikke": NikkeResourceReconcileCoordinator,
                        "wuwa": WuwaResourceReconcileCoordinator}[request.param]
    if request.param == "wuwa":
        # 실제 getter가 같은 coordinator identity를 반환하는지도 함께 검증한다.
        import src.services.wuwa as wuwa
        monkeypatch.setattr(wuwa, "_wuwa_service", current_service.value)
    else:
        monkeypatch.setattr(coordinator_type, "_get_service", lambda self: current_service.value)
    coordinator = coordinator_type(manager, monitor)
    coordinator._pool = QueuedPool()
    coordinator._health_pool = QueuedPool()

    class Transport:
        def observe_process_resource(self, pid, sid=None):
            calls.append(("observe", pid, sid))
            return {
                "process_id": pid, "observation_succeeded": True,
                "session_succeeded": sid is not None, "provider_status": "ok", "fetched_at": clock.wall,
                "process_row": {
                    "id": pid, "stamina_current": 100, "stamina_max": 240,
                    "stamina_updated_at": _TIMESTAMP_BASE + 100.0,
                    "resource_percent": 25.0, "resource_updated_at": _TIMESTAMP_BASE + 100.0,
                    "resource_status": "ok", "resource_label": "전초기지 방어 보상",
                    "resource_current": 60, "resource_max": 240,
                    "resource_reserve_current": 7, "resource_reserve_max": 480,
                },
            }


    transport = Transport()
    coordinator._transport = transport

    def event(sid, timestamp=_TIMESTAMP_BASE + 1000.0):
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
        calls=calls, current_service=current_service,
        transport=transport, event=event, provider=request.param, app=app,
    )
    yield state
    coordinator.shutdown()


def start_registered_job(state, sid=11, timestamp=_TIMESTAMP_BASE + 1000.0):
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
    second = start_registered_job(state, 12, timestamp=_TIMESTAMP_BASE + 1060.0)
    assert state.coordinator._jobs[("game", 11)] is first
    assert state.coordinator._jobs[("game", 12)] is second

    while state.coordinator._pool.tasks:
        state.coordinator._pool.run_next()
    assert [call[2] for call in state.calls] == [11, 12]
    assert first.timer.delay == 60_000
    assert second.timer.delay == 60_000
    assert not first.cancelled.is_set()


def test_same_values_never_finish_followup_before_all_slots(tracking):
    state = tracking
    job = start_registered_job(state)
    for elapsed in range(0, 600, 60):
        state.clock.monotonic = job.exit_monotonic + elapsed
        if elapsed:
            state.coordinator._start_attempt(job)
        state.coordinator._pool.run_next()
        if elapsed < 540:
            assert state.coordinator._jobs[job.key] is job
            assert job.timer.delay == 60_000
    assert state.coordinator._jobs[job.key] is job
    state.clock.monotonic = job.exit_monotonic + 600.0
    state.coordinator._start_attempt(job)
    assert job.key not in state.coordinator._jobs
    assert len(state.calls) == 10
    assert all(call == ("observe", "game", 11) for call in state.calls)


def test_old_actual_exit_does_not_gain_new_window_when_registered_late(tracking):
    state = tracking
    state.coordinator.handle_process_stopped(state.event(11, _TIMESTAMP_BASE - 1000.0))
    assert state.coordinator._jobs == {}
    assert state.calls == []


def test_queued_task_expiring_before_actual_start_never_calls_provider(tracking):
    state = tracking
    job = start_registered_job(state)
    state.clock.monotonic += 600.0
    state.coordinator._pool.run_next()
    assert state.calls == []
    assert job.key not in state.coordinator._jobs


def test_request_started_before_deadline_applies_late_api_result(tracking, monkeypatch):
    state = tracking
    job = start_registered_job(state)
    fetch = state.coordinator._pool.tasks[0]._fetch

    def delayed_fetch(current_job):
        result = fetch(current_job)
        state.clock.monotonic += 60.0
        return result

    state.coordinator._pool.tasks[0]._fetch = delayed_fetch
    state.clock.monotonic += 599.0
    state.coordinator._pool.run_next()
    assert state.calls == [("observe", "game", 11)]
    assert job.key not in state.coordinator._jobs


def test_queue_delay_skips_past_slots_without_catchup(tracking):
    state = tracking
    job = start_registered_job(state)
    state.clock.monotonic += 70.0
    state.coordinator._pool.run_next()
    assert job.timer.delay == 50_000
    state.clock.monotonic += 50.0
    state.coordinator._start_attempt(job)
    state.coordinator._pool.run_next()
    assert job.timer.delay == 60_000
    assert state.calls == [("observe", "game", 11)] * 2


def test_unchanged_timer_comes_from_canonical_row_not_response_time(tracking):
    state = tracking
    start_registered_job(state)
    state.coordinator._pool.run_next()
    field = "stamina_updated_at" if state.provider == "hoyolab" else "resource_updated_at"
    assert getattr(state.process, field) == _TIMESTAMP_BASE + 100.0
    assert state.clock.wall != getattr(state.process, field)








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


def test_account_service_reset_during_fetch_ignores_late_projection(tracking):
    state = tracking
    job = start_registered_job(state)
    fetch = state.coordinator._pool.tasks[0]._fetch

    def changing_account(current_job):
        result = fetch(current_job)
        state.current_service.value = object()
        if state.provider == "wuwa":
            import src.services.wuwa as wuwa
            wuwa._wuwa_service = state.current_service.value
        return result

    state.coordinator._pool.tasks[0]._fetch = changing_account
    state.coordinator._pool.run_next()
    assert state.calls == [("observe", "game", 11)]
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
    assert state.calls == [("observe", "game", None)]
    assert len(results) == 1
    assert results[0]["process_row"]["id"] == "game"
    assert state.coordinator._jobs == {}


def test_real_provider_pool_keeps_api_operations_contiguous(tracking, monkeypatch):
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
    assert state.calls == [("observe", "game", 11), ("observe", "game", 12)]
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
    assert state.calls == [("observe", "game", 11)]


def test_stored_exit_target_cannot_be_reinterpreted_after_edit(tracking):
    state = tracking
    event = state.event(11)
    if state.provider == "hoyolab":
        state.process.hoyolab_game_id = "zenless_zone_zero"
    else:
        state.process.resource_key = "another_resource"
    state.coordinator.handle_process_stopped(event)
    assert state.coordinator._jobs == {}


def test_unpersisted_exit_skips_periodic_but_preserves_manual_current_refresh(tracking):
    state = tracking
    state.coordinator.mark_process_stopped(state.event(None))
    state.coordinator.request_periodic_refreshes()
    assert state.coordinator._jobs == {}
    assert state.coordinator.request_refresh("game")
    state.coordinator._start_attempt(state.coordinator._jobs[("game", None)])
    state.coordinator._pool.run_next()
    assert state.calls == [("observe", "game", None)]
    state.clock.monotonic += 600
    state.coordinator.expire_exit_windows()
    state.coordinator.request_periodic_refreshes()
    assert state.coordinator._jobs[("game", None)].periodic


def _periodic_window(start, coordinators):
    from src.gui.main_window import MainWindow
    window = SimpleNamespace(
        _shutting_down=False, _beholder_restore_runtime_suspended=False,
        _hoyolab_reconcile=coordinators[0], _nikke_resource_reconcile=coordinators[1],
        _wuwa_resource_reconcile=coordinators[2] if len(coordinators) > 2 else coordinators[1],
        _resource_monitoring_slot=MainWindow._resource_monitoring_slot,
        _last_resource_monitoring_slot=MainWindow._resource_monitoring_slot(start),
    )
    return window, lambda now: MainWindow._maybe_refresh_periodic_resources(window, now)


def test_kst_half_hour_slots_are_fixed_and_duplicate_ticks_do_not_repeat(resource_test_isolation):
    kst = dt.timezone(dt.timedelta(hours=9))
    start = dt.datetime(2026, 11, 17, 10, 17, tzinfo=kst)
    calls = []
    owner = SimpleNamespace(expire_exit_windows=lambda: None, request_periodic_refreshes=lambda: calls.append(1))
    _, tick = _periodic_window(start, (owner, owner))
    tick(start)
    assert calls == []
    tick(start.replace(minute=30))
    tick(start.replace(minute=30, second=45))
    assert len(calls) == 3  # 세 제공자 각각 한 번
    tick(start.replace(minute=47))
    assert len(calls) == 3
    tick(start.replace(hour=11, minute=0))
    assert len(calls) == 6


def test_kst_schedule_has_48_daily_slots_even_with_utc_input(resource_test_isolation):
    kst = dt.timezone(dt.timedelta(hours=9))
    midnight = dt.datetime(2026, 11, 17, tzinfo=kst)
    calls = []
    owner = SimpleNamespace(expire_exit_windows=lambda: None, request_periodic_refreshes=lambda: calls.append(1))
    _, tick = _periodic_window(midnight - dt.timedelta(minutes=1), (owner, owner))
    for minute in range(0, 24 * 60, 30):
        tick((midnight + dt.timedelta(minutes=minute)).astimezone(dt.timezone.utc))
    assert len(calls) == 48 * 3


def test_game_end_1025_skips_1030_without_catchup_then_resumes_1100(tracking):
    state = tracking
    kst = dt.timezone(dt.timedelta(hours=9))
    start = dt.datetime(2026, 11, 17, 10, 25, tzinfo=kst)
    other = SimpleNamespace(expire_exit_windows=lambda: None, request_periodic_refreshes=lambda: None)
    _, tick = _periodic_window(start, (state.coordinator, other))
    state.coordinator.mark_process_stopped(state.event(None))
    state.clock.monotonic += 300
    tick(start.replace(minute=30))
    assert state.coordinator._jobs == {}
    state.clock.monotonic += 300
    tick(start.replace(minute=35))
    assert state.coordinator._jobs == {}
    state.clock.monotonic += 1500
    tick(start.replace(hour=11, minute=0))
    assert state.coordinator._jobs[("game", None)].periodic


def test_delayed_end_save_uses_actual_exit_deadline_and_next_fixed_slot(tracking):
    state = tracking
    end = state.clock.wall
    state.clock.monotonic += 450
    state.clock.wall += 450
    job = start_registered_job(state, timestamp=end)
    state.coordinator._pool.run_next()
    assert job.timer.delay == 30_000
    state.clock.monotonic += 150
    state.clock.wall += 150
    state.coordinator._start_attempt(job)
    assert job.key not in state.coordinator._jobs
    assert state.calls == [("observe", "game", 11)]


def test_each_game_and_latest_exit_window_bound_periodic_suppression(tracking):
    state = tracking
    other = ManagedProcess.from_dict({**state.process.to_dict(), "id": "other"})
    state.manager.managed_processes.append(other)
    first_end = state.clock.wall
    state.coordinator.mark_process_stopped(state.event(None, first_end))
    state.clock.monotonic += 300
    state.clock.wall += 300
    state.coordinator.mark_process_stopped(state.event(None, state.clock.wall))
    state.clock.monotonic += 300
    state.clock.wall += 300
    state.coordinator.request_periodic_refreshes()
    assert ("game", None) not in state.coordinator._jobs
    assert state.coordinator._jobs[("other", None)].periodic
    state.clock.monotonic += 300
    state.clock.wall += 300
    state.coordinator.expire_exit_windows()
    state.coordinator.request_periodic_refreshes()
    assert state.coordinator._jobs[("game", None)].periodic


def test_periodic_waiting_before_stop_skips_api_but_manual_still_runs(tracking):
    state = tracking
    state.coordinator.request_periodic_refreshes()
    periodic = state.coordinator._jobs[("game", None)]
    state.coordinator._start_attempt(periodic)
    state.coordinator.mark_process_stopped(state.event(None))
    state.coordinator._pool.run_next()
    assert state.calls == []
    assert periodic.key not in state.coordinator._jobs
    assert state.coordinator.request_refresh("game")
    state.coordinator._start_attempt(state.coordinator._jobs[("game", None)])
    state.coordinator._pool.run_next()
    assert state.calls == [("observe", "game", None)]
