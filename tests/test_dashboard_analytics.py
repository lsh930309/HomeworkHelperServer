import datetime as dt
import os
from pathlib import Path

os.environ["HOME"] = "/tmp/homeworkhelper-tests"
Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.dashboard.routes import router
from src.data import database, models


def _client_with_seed(monkeypatch, sessions=None, processes=None):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models.Base.metadata.create_all(bind=engine)
    db = TestingSession()
    try:
        for process in processes or [models.Process(id="game-a", name="Game A")]:
            db.add(process)
        for session in sessions or []:
            db.add(session)
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(database, "SessionLocal", TestingSession)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _ts(value: str) -> float:
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp()


def test_timeline_splits_session_across_date_boundary(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        sessions=[models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-04-01 23:30"), end_timestamp=_ts("2026-04-02 00:30"), session_duration=3600)],
    )
    response = client.get("/api/analytics/timeline?start=2026-04-01&end=2026-04-02")
    assert response.status_code == 200
    days = {row["date"]: row for row in response.json()["days"]}
    assert days["2026-04-01"]["total_seconds"] == 1800
    assert days["2026-04-02"]["total_seconds"] == 1800


def test_summary_includes_previous_period_delta(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-03-31 10:00"), end_timestamp=_ts("2026-03-31 11:00"), session_duration=3600),
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-04-01 10:00"), end_timestamp=_ts("2026-04-01 12:00"), session_duration=7200),
        ],
    )
    response = client.get("/api/analytics/summary?start=2026-04-01&end=2026-04-01")
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["total_seconds"] == 7200
    assert body["previous_metrics"]["total_seconds"] == 3600
    assert body["deltas"]["total_seconds"]["percent"] == 100


def test_patterns_and_session_filter_by_game(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        processes=[models.Process(id="game-a", name="Game A"), models.Process(id="game-b", name="Game B")],
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-04-01 10:00"), end_timestamp=_ts("2026-04-01 11:00"), session_duration=3600),
            models.ProcessSession(process_id="game-b", process_name="Game B", start_timestamp=_ts("2026-04-01 12:00"), end_timestamp=_ts("2026-04-01 13:00"), session_duration=3600),
        ],
    )
    sessions = client.get("/api/analytics/sessions?start=2026-04-01&end=2026-04-01&game_id=game-b").json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["process_id"] == "game-b"
    heatmap = client.get("/api/analytics/patterns?start=2026-04-01&end=2026-04-01&game_id=game-a").json()["heatmap"]
    assert sum(cell["total_seconds"] for cell in heatmap) == 3600


def test_empty_database_returns_zero_summary(monkeypatch):
    client = _client_with_seed(monkeypatch, sessions=[])
    response = client.get("/api/analytics/summary?start=2026-04-01&end=2026-04-03")
    assert response.status_code == 200
    assert response.json()["metrics"]["total_seconds"] == 0


def test_dashboard_entrypoint_uses_stable_packaged_assets(monkeypatch):
    client = _client_with_seed(monkeypatch, sessions=[])
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text
    assert '/static/dashboard/dashboard.css' in html
    assert '/static/dashboard/dashboard.js' in html
    assert '/static/dashboard/vite/' not in html
