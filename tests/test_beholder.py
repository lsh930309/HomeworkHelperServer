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
