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

from src.api.gui.routes import router
from src.data import database, models


def _client_with_seed(monkeypatch, *, processes=None, shortcuts=None, sessions=None):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models.Base.metadata.create_all(bind=engine)
    db = TestingSession()
    try:
        db.add(models.GlobalSettings(id=1, always_on_top=True, hide_on_game=True))
        for process in processes or []:
            db.add(process)
        for shortcut in shortcuts or []:
            db.add(shortcut)
        for session in sessions or []:
            db.add(session)
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(database, "SessionLocal", TestingSession)
    import src.api.gui.routes as gui_routes

    monkeypatch.setattr(gui_routes, "SessionLocal", TestingSession)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _ts(value: str) -> float:
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp()


def test_main_state_preserves_db_boundary_and_returns_compact_rows(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        processes=[
            models.Process(
                id="game-a",
                name="Game A",
                monitoring_path=r"C:\Games\GameA.exe",
                launch_path=r"C:\Games\LaunchA.lnk",
                user_cycle_hours=24,
                last_played_timestamp=_ts("2026-04-01 10:00"),
            )
        ],
        shortcuts=[models.WebShortcut(id="web-a", name="출석", url="https://example.test")],
    )

    response = client.get("/api/gui/main-state")

    assert response.status_code == 200
    body = response.json()
    assert body["db_continuity"] == {
        "mode": "api-only",
        "direct_sqlite_access": False,
        "appdata_path_owned_by_backend": True,
    }
    assert body["settings"]["always_on_top"] is True
    assert body["settings"]["hide_on_game"] is True
    assert body["processes"][0]["id"] == "game-a"
    assert body["processes"][0]["icon_url"] == "/api/dashboard/icons/game-a?size=128"
    assert body["web_shortcuts"][0]["id"] == "web-a"


def test_main_state_does_not_treat_stale_open_session_as_running(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        processes=[
            models.Process(
                id="game-completed",
                name="Completed Game",
                monitoring_path="run.exe",
                launch_path="run.lnk",
                last_played_timestamp=dt.datetime.now().timestamp(),
                user_cycle_hours=24,
            )
        ],
        sessions=[
            models.ProcessSession(
                process_id="game-completed",
                process_name="Completed Game",
                start_timestamp=_ts("2026-04-01 10:00"),
                end_timestamp=None,
            )
        ],
    )

    response = client.get("/api/gui/main-state")

    assert response.status_code == 200
    assert response.json()["processes"][0]["status"] == "완료됨"


def test_main_state_marks_actual_running_process_as_running(monkeypatch):
    import src.api.gui.routes as gui_routes

    monkeypatch.setattr(gui_routes, "_running_process_ids", lambda processes: {"game-running"})
    client = _client_with_seed(
        monkeypatch,
        processes=[
            models.Process(
                id="game-running",
                name="Running Game",
                monitoring_path="run.exe",
                launch_path="run.lnk",
                last_played_timestamp=dt.datetime.now().timestamp(),
                user_cycle_hours=24,
            )
        ],
    )

    response = client.get("/api/gui/main-state")

    assert response.status_code == 200
    assert response.json()["processes"][0]["status"] == "실행중"


def test_main_state_reports_stamina_progress_without_schema_changes(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        processes=[
            models.Process(
                id="hoyo",
                name="HoYo Game",
                monitoring_path="hoyo.exe",
                launch_path="hoyo.lnk",
                stamina_tracking_enabled=True,
                hoyolab_game_id="zzz",
                stamina_current=20,
                stamina_max=240,
                stamina_updated_at=dt.datetime.now().timestamp(),
            )
        ],
    )

    response = client.get("/api/gui/main-state")

    assert response.status_code == 200
    progress = response.json()["processes"][0]["progress"]
    assert progress["kind"] == "stamina"
    assert progress["label"] == "20/240"
    assert progress["hoyolab_game_id"] == "zzz"
