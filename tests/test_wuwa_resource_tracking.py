"""명조의 canonical 수량과 제한된 종료 세션 보정 권한을 검증한다."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data import crud, models, schemas


pytestmark = pytest.mark.usefixtures("wuwa_config_memory")
END = dt.datetime(2026, 11, 17, 10, tzinfo=dt.timezone.utc).timestamp()
TOKEN = "qa_wuwa_tracking_token_never_output"
OTHER_TOKEN = "qa_wuwa_other_tracking_token_never_output"
ROLE_ID = "799900001"
KEY = "waveplate"


@pytest.fixture
def tracked(monkeypatch, tmp_path, wuwa_config_memory):
    from src.core.resource_observation import observe_process_resource
    from src.services.wuwa import WuwaService

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

    def observe(session_id=11):
        return observe_process_resource("wuwa", session_id, session_factory=sessions,
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


def test_wuwa_request_at_599_can_store_after_600_without_recovery_backcast(tracked):
    tracked.now = END + 599
    tracked.after_role = lambda: setattr(tracked, "now", END + 610)
    result = tracked.observe()
    assert result["session_succeeded"] is True
    assert tracked.role_calls == [END + 599]
    assert tracked.values()[6:] == (50.0, 20.0)


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


def test_wuwa_read_projection_has_no_unverified_recovery_prediction(tracked):
    from src.data.data_models import ManagedProcess
    tracked.observe(None)
    with tracked.sessions() as db:
        row = db.get(models.Process, "wuwa")
        payload = schemas.ProcessSchema.model_validate(row).model_dump()
        assert row.resource_percent is None
    runtime = ManagedProcess.from_dict(payload)
    assert runtime.get_resource_percentage(now=END + 60) == 50.0
    assert runtime.get_resource_percentage(now=END + 86400) == 50.0
    assert runtime.resource_reserve_current == 80


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
