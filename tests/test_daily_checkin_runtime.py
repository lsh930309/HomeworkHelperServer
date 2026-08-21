from __future__ import annotations

import ast
import asyncio
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.daily_checkin_singleflight import (
    DailyCheckInAlreadyInFlight,
    DailyCheckInSingleFlight,
    bounded_provider_timeout_seconds,
    monotonic_deadline,
    remaining_deadline_seconds,
)
from src.core import daily_checkin
from src.services.hoyolab import HoYoLabService
from src.services.nikke import NikkeDailyCheckInStatus, NikkeService


class _ConfiguredHoYoLab:
    def is_configured(self):
        return True

    def load_credentials(self):
        return {"ltuid": 1, "ltoken_v2": "token"}


class _ConfiguredNikke:
    def is_configured(self):
        return True

    def load_session(self):
        return {"cookies": {"session_id": "test"}}


def test_hoyolab_sync_bridge_cancels_timed_out_coroutine_without_late_result():
    cancelled = threading.Event()
    completed = threading.Event()

    async def slow_provider_call():
        try:
            await asyncio.sleep(0.2)
            completed.set()
        finally:
            cancelled.set()

    service = HoYoLabService(
        config=_ConfiguredHoYoLab(),
        async_timeout=0.01,
    )

    with pytest.raises(TimeoutError, match="0.01초"):
        service._run_async(slow_provider_call())

    assert cancelled.wait(0.1)
    time.sleep(0.03)
    assert not completed.is_set()


def test_hoyolab_sync_bridge_rejects_running_loop_without_spawning_thread(monkeypatch):
    created_threads: list[str] = []
    original_start = threading.Thread.start

    def tracking_start(thread):
        created_threads.append(thread.name)
        return original_start(thread)

    async def invoke_from_running_loop():
        service = HoYoLabService(config=_ConfiguredHoYoLab())
        coroutine = asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="비동기 provider API를 직접 await"):
            service._run_async(coroutine)
        assert getattr(coroutine, "cr_frame", None) is None

    monkeypatch.setattr(threading.Thread, "start", tracking_start)
    asyncio.run(invoke_from_running_loop())

    assert created_threads == []


def test_hoyolab_timeout_is_preserved_as_existing_network_error_status():
    class SlowClient:
        async def claim_daily_reward(self, *, game, lang):
            await asyncio.sleep(0.2)
            raise AssertionError("cancelled provider call must not finish")

    service = HoYoLabService(
        config=_ConfiguredHoYoLab(),
        async_timeout=0.01,
    )
    service._client = SlowClient()

    results = service.claim_daily_rewards(["honkai_starrail"])

    assert [result.status for result in results] == ["network_error"]
    assert "0.01초" in results[0].message


def test_hoyolab_timeout_cannot_exceed_thirty_seconds():
    service = HoYoLabService(
        config=_ConfiguredHoYoLab(),
        async_timeout=300,
    )

    assert service._async_timeout == 30.0


def test_hoyolab_request_lock_wait_uses_same_operation_deadline():
    service = HoYoLabService(
        config=_ConfiguredHoYoLab(),
        async_timeout=30,
    )
    service._client = object()
    service._request_lock.acquire()
    started_at = time.monotonic()
    try:
        results = service.claim_daily_rewards(
            ["honkai_starrail"],
            timeout_seconds=0.01,
        )
    finally:
        service._request_lock.release()

    assert time.monotonic() - started_at < 0.2
    assert [result.status for result in results] == ["network_error"]
    assert "request lock deadline" in results[0].message


def test_hoyolab_client_lock_wait_uses_same_operation_deadline():
    service = HoYoLabService(
        config=_ConfiguredHoYoLab(),
        async_timeout=30,
    )
    service._client = object()
    locked = threading.Event()
    release = threading.Event()

    def hold_client_lock():
        with service._client_lock:
            locked.set()
            release.wait(1)

    holder = threading.Thread(target=hold_client_lock)
    holder.start()
    assert locked.wait(1)
    try:
        results = service.get_daily_reward_status(
            ["honkai_starrail"],
            timeout_seconds=0.01,
        )
    finally:
        release.set()
        holder.join(timeout=1)

    assert not holder.is_alive()
    assert [result.status for result in results] == ["network_error"]
    assert "client lock deadline" in results[0].message


def test_hoyolab_lock_is_released_when_protected_work_raises():
    service = HoYoLabService(config=_ConfiguredHoYoLab())

    with pytest.raises(RuntimeError, match="provider failed"):
        with service._lock_until(
            service._request_lock,
            service._operation_deadline(1.0),
            "request",
        ):
            raise RuntimeError("provider failed")

    assert service._request_lock.acquire(blocking=False)
    service._request_lock.release()


def test_nikke_each_http_request_timeout_is_capped_at_ten_seconds(monkeypatch):
    observed_timeouts: list[float] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0}

    class FakeSession:
        def __init__(self):
            self.cookies = {}

        def get(self, url, **kwargs):
            observed_timeouts.append(kwargs["timeout"])
            return FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr("src.services.nikke.requests.Session", FakeSession)
    service = NikkeService(config=_ConfiguredNikke(), timeout=60)

    service._get("test")

    assert observed_timeouts == [10.0]


def test_nikke_status_fallback_and_post_share_one_absolute_deadline(monkeypatch):
    observed_timeouts: list[float] = []
    closed_sessions: list[bool] = []
    post_calls: list[str] = []
    monotonic_values = iter((0.0, 8.0, 14.0, 16.0))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0}

    class FakeSession:
        def __init__(self):
            self.cookies = {}

        def get(self, url, **kwargs):
            observed_timeouts.append(kwargs["timeout"])
            return FakeResponse()

        def post(self, url, **kwargs):
            post_calls.append(url)
            return FakeResponse()

        def close(self):
            closed_sessions.append(True)

    parse_calls = 0

    def parse_status(_body, now, *, get_top):
        nonlocal parse_calls
        parse_calls += 1
        if parse_calls == 1:
            return NikkeDailyCheckInStatus("route_error", now)
        return NikkeDailyCheckInStatus("ready", now, task_id="15")

    monkeypatch.setattr("src.services.nikke.requests.Session", FakeSession)
    monkeypatch.setattr("src.services.nikke.time.monotonic", lambda: next(monotonic_values))
    service = NikkeService(config=_ConfiguredNikke(), timeout=60)
    monkeypatch.setattr(service, "_parse_daily_checkin_status", parse_status)

    result = service.claim_daily_checkin(timeout_seconds=15.0)

    assert result.status == "network_error"
    assert "deadline" in result.message
    assert observed_timeouts == [7.0, 1.0]
    assert post_calls == []
    assert closed_sessions == [True, True]
    assert result.raw_debug["post_called"] is False


def test_nikke_operation_timeout_is_capped_at_thirty_seconds(monkeypatch):
    monkeypatch.setattr("src.services.nikke.time.monotonic", lambda: 100.0)
    service = NikkeService(config=_ConfiguredNikke())

    assert service._daily_checkin_deadline(300.0) == 130.0
    assert service._daily_checkin_deadline(5.0) == 105.0


def test_daily_checkin_singleflight_rejects_duplicate_and_releases_cross_thread():
    controller = DailyCheckInSingleFlight()
    lease = controller.acquire_or_raise("run", "hoyolab", "p1", "g1", 100.0)

    with pytest.raises(DailyCheckInAlreadyInFlight) as duplicate:
        controller.acquire_or_raise("run", "hoyolab", "p1", "g1", 100.0)
    assert duplicate.value.code == "daily_checkin_in_flight"

    releaser = threading.Thread(target=lease.release)
    releaser.start()
    releaser.join(timeout=1)
    assert not releaser.is_alive()

    replacement = controller.try_acquire("run", "hoyolab", "p1", "g1", 100.0)
    assert replacement is not None
    replacement.release()
    replacement.release()
    assert controller.snapshot() == ()


def test_daily_checkin_singleflight_finally_release_does_not_block_other_keys():
    controller = DailyCheckInSingleFlight()

    with pytest.raises(RuntimeError, match="provider failed"):
        with controller.acquire_or_raise("run", "hoyolab", "p1", "g1", 100.0):
            other = controller.try_acquire("run", "hoyolab", "p2", "g2", 100.0)
            assert other is not None
            other.release()
            raise RuntimeError("provider failed")

    assert controller.snapshot() == ()
    replacement = controller.try_acquire("run", "hoyolab", "p1", "g1", 100.0)
    assert replacement is not None
    replacement.release()


def test_run_due_deadline_helpers_use_monotonic_remaining_budget():
    deadline = monotonic_deadline(60.0, now=lambda: 100.0)

    assert deadline == 160.0
    assert remaining_deadline_seconds(deadline, now=lambda: 125.5) == 34.5
    assert remaining_deadline_seconds(deadline, now=lambda: 170.0) == 0.0
    assert bounded_provider_timeout_seconds(deadline, 30.0, now=lambda: 125.5) == 30.0
    assert bounded_provider_timeout_seconds(deadline, 30.0, now=lambda: 150.0) == 10.0
    assert bounded_provider_timeout_seconds(deadline, 30.0, now=lambda: 170.0) == 0.0


@dataclass(frozen=True)
class _RunDueTargetSnapshot:
    process_id: str
    process_name: str
    user_preset_id: str | None
    descriptor: object


def _load_run_due_endpoint(namespace):
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "run_due_daily_checkins"
    )
    function.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, "homework_helper.pyw", "exec"), namespace)
    return namespace["run_due_daily_checkins"]


def _load_daily_checkin_endpoint(name, namespace):
    source = Path("homework_helper.pyw").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    function.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, "homework_helper.pyw", "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize(
    ("endpoint_name", "provider_method"),
    [
        ("run_daily_checkin", "execute_daily_checkin"),
        ("probe_daily_checkin_status", "probe_daily_checkin_status"),
    ],
)
def test_single_daily_checkin_deadline_covers_snapshot_provider_and_persistence(
    monkeypatch,
    endpoint_name,
    provider_method,
):
    clock = {"now": 100.0}
    deadline = 130.0
    descriptor = daily_checkin.DAILY_CHECKIN_DESCRIPTORS[daily_checkin.GAME_HONKAI_STARRAIL]
    target = _RunDueTargetSnapshot("process-1", "Game", None, descriptor)
    database_phases = []
    provider_timeouts = []
    recorded_deadlines = []
    controller = DailyCheckInSingleFlight()

    @contextmanager
    def database_session(route_name, **kwargs):
        database_phases.append((route_name, kwargs))
        if route_name.endswith("snapshot"):
            clock["now"] = 112.0
        yield object()

    def provider_call(_descriptor, *, timeout_seconds):
        provider_timeouts.append(timeout_seconds)
        clock["now"] = 129.0
        return daily_checkin.DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status="success",
            attempted_at=time.time(),
        )

    monkeypatch.setattr(daily_checkin, provider_method, provider_call)

    def record_result(_db, _target, _result, *args, **kwargs):
        recorded_deadlines.append(kwargs["deadline"])
        return {"status": "success"}

    namespace = {
        "SINGLE_DAILY_CHECKIN_TOTAL_DEADLINE_SECONDS": 30.0,
        "_database_session": database_session,
        "_daily_checkin_target_snapshot": lambda *_args: target,
        "_record_daily_checkin_result": record_result,
        "_record_daily_checkin_probe": record_result,
        "bounded_provider_timeout_seconds": lambda absolute, maximum: min(
            absolute - clock["now"], maximum
        ),
        "daily_checkin_singleflight": controller,
        "monotonic_deadline": lambda timeout: clock["now"] + timeout,
        "schemas": SimpleNamespace(
            DailyCheckInRunRequest=object,
            DailyCheckInStatusProbeRequest=object,
        ),
    }
    endpoint = _load_daily_checkin_endpoint(endpoint_name, namespace)
    request = SimpleNamespace(process_id="process-1", game_id=descriptor.game_id, trigger="manual")

    assert endpoint(request) == {"status": "success"}
    assert provider_timeouts == [18.0]
    assert recorded_deadlines == [deadline]
    assert [kwargs["deadline"] for _route, kwargs in database_phases] == [deadline, deadline]
    assert controller.snapshot() == ()


def test_run_due_multi_target_deadline_reserves_persistence_and_leaves_no_resources(
    monkeypatch,
):
    controller = DailyCheckInSingleFlight()
    processes = {
        f"process-{index}": SimpleNamespace(
            id=f"process-{index}",
            name=f"Game {index}",
            user_preset_id=daily_checkin.GAME_HONKAI_STARRAIL,
            hoyolab_game_id=None,
            resource_provider=None,
            resource_key=None,
        )
        for index in range(3)
    }
    settings = [
        SimpleNamespace(process_id=process_id, game_id=daily_checkin.GAME_HONKAI_STARRAIL)
        for process_id in processes
    ]

    class FakeCrud:
        @staticmethod
        def get_enabled_daily_checkin_settings(_db):
            return settings

        @staticmethod
        def get_process_by_id(*, db, process_id):
            return processes[process_id]

        @staticmethod
        def get_daily_checkin_logs_for_period(*_args, **_kwargs):
            return []

    database_phases = []

    @contextmanager
    def database_session(route_name, **kwargs):
        database_phases.append((route_name, kwargs))
        yield object()

    provider_calls: list[float] = []

    def execute_provider(descriptor, *, timeout_seconds):
        provider_calls.append(timeout_seconds)
        time.sleep(timeout_seconds + 0.003)
        return daily_checkin.DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status="success",
            attempted_at=time.time(),
            message="claimed",
            post_called=True,
        )

    monkeypatch.setattr(daily_checkin, "execute_daily_checkin", execute_provider)
    started_threads: list[str] = []
    original_thread_start = threading.Thread.start

    def track_thread_start(thread):
        started_threads.append(thread.name)
        return original_thread_start(thread)

    monkeypatch.setattr(threading.Thread, "start", track_thread_start)
    persisted = []

    def record_result(_db, target, result, _trigger, **_kwargs):
        persisted.append((target, result))
        return {
            "process_id": target.process_id,
            "status": result.status,
            "post_called": result.post_called,
        }

    started_at = time.monotonic()
    deadline = started_at + 0.12
    namespace = {
        "RUN_DUE_TOTAL_DEADLINE_SECONDS": 60.0,
        "RUN_DUE_MIN_PERSISTENCE_RESERVE_SECONDS": 5.0,
        "RUN_DUE_MAX_PERSISTENCE_RESERVE_SECONDS": 10.0,
        "RUN_DUE_PERSISTENCE_RESERVE_PER_TARGET_SECONDS": 0.5,
        "_DailyCheckInTargetSnapshot": _RunDueTargetSnapshot,
        "_configure_database_deadline": lambda *_args, **_kwargs: 1.0,
        "_database_session": database_session,
        "_record_daily_checkin_result": record_result,
        "bounded_provider_timeout_seconds": bounded_provider_timeout_seconds,
        "crud": FakeCrud,
        "daily_checkin_singleflight": controller,
        "logger": logging.getLogger("test.run_due"),
        "monotonic_deadline": lambda _timeout: deadline,
        "remaining_deadline_seconds": remaining_deadline_seconds,
        "schemas": SimpleNamespace(DailyCheckInRunDueRequest=object),
        "time": time,
    }
    endpoint = _load_run_due_endpoint(namespace)

    response = endpoint(SimpleNamespace(trigger="deadline-test"))
    completed_at = time.monotonic()

    assert completed_at <= deadline + 0.03
    assert len(provider_calls) == 1
    assert 0.0 < provider_calls[0] <= 0.07
    assert response["attempted"] == 3
    assert response["skipped"] == []
    assert [item["status"] for item in response["logs"]] == [
        "success",
        "network_error",
        "network_error",
    ]
    assert [item["post_called"] for item in response["logs"]] == [True, False, False]
    assert all(
        result.raw_debug == {"deadline_exhausted": True}
        for _target, result in persisted[1:]
    )
    assert [phase for phase, _kwargs in database_phases] == [
        "POST /daily-checkin/run-due snapshot",
        "POST /daily-checkin/run-due persist",
    ]
    assert controller.snapshot() == ()
    assert started_threads == []
