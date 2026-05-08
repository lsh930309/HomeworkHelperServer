import datetime as dt

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.beholder_routes import router as beholder_router
from src.data import beholder, crud, models, schemas


def _session_factory(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import src.api.beholder_routes as routes

    monkeypatch.setattr(routes, "SessionLocal", TestingSession)
    return TestingSession


def test_beholder_blocks_extreme_legacy_session_close_and_keeps_session_open(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 1, 1, 0, 0).timestamp()
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=start,
        end_timestamp=None,
        session_duration=None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(
            db,
            session.id,
            dt.datetime(2026, 5, 8, 0, 0).timestamp(),
            actor="new_gui_runtime",
            operation_kind="runtime_stop",
        )
        assert False, "Beholder should block extreme stale session close"
    except beholder.BeholderBlocked as exc:
        incident = exc.incident
        assert incident.severity == "critical"
        assert "extreme_duration_without_sufficient_evidence" in incident.risk_factors

    db.expire_all()
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None
    assert still_open.session_duration is None
    assert db.query(models.BeholderIncident).count() == 1


def test_beholder_allows_long_session_with_override_token(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 1, 1, 0, 0).timestamp()
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=start)
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(db, session.id, dt.datetime(2026, 5, 8, 0, 0).timestamp(), actor="new_gui_runtime")
    except beholder.BeholderBlocked as exc:
        token = beholder.issue_override_token(db, exc.incident)

    closed = crud.end_session(
        db,
        session.id,
        dt.datetime(2026, 5, 8, 0, 0).timestamp(),
        actor="new_gui_runtime",
        override_token=token,
    )
    assert closed.end_timestamp is not None
    assert closed.session_status == "closed"
    assert db.query(models.BeholderIncident).one().override_used_at is not None


def test_beholder_active_incidents_api_and_resolve(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    op = beholder.BeholderOperation(kind="runtime_stop", actor="new_gui_runtime")
    incident = beholder.create_incident(
        db,
        severity="critical",
        operation=op,
        target_summary="session_id=1",
        suspected_cause="테스트",
        current_state_summary="open",
        proposed_change_summary="close",
        risk_score=90,
        risk_factors=["test"],
        safe_recommendation="차단 유지",
    )
    db.close()

    app = FastAPI()
    app.include_router(beholder_router)
    client = TestClient(app)

    active = client.get("/api/beholder/incidents/active")
    assert active.status_code == 200
    assert active.json()["incidents"][0]["id"] == incident.id

    resolved = client.post(f"/api/beholder/incidents/{incident.id}/resolve", json={"action": "deny"})
    assert resolved.status_code == 200
    assert resolved.json()["incident"]["status"] == "denied"
    assert client.get("/api/beholder/incidents/active").json()["incidents"] == []


def test_duplicate_open_session_incident_offers_continue_action(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    db.add(models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=dt.datetime(2026, 5, 8, 10, 0).timestamp(),
        session_status="open",
        session_owner="process_monitor",
    ))
    db.commit()

    try:
        crud.create_session(db, schemas.ProcessSessionCreate(
            process_id="game-a",
            process_name="Game A",
            start_timestamp=dt.datetime(2026, 5, 8, 11, 0).timestamp(),
        ))
        assert False, "duplicate open session should be blocked"
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert payload["recommended_action"] == "continue_existing_session"
    assert "continue_existing_session" in {action["id"] for action in payload["available_actions"]}
    assert payload["user_title"]


def test_continue_existing_session_resolution_reuses_open_session(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    original = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=dt.datetime(2026, 5, 8, 10, 0).timestamp(),
        session_status="open",
        session_owner="process_monitor",
    )
    db.add(original)
    db.commit()
    db.refresh(original)

    try:
        crud.create_session(db, schemas.ProcessSessionCreate(
            process_id="game-a",
            process_name="Game A",
            start_timestamp=dt.datetime(2026, 5, 8, 11, 0).timestamp(),
        ))
    except beholder.BeholderBlocked as exc:
        incident = exc.incident

    result = beholder.resolve_incident_action(db, incident, "continue_existing_session")
    assert result["session_id"] == original.id
    assert db.query(models.ProcessSession).count() == 1
    db.refresh(original)
    assert original.lease_token
    assert original.guard_flags["continued_after_restart"] is True
    assert db.query(models.BeholderIncident).one().status == beholder.STATUS_RESOLVED


def test_settings_guard_blocks_columns_outside_actor_scope(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    crud.get_settings(db)

    try:
        crud.patch_settings(
            db,
            {"sidebar_height_ratio": 0.5},
            actor="new_gui_settings",
            allowed_fields={"theme"},
        )
        assert False, "new GUI settings patch must not mutate sidebar detail fields"
    except beholder.BeholderBlocked as exc:
        assert "unauthorized_column_write" in exc.incident.risk_factors

    settings = crud.get_settings(db)
    assert settings.sidebar_height_ratio == 1.0


def test_delete_process_with_open_session_offers_safe_cleanup_action(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="game-open",
        name="Open Game",
        monitoring_path="C:/Games/Open.exe",
        launch_path="C:/Games/Open.lnk",
    ))
    db.add(models.ProcessSession(
        process_id=process.id,
        process_name=process.name,
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        session_status="open",
    ))
    db.commit()

    try:
        crud.delete_process(db, process.id)
        assert False, "deleting a process with an open session should be blocked"
    except beholder.BeholderBlocked as exc:
        incident = exc.incident
        payload = beholder.incident_to_dict(incident)

    assert payload["recommended_action"] == "close_sessions_and_delete_process"
    assert "delete_process_with_open_sessions" in payload["risk_factors"]
    assert db.query(models.Process).filter_by(id="game-open").first() is not None

    result = beholder.resolve_incident_action(db, incident, "close_sessions_and_delete_process")
    assert result["action"] == "close_sessions_and_delete_process"
    assert db.query(models.Process).filter_by(id="game-open").first() is None
    closed = db.query(models.ProcessSession).filter_by(process_id="game-open").one()
    assert closed.end_timestamp is not None
    assert closed.close_reason == "beholder_close_before_process_delete"


def test_negative_session_stamina_is_blocked_without_mutating_session(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        stamina_at_end=10,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.update_session_stamina(db, session.id, -1)
        assert False, "negative stamina should be blocked"
    except beholder.BeholderBlocked as exc:
        assert "invalid_negative_stamina" in exc.incident.risk_factors

    db.expire_all()
    unchanged = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert unchanged.stamina_at_end == 10
