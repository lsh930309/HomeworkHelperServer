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


def test_open_session_merges_with_next_completed_same_game_for_ab_validation(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-03-30 23:00"), end_timestamp=None, session_duration=None),
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-03-31 00:30"), end_timestamp=_ts("2026-03-31 01:00"), session_duration=1800),
        ],
    )
    response = client.get("/api/analytics/timeline?start=2026-03-30&end=2026-03-31")
    assert response.status_code == 200
    days = {row["date"]: row for row in response.json()["days"]}
    assert days["2026-03-30"]["total_seconds"] == 3600
    assert days["2026-03-31"]["total_seconds"] == 3600

    summary = client.get("/api/analytics/summary?start=2026-03-30&end=2026-03-31").json()
    assert summary["metrics"]["total_seconds"] == 7200
    assert summary["metrics"]["session_count"] == 1
    assert summary["metrics"]["longest_session"]["duration_seconds"] == 7200
    assert summary["metrics"]["longest_session"]["merged_from_open_session"] is True


def test_open_session_merge_counts_overlap_before_next_completed_start(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-03-30 23:00"), end_timestamp=None, session_duration=None),
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-03-31 00:30"), end_timestamp=_ts("2026-03-31 01:00"), session_duration=1800),
        ],
    )
    response = client.get("/api/analytics/timeline?start=2026-03-30&end=2026-03-30")
    assert response.status_code == 200
    assert response.json()["days"] == [{"date": "2026-03-30", "total_seconds": 3600, "games": [{"process_id": "game-a", "process_name": "Game A", "total_seconds": 3600, "sessions": 1}]}]


def test_open_session_without_next_completed_is_excluded(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-01-01 00:00"), end_timestamp=None, session_duration=None),
        ],
    )
    response = client.get("/api/analytics/summary?start=2026-01-01&end=2026-04-01")
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["total_seconds"] == 0
    assert body["metrics"]["longest_session"] is None


def test_open_session_does_not_merge_with_next_different_game(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        processes=[models.Process(id="game-a", name="Game A"), models.Process(id="game-b", name="Game B")],
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-03-30 23:00"), end_timestamp=None, session_duration=None),
            models.ProcessSession(process_id="game-b", process_name="Game B", start_timestamp=_ts("2026-03-31 00:30"), end_timestamp=_ts("2026-03-31 01:00"), session_duration=1800),
        ],
    )
    response = client.get("/api/analytics/summary?start=2026-03-30&end=2026-03-31")
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["total_seconds"] == 1800
    assert body["metrics"]["games"][0]["process_id"] == "game-b"


def test_all_time_range_is_clamped_to_actual_session_start_dates(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-04-01 10:00"), end_timestamp=_ts("2026-04-03 11:00"), session_duration=49 * 3600),
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-04-05 10:00"), end_timestamp=_ts("2026-04-05 11:00"), session_duration=3600),
        ],
    )
    response = client.get("/api/analytics/timeline?start=1970-01-01&end=2026-04-30")
    assert response.status_code == 200
    body = response.json()
    assert body["range"] == {"start": "2026-04-01", "end": "2026-04-05"}
    assert [day["date"] for day in body["days"]] == ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"]
    assert body["days"][0]["total_seconds"] == 14 * 3600
    assert body["days"][1]["total_seconds"] == 24 * 3600
    assert body["days"][2]["total_seconds"] == 11 * 3600


def test_analytics_range_returns_actual_session_bounds(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        sessions=[
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-03-31 10:00"), end_timestamp=_ts("2026-03-31 11:00"), session_duration=3600),
            models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=_ts("2026-04-30 10:00"), end_timestamp=_ts("2026-04-30 11:00"), session_duration=3600),
        ],
    )
    response = client.get("/api/analytics/range")
    assert response.status_code == 200
    assert response.json() == {"start": "2026-03-31", "end": "2026-04-30"}


def test_empty_all_time_summary_avoids_decades_long_range(monkeypatch):
    client = _client_with_seed(monkeypatch, sessions=[])
    response = client.get("/api/analytics/summary?start=1970-01-01&end=2026-04-30")
    assert response.status_code == 200
    body = response.json()
    assert body["range"] == {"start": "2026-04-30", "end": "2026-04-30"}
    assert body["metrics"]["no_play_days"] == 1


def test_dashboard_entrypoint_uses_stable_packaged_assets(monkeypatch):
    client = _client_with_seed(monkeypatch, sessions=[])
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text
    assert '/static/dashboard/dashboard.css' in html
    assert '/static/dashboard/dashboard.js' in html
    assert '/static/dashboard/vite/' not in html

