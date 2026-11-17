"""실제 서버 관측 시작과 종료 세션 보정 권한의 공유 경계를 검증한다."""
from __future__ import annotations

import copy
import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.resource_observation import observe_process_resource
from src.data import crud, models


pytestmark = pytest.mark.usefixtures("resource_test_isolation")
END = dt.datetime(2026, 11, 17, 10, 0, tzinfo=dt.timezone.utc).timestamp()


@pytest.fixture(params=["hoyolab", "nikke"])
def observed(request, monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(crud, "base_dir", str(tmp_path / "backups"))
    provider = request.param
    state = SimpleNamespace(
        provider=provider, sessions=session_factory, now=END + 60.0,
        observed_at=END + 60.0, current=130, percent=40.0,
        credentials={"ltuid": 1, "ltoken_v2": "fixture-token", "starrail_uid": 2},
        login={"cookies": {"session_id": "fixture-session"}, "intl_open_id": "fixture-role", "nikke_area_id": 1},
        requests=[], before_request=None, after_request=None, reserve=None, reserve_max=None,
    )
    with session_factory() as db:
        db.add(models.Process(
            id="game", name="관측 대상", monitoring_path="/fixture/game.exe", launch_path="/fixture/game.exe",
            stamina_tracking_enabled=provider == "hoyolab", hoyolab_game_id="honkai_starrail",
            stamina_current=100, stamina_max=240, stamina_updated_at=END - 60.0,
            resource_tracking_enabled=provider == "nikke", resource_provider="nikke_blablalink",
            resource_key="nikke_outpost_storage", resource_label="전초기지 방어 보상",
            resource_percent=25.0, resource_updated_at=END - 60.0, resource_status="ok",
        ))
        db.add_all([
            models.ProcessSession(id=11, process_id="game", process_name="관측 대상",
                                  start_timestamp=END - 3600, end_timestamp=END, session_duration=3600,
                                  stamina_at_end=100, resource_percent_at_end=25.0, session_status="closed"),
            models.ProcessSession(id=12, process_id="game", process_name="관측 대상",
                                  start_timestamp=END - 1800, end_timestamp=END + 30, session_duration=1830,
                                  stamina_at_end=90, resource_percent_at_end=20.0, session_status="closed"),
        ])
        db.commit()

    class Config:
        def load_credentials(self):
            return copy.deepcopy(state.credentials)

        def load_session(self):
            return copy.deepcopy(state.login)

        def is_configured(self):
            return True

        def save_session(self, cookies, *, intl_open_id=None, nikke_area_id=None):
            state.login = {"cookies": copy.deepcopy(cookies), "intl_open_id": intl_open_id,
                           "nikke_area_id": nikke_area_id, "saved_at": state.now}
            return True

    class Service:
        def __init__(self, config):
            self._config = config
            state.config_snapshot = config

        def is_available(self):
            return True

        def is_configured(self):
            return self._config.is_configured()

        def _observe(self, before_fetch):
            if state.before_request is not None:
                state.before_request()
            assert before_fetch is not None, "서버 관측은 실제 제공자 요청 경계를 통해 시작해야 한다"
            before_fetch()
            state.requests.append(state.now)
            if state.after_request is not None:
                state.after_request()
            return SimpleNamespace(
                game_id="honkai_starrail", current=state.current, max=240,
                provider="nikke_blablalink", resource_key="nikke_outpost_storage",
                percent=state.percent, status="ok", label="전초기지 방어 보상", message="",
                updated_at=dt.datetime.fromtimestamp(state.observed_at, tz=dt.timezone.utc),
                reserve_current=state.reserve, reserve_max=state.reserve_max,
            )

        def get_stamina(self, game_id, *, before_fetch=None):
            assert game_id == "honkai_starrail"
            return self._observe(before_fetch)

        def get_outpost_storage(self, *, before_fetch=None):
            return self._observe(before_fetch)

        def close(self):
            return True

    def observe(session_id=11, **kwargs):
        return observe_process_resource(
            "game", session_id, session_factory=state.sessions,
            hoyolab_config_factory=Config, nikke_config_factory=Config,
            hoyolab_service_factory=Service, nikke_service_factory=Service,
            clock=lambda: state.now,
            **kwargs,
        )

    def values():
        with session_factory() as db:
            process = db.get(models.Process, "game")
            session = db.get(models.ProcessSession, 11)
            other = db.get(models.ProcessSession, 12)
            return SimpleNamespace(
                current=process.stamina_current if provider == "hoyolab" else process.resource_percent,
                anchor=process.stamina_updated_at if provider == "hoyolab" else process.resource_updated_at,
                session=session.stamina_at_end if provider == "hoyolab" else session.resource_percent_at_end,
                other_session=other.stamina_at_end if provider == "hoyolab" else other.resource_percent_at_end,
            )

    state.observe, state.values = observe, values
    yield state
    engine.dispose()


@pytest.mark.parametrize("observed", ["hoyolab"], indirect=True)
@pytest.mark.parametrize("reserve,reserve_max", [(None, None), (0, 2400), (120, 2400)])
def test_successful_hsr_snapshot_replaces_nullable_reserve_as_one_observation(observed, reserve, reserve_max):
    with observed.sessions() as db:
        row = db.get(models.Process, "game")
        row.resource_reserve_current, row.resource_reserve_max = 80, 2400
        db.commit()
    observed.reserve, observed.reserve_max = reserve, reserve_max
    result = observed.observe(None)
    assert result["observation_succeeded"] is True
    with observed.sessions() as db:
        row = db.get(models.Process, "game")
        assert (row.stamina_current, row.stamina_max) == (130, 240)
        assert (row.resource_reserve_current, row.resource_reserve_max) == (reserve, reserve_max)
        assert (row.resource_current, row.resource_max) == (None, None)


@pytest.mark.parametrize("observed", ["hoyolab"], indirect=True)
def test_failed_hsr_snapshot_preserves_both_normal_and_reserve(observed):
    with observed.sessions() as db:
        row = db.get(models.Process, "game")
        row.resource_reserve_current, row.resource_reserve_max = 80, 2400
        db.commit()
    def fail():
        raise RuntimeError("격리 서버 오류")
    observed.before_request = fail
    result = observed.observe(None)
    assert result["observation_succeeded"] is False
    with observed.sessions() as db:
        row = db.get(models.Process, "game")
        assert (row.stamina_current, row.stamina_max, row.stamina_updated_at) == (100, 240, END - 60)
        assert (row.resource_reserve_current, row.resource_reserve_max) == (80, 2400)


def test_authorized_observation_updates_current_and_only_its_fixed_session(observed):
    state = observed
    result = state.observe()
    saved = state.values()
    assert result["observation_succeeded"] is True
    assert result["session_succeeded"] is True
    assert result["process_row"]["id"] == "game"
    assert state.requests == [END + 60]
    assert saved.current == (130 if state.provider == "hoyolab" else 40.0)
    expected = 130 if state.provider == "hoyolab" else 40.0 - 60 * 100 / 86400
    assert saved.session == pytest.approx(expected)
    assert saved.other_session == (90 if state.provider == "hoyolab" else 20.0)


@pytest.mark.parametrize("delay", [600.0, 601.0])
def test_actual_provider_start_at_deadline_has_no_session_authority(observed, delay):
    state = observed
    state.now = END + delay
    before = state.values()
    result = state.observe()
    assert result.get("expired") is True
    assert state.requests == []
    assert state.values() == before


def test_waiting_before_actual_provider_request_cannot_keep_early_authority(observed):
    state = observed
    state.now = END + 599
    state.before_request = lambda: setattr(state, "now", END + 601)
    before = state.values()
    result = state.observe()
    assert result.get("expired") is True
    assert state.requests == []
    assert state.values() == before


def test_request_started_at_599_can_finish_and_store_after_600(observed):
    state = observed
    state.now = END + 599

    def complete_late():
        state.now = END + 610
        state.observed_at = END + 610

    state.after_request = complete_late
    result = state.observe()
    saved = state.values()
    assert state.requests == [END + 599]
    assert result["observation_succeeded"] is True
    assert result["session_succeeded"] is True
    assert saved.current == (130 if state.provider == "hoyolab" else 40.0)
    expected = 129 if state.provider == "hoyolab" else 40.0 - 610 * 100 / 86400
    assert saved.session == pytest.approx(expected)


def test_sessionless_start_manual_or_periodic_refresh_changes_only_current(observed):
    state = observed
    state.now = END + 3600
    state.observed_at = state.now
    before = state.values()
    result = state.observe(None)
    saved = state.values()
    assert result["observation_succeeded"] is True
    assert not result.get("session_succeeded")
    assert saved.current == (130 if state.provider == "hoyolab" else 40.0)
    assert saved.session == before.session
    assert saved.other_session == before.other_session


def test_unchanged_observation_retains_canonical_recovery_anchor(observed):
    state = observed
    state.current = 100
    state.percent = 25.1
    before = state.values()
    result = state.observe(None)
    assert result["observation_succeeded"] is True
    saved = state.values()
    assert saved.current == before.current
    assert saved.anchor == before.anchor
    field = "stamina_updated_at" if state.provider == "hoyolab" else "resource_updated_at"
    assert result["process_row"][field] == before.anchor


def test_account_change_during_request_discards_late_response(observed):
    state = observed
    before = state.values()

    def change_account():
        state.credentials["ltuid"] = 999
        state.login["intl_open_id"] = "replacement-fixture-role"

    state.after_request = change_account
    result = state.observe()
    assert result.get("cancelled") is True
    assert state.values() == before


def test_same_account_external_cookie_rotation_keeps_observation_valid(observed):
    state = observed

    def rotate_cookie():
        state.credentials["ltoken_v2"] = "rotated-fixture-token"
        state.login["cookies"]["session_id"] = "rotated-fixture-session"
        state.login["saved_at"] = END + 61

    state.after_request = rotate_cookie
    result = state.observe()
    assert result["observation_succeeded"] is True
    assert result["session_succeeded"] is True


@pytest.mark.parametrize("observed", ["nikke"], indirect=True)
def test_old_response_cannot_overwrite_new_cookie_of_same_account(observed):
    state = observed

    def rotate_then_old_save():
        state.login["cookies"]["session_id"] = "newer-fixture-session"
        state.login["saved_at"] = END + 61
        assert state.config_snapshot.save_session(
            {"session_id": "older-response-cookie"}, intl_open_id="fixture-role", nikke_area_id=1,
        ) is False

    state.after_request = rotate_then_old_save
    result = state.observe()
    assert result["session_succeeded"] is True
    assert state.login["cookies"]["session_id"] == "newer-fixture-session"


def test_tracking_target_change_during_request_discards_late_response(observed):
    state = observed
    before = state.values()

    def change_target():
        with state.sessions() as db:
            process = db.get(models.Process, "game")
            if state.provider == "hoyolab":
                process.hoyolab_game_id = "zenless_zone_zero"
            else:
                process.resource_key = "another-resource"
            db.commit()

    state.after_request = change_target
    result = state.observe()
    assert result.get("cancelled") is True
    assert state.values() == before


def test_current_write_failure_preserves_authorized_session_correction(observed, monkeypatch):
    state = observed
    name = "update_process_stamina" if state.provider == "hoyolab" else "update_process_resource"

    def fail(*args, **kwargs):
        raise RuntimeError("fixture current write failed")

    monkeypatch.setattr(crud, name, fail)
    before = state.values()
    result = state.observe()
    saved = state.values()
    assert "fixture current write failed" in result["process_error"]
    assert result["session_succeeded"] is True
    assert saved.current == before.current
    assert saved.session != before.session


def test_session_write_failure_preserves_successful_current_write(observed, monkeypatch):
    state = observed

    def fail(*args, **kwargs):
        raise RuntimeError("fixture session write failed")

    monkeypatch.setattr(crud, "apply_session_resource_observation", fail)
    before = state.values()
    result = state.observe()
    saved = state.values()
    assert "fixture session write failed" in result["session_error"]
    assert not result.get("session_succeeded")
    assert saved.current != before.current
    assert saved.session == before.session


def test_session_snapshot_failure_keeps_session_while_current_save_succeeds(observed, monkeypatch):
    state = observed
    backup = crud.backup_model_snapshot

    def fail_session_only(model, *, table, **kwargs):
        if table == "process_sessions":
            return None
        return backup(model, table=table, **kwargs)

    monkeypatch.setattr(crud, "backup_model_snapshot", fail_session_only)
    before = state.values()
    result = state.observe()
    assert "백업" in result["session_error"]
    assert state.values().session == before.session
    assert state.values().current != before.current


def test_background_transport_posts_only_process_and_fixed_session_identity(monkeypatch):
    from src.api.client import BackgroundApiTransport, BackgroundHttpResult
    transport = BackgroundApiTransport("http://testserver")
    calls = []
    expected = {"observation_succeeded": True, "process_row": {"id": "game"}}
    def post(path, body, **kwargs):
        calls.append((path, body, kwargs))
        return BackgroundHttpResult(200, expected, 0.1)
    monkeypatch.setattr(transport, "post_json", post)
    assert transport.observe_process_resource("game", 11) == expected
    assert calls == [("/processes/game/resource-observation", {"session_id": 11}, {"timeout": 45.0})]


def _observation_route(state, monkeypatch):
    """실제 route/schema만 로드하여 서버·앱 startup과 운영 DB를 실행하지 않는다."""
    import ast
    import threading
    from pathlib import Path
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import BaseModel
    from src.core import resource_observation
    from src.data.database_coordination import DatabaseMaintenanceCoordinator

    tree = ast.parse(Path("homework_helper.pyw").read_text(encoding="utf-8"))
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "ResourceObservationRequest"]
    routes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "observe_process_resource"]
    assert len(classes) == len(routes) == 1
    # 삭제된 raw PATCH가 실제 entrypoint에 다시 생기면 격리 앱 구성 전부터 실패한다.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and decorator.args and isinstance(decorator.args[0], ast.Constant):
                    assert decorator.args[0].value not in {"/sessions/{session_id}/stamina", "/sessions/{session_id}/resource"}
    coordinator = DatabaseMaintenanceCoordinator()
    api = FastAPI()
    namespace = dict(app=api, BaseModel=BaseModel, database_coordinator=coordinator,
                     SessionLocal=state.sessions, shutdown_event=threading.Event())
    exec(compile(ast.fix_missing_locations(ast.Module(body=classes + routes, type_ignores=[])),
                 "homework_helper.pyw", "exec"), namespace)

    def operation(pid, sid=None, **kwargs):
        assert pid == "game"
        return state.observe(sid, is_cancelled=kwargs["is_cancelled"])

    monkeypatch.setattr(resource_observation, "observe_process_resource", operation)
    return TestClient(api), coordinator


def test_real_route_rejects_claimed_time_and_raw_values_and_has_no_raw_patch(observed, monkeypatch):
    state = observed
    http, _ = _observation_route(state, monkeypatch)
    before = state.values()
    for extra in ({"request_started_at": END + 1}, {"stamina_at_end": 7}, {"resource_percent_at_end": 7}):
        response = http.post("/processes/game/resource-observation", json={"session_id": 11, **extra})
        assert response.status_code == 422
    for path in ("stamina", "resource"):
        assert http.patch(f"/sessions/11/{path}", params={"stamina_at_end": 7}).status_code == 404
    assert state.requests == []
    assert state.values() == before


@pytest.mark.parametrize("observed", ["hoyolab"], indirect=True)
def test_real_route_holds_database_lease_during_provider_until_restore_can_drain(observed, monkeypatch):
    import concurrent.futures
    import threading
    from src.data.database_coordination import DatabaseDrainTimeout

    state = observed
    active_sessions = SimpleNamespace(count=0)
    original_session = state.sessions.class_

    class CountedSession(original_session):
        def __enter__(self):
            active_sessions.count += 1
            return super().__enter__()

        def __exit__(self, *args):
            try:
                return super().__exit__(*args)
            finally:
                active_sessions.count -= 1

    state.sessions = sessionmaker(bind=state.sessions.kw["bind"], class_=CountedSession)
    http, coordinator = _observation_route(state, monkeypatch)
    entered, release = threading.Event(), threading.Event()

    def during_provider():
        assert active_sessions.count == 0, "네트워크 응답 대기 중 SQL 세션을 잡아 두면 안 된다"
        entered.set()
        assert release.wait(2)

    state.after_request = during_provider
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(http.post, "/processes/game/resource-observation", json={"session_id": 11})
        try:
            assert entered.wait(2)
            assert coordinator.snapshot().active_requests == 1
            with pytest.raises(DatabaseDrainTimeout):
                coordinator.begin_maintenance("fixture restore", drain_timeout_seconds=0)
        finally:
            release.set()
        response = future.result(timeout=2)
    assert response.status_code == 200 and response.json()["session_succeeded"]
    assert coordinator.snapshot().active_requests == 0
    with coordinator.begin_maintenance("fixture restore", drain_timeout_seconds=0):
        assert coordinator.snapshot().mode == "maintenance"
