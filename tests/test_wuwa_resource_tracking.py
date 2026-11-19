"""명조의 canonical 수량과 제한된 종료 세션 보정 권한을 검증한다."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data import crud, models, schemas


pytestmark = pytest.mark.usefixtures("wuwa_config_memory")
END = dt.datetime(2026, 11, 17, 10, tzinfo=dt.timezone.utc).timestamp()
TOKEN = "qa_wuwa_tracking_token_never_output"
OTHER_TOKEN = "qa_wuwa_other_tracking_token_never_output"
ROLE_ID = "799900001"
KEY = "waveplate"
TARGET = ("wuwa", KEY, f"waveplate@Asia@{ROLE_ID}")
OTHER_TARGET = ("wuwa", KEY, "waveplate@Asia@799900002")


@pytest.fixture
def tracked(request, monkeypatch, tmp_path, wuwa_config_memory):
    from src.core.resource_observation import observe_process_resource
    from src.services.wuwa import WuwaService

    if getattr(request, "param", None) == "independent_connections":
        engine = create_engine(f"sqlite:///{tmp_path / 'resource-race.db'}", connect_args={"timeout": 0})
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(crud, "base_dir", str(tmp_path / "backups"))
    state = SimpleNamespace(sessions=sessions, now=END + 60, mono=1000.0, accounts=[TOKEN],
                            role_codes=[], role_calls=[], info_calls=[], sleeps=[], after_role=None,
                            after_info=None, current=120, maximum=240, reserve=80, reserve_max=480)
    with sessions() as db:
        db.add(models.Process(id="wuwa", name="명조", monitoring_path="/fixture/wuwa.exe", launch_path="/fixture/wuwa.exe",
                              resource_tracking_enabled=True, resource_provider="wuwa", resource_key=KEY,
                              resource_current=100, resource_max=240, resource_reserve_current=7, resource_reserve_max=480,
                              resource_percent=None, resource_status="ok", resource_updated_at=END - 60))
        db.add_all([
            models.ProcessSession(id=11, process_id="wuwa", process_name="명조", start_timestamp=END - 3600,
                                  end_timestamp=END, session_duration=3600, resource_percent_at_end=25,
                                  session_status="closed"),
            models.ProcessSession(id=12, process_id="wuwa", process_name="명조", start_timestamp=END - 3000,
                                  end_timestamp=END + 30, session_duration=3030, resource_percent_at_end=20,
                                  session_status="closed"),
        ])
        db.commit()

    class Gateway:
        def read_accounts(self):
            return tuple(state.accounts)

        def post_json(self, operation, payload, timeout):
            if operation == "queryPlayerInfo":
                state.info_calls.append(state.now)
                if state.after_info:
                    state.after_info()
                return 200, {"code": 0, "data": {"Asia": json.dumps({"roleId": ROLE_ID})}}
            assert operation == "queryRole"
            state.role_calls.append(state.now)
            code = state.role_codes.pop(0) if state.role_codes else 200
            if state.after_role:
                state.after_role()
            return 200, {"code": code, "message": TOKEN, "data": {"Asia": json.dumps({"Base": {
                "Energy": state.current, "MaxEnergy": state.maximum,
                "StoreEnergy": state.reserve, "MaxStoreEnergy": state.reserve_max,
                "EnergyRecoverTime": 17, "StoreEnergyRecoverTime": 29,
            }})}}

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds
        state.mono += seconds

    def factory():
        return WuwaService(gateway=Gateway(), clock=lambda: state.now,
                           monotonic=lambda: state.mono, sleep=sleep)

    def observe(session_id=11, *, expected_target=TARGET):
        return observe_process_resource("wuwa", session_id, session_factory=sessions,
                                        expected_target=expected_target,
                                        wuwa_service_factory=factory, clock=lambda: state.now)

    def values():
        with sessions() as db:
            process = db.get(models.Process, "wuwa")
            return (process.resource_current, process.resource_max, process.resource_reserve_current,
                    process.resource_reserve_max, process.resource_percent, process.resource_updated_at,
                    db.get(models.ProcessSession, 11).resource_percent_at_end,
                    db.get(models.ProcessSession, 12).resource_percent_at_end)

    state.observe, state.values = observe, values
    yield state
    engine.dispose()


def test_wuwa_observation_stores_four_quantities_and_only_fixed_session_percentage(tracked):
    result = tracked.observe()
    assert result["observation_succeeded"] is True and result["session_succeeded"] is True
    assert tracked.values() == (120, 240, 80, 480, None, END + 60, 50.0, 20.0)
    assert result["process_row"]["resource_percent"] == 50.0
    assert result["process_row"]["resource_reserve_current"] == 80
    assert TOKEN not in json.dumps(result)


def test_wuwa_periodic_start_or_manual_observation_does_not_rewrite_sessions(tracked):
    result = tracked.observe(None)
    assert result["observation_succeeded"] is True and result["session_succeeded"] is False
    assert tracked.values() == (120, 240, 80, 480, None, END + 60, 25.0, 20.0)


def test_wuwa_request_at_599_can_store_after_600_with_recovery_backcast(tracked):
    tracked.now = END + 599
    tracked.after_role = lambda: setattr(tracked, "now", END + 610)
    result = tracked.observe()
    assert result["session_succeeded"] is True
    assert tracked.role_calls == [END + 599]
    assert tracked.values()[6:] == (pytest.approx(119 / 240 * 100), 20.0)


@pytest.mark.parametrize("elapsed,count_at_end", [(359, 120), (360, 119)])
def test_wuwa_end_backcast_counts_only_complete_recovery_intervals(tracked, elapsed, count_at_end):
    tracked.now = END + elapsed
    result = tracked.observe()
    assert result["session_succeeded"] is True
    assert result["corrected_exit_percent"] == pytest.approx(count_at_end / 240 * 100)
    assert tracked.values()[6:] == (pytest.approx(count_at_end / 240 * 100), 20.0)


def test_wuwa_1005_retry_crossing_600_has_no_new_request_or_session_write(tracked):
    tracked.now = END + 599.8
    tracked.role_codes = [1005, 200]
    before = tracked.values()
    result = tracked.observe()
    assert result.get("expired") is True
    assert result["session_succeeded"] is False
    assert tracked.role_calls == [END + 599.8]
    assert tracked.sleeps == [0.5]
    assert tracked.values() == before


def test_wuwa_account_preparation_does_not_authorize_late_resource_request(tracked):
    tracked.now = END + 599
    tracked.after_info = lambda: setattr(tracked, "now", END + 601)
    before = tracked.values()
    result = tracked.observe()
    assert result.get("expired") is True
    assert tracked.info_calls == [END + 599] and tracked.role_calls == []
    assert tracked.values() == before


@pytest.mark.parametrize('change', ['launcher', 'selected', 'clear'])
def test_wuwa_account_change_discards_late_observation(tracked, wuwa_config_memory, change):
    if change == 'launcher':
        tracked.after_role = lambda: setattr(tracked, "accounts", [OTHER_TOKEN])
    else:
        tracked.after_role = lambda: setattr(wuwa_config_memory, 'selected',
            'waveplate@Asia@799900002' if change == 'selected' else None)
    before = tracked.values()
    result = tracked.observe()
    assert result.get("cancelled") is True
    assert not result["session_succeeded"]
    assert tracked.values() == before
    assert TOKEN not in json.dumps(result) and OTHER_TOKEN not in json.dumps(result)


@pytest.mark.parametrize("changed_account", [False, True])
def test_wuwa_end_observation_requires_original_account_before_provider_access(tracked, wuwa_config_memory, changed_account):
    expected = None
    if changed_account:
        wuwa_config_memory.selected = OTHER_TARGET[2]
        expected = TARGET
    before = tracked.values()
    result = tracked.observe(expected_target=expected)
    assert result.get("cancelled") is True
    assert result["session_succeeded"] is False
    assert tracked.info_calls == tracked.role_calls == []
    assert tracked.values() == before
    assert ROLE_ID not in json.dumps(result)


@pytest.mark.parametrize("tracked", ["independent_connections"], indirect=True)
def test_wuwa_account_switch_cannot_commit_between_validation_and_current_write(tracked, wuwa_config_memory):
    attempts = []

    def attempt_switch(during_write, *_):
        # 현재량 쓰기의 설정 확인이 끝났고 실제 수량을 flush하기 직전이다.
        if not any(isinstance(row, models.Process) for row in during_write.dirty) or attempts:
            return
        attempts.append(wuwa_config_memory.selected)
        with tracked.sessions() as independent:
            with pytest.raises(OperationalError, match="database is locked"):
                crud.configure_wuwa_link(independent, OTHER_TARGET[2])
        assert wuwa_config_memory.selected == TARGET[2]

    event.listen(tracked.sessions, "before_flush", attempt_switch)
    try:
        result = tracked.observe(None)
    finally:
        event.remove(tracked.sessions, "before_flush", attempt_switch)
    assert attempts == [TARGET[2]]
    assert result["process_row"]["resource_current"] == 120

    with tracked.sessions() as db:
        switch = crud.configure_wuwa_link(db, OTHER_TARGET[2])
    assert switch["connected"] is True
    assert wuwa_config_memory.selected == OTHER_TARGET[2]
    assert tracked.values() == (None, None, None, None, None, None, 25.0, 20.0)


@pytest.mark.parametrize("tracked", ["independent_connections"], indirect=True)
def test_wuwa_response_that_reaches_writer_after_account_switch_preserves_cleared_state(tracked, monkeypatch):
    original = crud.update_process_resource
    switched = []

    def apply_after_switch(*args, **kwargs):
        with tracked.sessions() as independent:
            result = crud.configure_wuwa_link(independent, OTHER_TARGET[2])
        switched.append(result["connected"])
        return original(*args, **kwargs)

    monkeypatch.setattr(crud, "update_process_resource", apply_after_switch)
    result = tracked.observe()

    assert tracked.role_calls == [END + 60]
    assert switched == [True]
    assert result.get("cancelled") is True
    assert result["process_row"] is None and result["session_succeeded"] is False
    assert tracked.values() == (None, None, None, None, None, None, 25.0, 20.0)


def test_wuwa_editor_stale_quantities_cannot_overwrite_new_canonical_observation(tracked):
    tracked.observe(None)
    with tracked.sessions() as db:
        saved = crud.update_process(db, "wuwa", schemas.ProcessCreateSchema(
            name="새 이름", monitoring_path="/fixture/new.exe", launch_path="/fixture/new.exe",
            resource_tracking_enabled=True, resource_provider="wuwa", resource_key=KEY,
            resource_current=1, resource_max=2, resource_reserve_current=0, resource_reserve_max=1,
            resource_percent=99, resource_updated_at=1,
        ))
        assert saved.name == "새 이름"
    assert tracked.values() == (120, 240, 80, 480, None, END + 60, 25.0, 20.0)


def test_wuwa_read_projection_uses_count_recovery_in_managed_model(tracked):
    from src.data.data_models import ManagedProcess
    tracked.observe(None)
    with tracked.sessions() as db:
        row = db.get(models.Process, "wuwa")
        payload = schemas.ProcessSchema.model_validate(row).model_dump()
        assert row.resource_percent is None
    runtime = ManagedProcess.from_dict(payload)
    assert runtime.get_resource_percentage(now=END + 60) == 50.0
    assert runtime.get_resource_percentage(now=END + 60 + 359) == 50.0
    assert runtime.get_resource_percentage(now=END + 60 + 360) == pytest.approx(121 / 240 * 100)
    assert runtime.get_resource_percentage(now=END + 86400) == 100.0
    assert runtime.resource_reserve_current == 80


def test_wuwa_progress_api_estimates_full_refill_from_latest_observation(tracked):
    from src.api.remote_routes import _serialize_process

    def progress_at(now):
        with tracked.sessions() as db:
            process = db.get(models.Process, "wuwa")
            return _serialize_process(process, current_dt=dt.datetime.fromtimestamp(now))["progress"]

    tracked.current = 6
    tracked.observe(None)
    first_at = tracked.now
    before = tracked.values()
    first = progress_at(first_at)
    expected_duration = 23 * 3600 + 24 * 60
    assert first["display_text"] == first["gauge_text"] == "6/240"
    assert first["percentage"] == 2.5
    assert first["remaining_seconds"] == first["projection"]["remaining_seconds"] == expected_duration
    assert first["ready_at"] == first["projection"]["ready_at"] == first_at + expected_duration
    assert first["projection"]["strategy"] == "linear_recovery"
    assert first["projection"]["unit"] == "count"
    assert first["projection"]["recovery_seconds_per_unit"] == 360
    assert "overlay_percentage" not in first

    assert progress_at(first_at + 359)["display_text"] == "6/240"
    later = progress_at(first_at + 360)
    assert later["ready_at"] == first["ready_at"]
    assert later["remaining_seconds"] == expected_duration - 360
    assert later["display_text"] == "7/240"
    assert tracked.values() == before

    tracked.now = first_at + 360
    tracked.current = 7
    tracked.observe(None)
    assert tracked.values() == before
    assert progress_at(tracked.now)["ready_at"] == first["ready_at"]

    tracked.now = first_at + 1800
    tracked.current = 8
    tracked.observe(None)
    refreshed = progress_at(tracked.now)
    assert refreshed["display_text"] == "8/240"
    assert refreshed["ready_at"] == tracked.now + (240 - 8) * 360
    assert refreshed["ready_at"] != first["ready_at"]

    elapsed = progress_at(refreshed["ready_at"] + 1)
    assert elapsed["ready_at"] == refreshed["ready_at"]
    assert elapsed["remaining_seconds"] == 0
    assert elapsed["display_text"] == "80/480"
    assert elapsed["resource_current"] == 240
    assert elapsed["projection"]["strategy"] == "static_value"


def test_wuwa_progress_keeps_reserve_overlay_with_full_base(tracked):
    from src.core.process_progress import calculate_process_progress

    tracked.current = 240
    tracked.observe(None)
    with tracked.sessions() as db:
        process = db.get(models.Process, "wuwa")
        progress = calculate_process_progress(process, dt.datetime.fromtimestamp(tracked.now))

    assert progress["display_text"] == progress["gauge_text"] == "80/480"
    assert progress["resource_current"] == 240
    assert progress["overlay_percentage"] == pytest.approx(80 / 480 * 100)
    assert progress["ready_at"] == tracked.now
    assert progress["remaining_seconds"] == 0
    assert progress["projection"]["strategy"] == "static_value"


def test_full_count_without_observed_reserve_keeps_standard_recovery_wire(tracked):
    from src.core.process_progress import calculate_process_progress

    with tracked.sessions() as db:
        process = db.get(models.Process, "wuwa")
        process.resource_current, process.resource_updated_at = 240, tracked.now
        process.resource_reserve_current, process.resource_reserve_max = None, None
        progress = calculate_process_progress(process, dt.datetime.fromtimestamp(tracked.now))

    assert progress["display_text"] == "240/240"
    assert "overlay_percentage" not in progress
    assert progress["projection"]["strategy"] == "linear_recovery"


@pytest.mark.parametrize("status,observed_at,current", [
    ("error", END, 6),
    ("ok", None, 6),
    ("ok", 0, 6),
    ("ok", END + 1, 6),
    ("ok", END, None),
])
def test_wuwa_progress_withholds_eta_without_valid_observation(status, observed_at, current):
    from src.core.process_progress import calculate_process_progress

    process = SimpleNamespace(resource_tracking_enabled=True, resource_provider="wuwa", resource_key=KEY,
                              resource_status=status, resource_current=current, resource_max=240,
                              resource_updated_at=observed_at)
    progress = calculate_process_progress(process, dt.datetime.fromtimestamp(END))

    assert "ready_at" not in progress
    assert "remaining_seconds" not in progress
    assert "ready_at" not in progress.get("projection", {})
    assert "remaining_seconds" not in progress.get("projection", {})


def test_wuwa_migration_adds_nullable_current_quantities_without_session_quantity_columns(monkeypatch):
    from src.data import database
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE managed_processes (id TEXT PRIMARY KEY, name TEXT)"))
        db.execute(text("INSERT INTO managed_processes (id,name) VALUES ('legacy','보존 게임')"))
        db.execute(text("CREATE TABLE process_sessions (id INTEGER PRIMARY KEY, process_id TEXT, end_timestamp REAL)"))
    monkeypatch.setattr(database, "engine", engine)
    database.auto_migrate_database(strict=True)
    with engine.connect() as db:
        values = db.execute(text("SELECT name,resource_current,resource_max,resource_reserve_current,resource_reserve_max FROM managed_processes WHERE id='legacy'"))
        assert values.one() == ("보존 게임", None, None, None, None)
    columns = {column["name"] for column in inspect(engine).get_columns("process_sessions")}
    assert not columns.intersection({"resource_current", "resource_max", "resource_reserve_current", "resource_reserve_max"})
    engine.dispose()
