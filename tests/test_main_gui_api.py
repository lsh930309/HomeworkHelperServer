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


def test_main_state_is_read_only_even_when_process_is_running(monkeypatch):
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
                last_played_timestamp=None,
                user_cycle_hours=24,
            )
        ],
    )

    response = client.get("/api/gui/main-state")

    assert response.status_code == 200
    body = response.json()
    assert body["processes"][0]["status"] == "실행중"
    assert "runtime_sync" not in body


def test_main_state_does_not_mutate_existing_open_session(monkeypatch):
    client = _client_with_seed(
        monkeypatch,
        processes=[
            models.Process(
                id="game-stopped",
                name="Stopped Game",
                monitoring_path="definitely-not-running.exe",
                launch_path="run.lnk",
                last_played_timestamp=None,
                user_cycle_hours=24,
            )
        ],
        sessions=[
            models.ProcessSession(
                process_id="game-stopped",
                process_name="Stopped Game",
                start_timestamp=_ts("2026-04-01 10:00"),
                end_timestamp=None,
            )
        ],
    )

    response = client.get("/api/gui/main-state")

    assert response.status_code == 200
    assert response.json()["processes"][0]["last_played_timestamp"] is None


def test_gui_process_crud_reuses_backend_models(monkeypatch):
    client = _client_with_seed(monkeypatch)

    created = client.post(
        "/api/gui/processes",
        json={
            "name": "New Game",
            "monitoring_path": "C:/Games/New.exe",
            "launch_path": "C:/Games/New.lnk",
            "preferred_launch_type": "direct",
            "server_reset_time_str": "05:00",
            "mandatory_times_str": ["12:00"],
            "is_mandatory_time_enabled": True,
        },
    )
    assert created.status_code == 201
    process_id = created.json()["id"]
    assert created.json()["preferred_launch_type"] == "direct"

    updated = client.put(
        f"/api/gui/processes/{process_id}",
        json={
            "name": "Renamed Game",
            "monitoring_path": "C:/Games/New.exe",
            "launch_path": "C:/Games/New.lnk",
            "preferred_launch_type": "shortcut",
            "server_reset_time_str": "06:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed Game"

    deleted = client.delete(f"/api/gui/processes/{process_id}")
    assert deleted.status_code == 200


def test_gui_web_shortcut_crud_and_open_refresh_state(monkeypatch):
    client = _client_with_seed(monkeypatch)

    created = client.post(
        "/api/gui/web-shortcuts",
        json={"name": "출석", "url": "https://example.test", "refresh_time_str": "05:00"},
    )
    assert created.status_code == 201
    shortcut_id = created.json()["id"]
    assert created.json()["state"] in {"due", "done"}

    opened = client.post(f"/api/gui/web-shortcuts/{shortcut_id}/open")
    assert opened.status_code == 200
    assert opened.json()["last_reset_timestamp"] is not None

    updated = client.put(
        f"/api/gui/web-shortcuts/{shortcut_id}",
        json={"name": "출석2", "url": "https://example.test/2", "refresh_time_str": None},
    )
    assert updated.status_code == 200
    assert updated.json()["state"] == "default"

    deleted = client.delete(f"/api/gui/web-shortcuts/{shortcut_id}")
    assert deleted.status_code == 200


def test_gui_settings_patch_updates_preview_runtime_flags(monkeypatch):
    import src.api.gui.routes as gui_routes

    monkeypatch.setattr(gui_routes, "set_startup_shortcut", lambda enabled: True)
    client = _client_with_seed(monkeypatch)

    response = client.patch(
        "/api/gui/settings",
        json={
            "always_on_top": False,
            "hide_on_game": False,
            "run_on_startup": True,
            "theme": "dark",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["always_on_top"] is False
    assert body["hide_on_game"] is False
    assert body["run_on_startup"] is True
    assert body["startup_applied"] is True


def test_gui_privilege_apply_wraps_admin_restart_helpers(monkeypatch):
    import src.api.gui.routes as gui_routes

    monkeypatch.setattr(gui_routes, "is_admin", lambda: False)
    monkeypatch.setattr(gui_routes, "run_as_admin", lambda: True)
    client = _client_with_seed(monkeypatch)
    client.patch("/api/gui/settings", json={"run_as_admin": True})

    response = client.post("/api/gui/settings/apply-privilege")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["action"] == "run_as_admin"


def test_gui_settings_patch_preserves_sidebar_detail_fields(monkeypatch, tmp_path):
    import src.api.gui.routes as gui_routes
    import src.data.crud as crud_mod

    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    client = _client_with_seed(monkeypatch)
    db = gui_routes.SessionLocal()
    settings = db.query(models.GlobalSettings).filter_by(id=1).one()
    settings.sidebar_trigger_y_start = 0.25
    settings.sidebar_trigger_y_end = 0.75
    settings.sidebar_effect = "glass"
    settings.screenshot_trigger_vk = 179
    settings.sidebar_height_ratio = 0.6
    db.commit()
    db.close()

    response = client.patch("/api/gui/settings", json={"theme": "dark"})

    assert response.status_code == 200
    db = gui_routes.SessionLocal()
    preserved = db.query(models.GlobalSettings).filter_by(id=1).one()
    assert preserved.theme == "dark"
    assert preserved.sidebar_trigger_y_start == 0.25
    assert preserved.sidebar_trigger_y_end == 0.75
    assert preserved.sidebar_effect == "glass"
    assert preserved.screenshot_trigger_vk == 179
    assert preserved.sidebar_height_ratio == 0.6
    db.close()


def test_settings_persistence_contract_includes_sidebar_dialog_fields():
    Schema = __import__("src.data.schemas", fromlist=["GlobalSettingsSchema"]).GlobalSettingsSchema
    schema_fields = set(Schema.model_fields if hasattr(Schema, "model_fields") else Schema.__fields__)
    model_columns = {column.name for column in models.GlobalSettings.__table__.columns}
    required = {"sidebar_trigger_y_start", "sidebar_trigger_y_end", "sidebar_effect", "screenshot_trigger_vk"}

    assert required <= schema_fields
    assert required <= model_columns
