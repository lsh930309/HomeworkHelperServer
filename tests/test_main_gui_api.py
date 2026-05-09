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
    assert updated.json()["last_reset_timestamp"] == opened.json()["last_reset_timestamp"]

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


def test_gui_settings_get_returns_full_global_settings_contract(monkeypatch):
    from src.data import schemas

    client = _client_with_seed(monkeypatch)

    response = client.get("/api/gui/settings")

    assert response.status_code == 200
    schema_fields = set(schemas.GlobalSettingsSchema.model_fields if hasattr(schemas.GlobalSettingsSchema, "model_fields") else schemas.GlobalSettingsSchema.__fields__)
    assert schema_fields <= set(response.json())


def test_gui_settings_patch_updates_sidebar_screenshot_recording_and_notification_fields(monkeypatch):
    import src.api.gui.routes as gui_routes

    client = _client_with_seed(monkeypatch)

    response = client.patch(
        "/api/gui/settings",
        json={
            "sleep_start_time_str": "01:15",
            "sleep_end_time_str": "07:45",
            "sleep_correction_advance_notify_hours": 1.5,
            "cycle_deadline_advance_notify_hours": 3.0,
            "notify_on_mandatory_time": False,
            "notify_on_cycle_deadline": False,
            "notify_on_sleep_correction": False,
            "notify_on_daily_reset": False,
            "stamina_notify_enabled": False,
            "stamina_notify_threshold": 35,
            "sidebar_auto_hide_ms": 4321,
            "sidebar_edge_width_px": 7,
            "sidebar_trigger_y_start": 0.22,
            "sidebar_trigger_y_end": 0.81,
            "sidebar_effect": "glass",
            "sidebar_height_ratio": 0.67,
            "sidebar_opacity": 0.73,
            "sidebar_clock_enabled": False,
            "sidebar_clock_format": "%H:%M",
            "sidebar_playtime_enabled": False,
            "sidebar_playtime_prefix": "플레이",
            "sidebar_volume_section_enabled": False,
            "screenshot_save_dir": "C:/Shots",
            "screenshot_gamepad_trigger": False,
            "screenshot_disable_gamebar": True,
            "screenshot_capture_mode": "game_window",
            "screenshot_gamepad_button_index": 4,
            "screenshot_trigger_vk": 179,
            "obs_host": "127.0.0.1",
            "obs_port": 4456,
            "obs_password": "secret",
            "obs_exe_path": "C:/OBS/obs64.exe",
            "obs_auto_launch": True,
            "obs_launch_hidden": False,
            "obs_watch_output_dir": False,
            "obs_recording_output_dir": "C:/Recordings",
            "recording_hold_threshold_ms": 1200,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sidebar_effect"] == "glass"
    assert body["screenshot_trigger_vk"] == 179
    assert body["obs_port"] == 4456
    assert body["stamina_notify_threshold"] == 35

    db = gui_routes.SessionLocal()
    saved = db.query(models.GlobalSettings).filter_by(id=1).one()
    assert saved.sidebar_playtime_prefix == "플레이"
    assert saved.screenshot_save_dir == "C:/Shots"
    assert saved.obs_recording_output_dir == "C:/Recordings"
    assert saved.notify_on_daily_reset is False
    db.close()


def test_gui_settings_patch_rejects_unknown_and_invalid_values(monkeypatch):
    client = _client_with_seed(monkeypatch)

    assert client.patch("/api/gui/settings", json={"unknown_setting": True}).status_code == 422
    assert client.patch("/api/gui/settings", json={"sleep_start_time_str": "25:00"}).status_code == 422
    assert client.patch("/api/gui/settings", json={"obs_port": 70000}).status_code == 422
    assert client.patch("/api/gui/settings", json={"sidebar_trigger_y_start": 0.9, "sidebar_trigger_y_end": 0.1}).status_code == 422


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


def test_web_shortcut_open_uses_guarded_crud_path(monkeypatch, tmp_path):
    import src.data.crud as crud_mod

    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    client = _client_with_seed(monkeypatch, shortcuts=[models.WebShortcut(
        id="web-guarded",
        name="출석",
        url="https://example.test",
        refresh_time_str="05:00",
        last_reset_timestamp=None,
    )])

    response = client.post("/api/gui/web-shortcuts/web-guarded/open")

    assert response.status_code == 200
    assert response.json()["last_reset_timestamp"] is not None
    snapshots = list((tmp_path / "backups" / "mutations" / "web_shortcuts").glob("*.json"))
    assert snapshots, "guarded shortcut runtime write should leave a pre-mutation snapshot"


def test_gui_hoyolab_credentials_are_managed_without_exposing_tokens(monkeypatch, tmp_path):
    from src.utils.hoyolab_config import HoYoLabConfig

    monkeypatch.setattr(HoYoLabConfig, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(HoYoLabConfig, "_encrypt_data", lambda self, data: data)
    monkeypatch.setattr(HoYoLabConfig, "_decrypt_data", lambda self, data: data)
    client = _client_with_seed(monkeypatch)

    initial = client.get("/api/gui/hoyolab/status")
    assert initial.status_code == 200
    assert "supported_games" in initial.json()

    saved = client.put(
        "/api/gui/hoyolab/credentials",
        json={"ltuid": 12345, "ltoken_v2": "token-secret", "ltmid_v2": "mid-secret"},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["configured"] is True
    assert "token-secret" not in str(body)
    assert "mid-secret" not in str(body)

    status = client.get("/api/gui/hoyolab/status")
    assert status.status_code == 200
    assert status.json()["credentials_file_exists"] is True

    cleared = client.delete("/api/gui/hoyolab/credentials")
    assert cleared.status_code == 200
    assert cleared.json()["credentials_file_exists"] is False


def test_gui_hoyolab_extract_saves_cookies_without_returning_cookie_values(monkeypatch, tmp_path):
    from src.utils.hoyolab_config import HoYoLabConfig

    monkeypatch.setattr(HoYoLabConfig, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(HoYoLabConfig, "_encrypt_data", lambda self, data: data)
    monkeypatch.setattr(HoYoLabConfig, "_decrypt_data", lambda self, data: data)

    class FakeExtractor:
        def extract_from_browser(self, browser):
            assert browser == "chrome"
            return {"ltuid": 123, "ltoken_v2": "extracted-token", "ltmid_v2": "extracted-mid"}

    monkeypatch.setattr("src.utils.browser_cookie_extractor.BrowserCookieExtractor", FakeExtractor)
    client = _client_with_seed(monkeypatch)

    response = client.post("/api/gui/hoyolab/extract", json={"browser": "chrome"})

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert "extracted-token" not in str(response.json())
    assert client.post("/api/gui/hoyolab/extract", json={"browser": "netscape"}).status_code == 422


def test_gui_hoyolab_stamina_refresh_can_persist_through_guarded_process_update(monkeypatch, tmp_path):
    import src.api.gui.routes as gui_routes
    import src.data.crud as crud_mod
    import src.services.hoyolab as hoyolab_mod

    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))

    class FakeInfo:
        game_id = "honkai_starrail"
        game_name = "붕괴: 스타레일"
        current = 144
        max = 240
        recover_time = 3600
        full_time = None
        updated_at = dt.datetime(2026, 5, 9, 12, 0, 0)

    class FakeService:
        def is_available(self):
            return True

        def is_configured(self):
            return True

        def get_stamina(self, game_id):
            assert game_id == "honkai_starrail"
            return FakeInfo()

    monkeypatch.setattr(hoyolab_mod, "get_hoyolab_service", lambda: FakeService())
    client = _client_with_seed(
        monkeypatch,
        processes=[
            models.Process(
                id="hoyo-game",
                name="HoYo Game",
                monitoring_path="hoyo.exe",
                launch_path="hoyo.lnk",
                stamina_tracking_enabled=True,
                hoyolab_game_id="honkai_starrail",
            )
        ],
    )

    response = client.post(
        "/api/gui/hoyolab/stamina",
        json={"game_id": "honkai_starrail", "process_id": "hoyo-game", "persist_to_process": True},
    )

    assert response.status_code == 200
    assert response.json()["current"] == 144
    db = gui_routes.SessionLocal()
    saved = db.query(models.Process).filter_by(id="hoyo-game").one()
    assert saved.stamina_current == 144
    assert saved.stamina_max == 240
    db.close()
    snapshots = list((tmp_path / "backups" / "mutations" / "managed_processes").glob("*.json"))
    assert snapshots, "new GUI HoYoLab runtime refresh should leave a guarded pre-mutation snapshot"


def test_gui_recording_obs_config_import_wraps_existing_reader(monkeypatch):
    monkeypatch.setattr(
        "src.recording.obs_config_reader.read_obs_config",
        lambda: {
            "port": 4456,
            "password": "obs-secret",
            "output_dir": "C:/Recordings",
            "exe_path": "C:/OBS/bin/64bit/obs64.exe",
        },
    )
    client = _client_with_seed(monkeypatch)

    response = client.get("/api/gui/recording/obs-config")

    assert response.status_code == 200
    assert response.json() == {
        "port": 4456,
        "password": "obs-secret",
        "output_dir": "C:/Recordings",
        "exe_path": "C:/OBS/bin/64bit/obs64.exe",
    }


def test_gui_clipboard_file_payload_describes_existing_utility(monkeypatch, tmp_path):
    client = _client_with_seed(monkeypatch)
    note = tmp_path / "note.txt"
    note.write_text("hello", encoding="utf-8")

    response = client.post("/api/gui/clipboard/file-payload", json={"path": str(note)})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(note)
    assert body["exists"] is True
    assert body["file_url"].startswith("file:")
    assert body["has_image"] is False
    assert body["has_png"] is False
    assert isinstance(body["native_copy_supported"], bool)


def test_gui_clipboard_copy_file_rejects_unsupported_environment(monkeypatch, tmp_path):
    monkeypatch.setattr("src.utils.clipboard.is_native_file_clipboard_supported", lambda: False)
    client = _client_with_seed(monkeypatch)
    note = tmp_path / "note.txt"
    note.write_text("hello", encoding="utf-8")

    response = client.post("/api/gui/clipboard/copy-file", json={"path": str(note)})

    assert response.status_code == 503


def test_gui_screenshot_gallery_lists_recent_files_and_serves_safe_images(monkeypatch, tmp_path):
    client = _client_with_seed(monkeypatch)
    shot_dir = tmp_path / "shots"
    shot_dir.mkdir()
    older = shot_dir / "old.png"
    newer = shot_dir / "new.png"
    older.write_bytes(b"\x89PNG\r\n\x1a\nold")
    newer.write_bytes(b"\x89PNG\r\n\x1a\nnew")
    os.utime(older, (_ts("2026-05-08 10:00"), _ts("2026-05-08 10:00")))
    os.utime(newer, (_ts("2026-05-08 11:00"), _ts("2026-05-08 11:00")))

    patched = client.patch("/api/gui/settings", json={"screenshot_save_dir": str(shot_dir)})
    assert patched.status_code == 200

    gallery = client.get("/api/gui/screenshot/gallery?limit=1")

    assert gallery.status_code == 200
    body = gallery.json()
    assert body["exists"] is True
    assert body["total"] == 2
    assert body["items"][0]["name"] == "new.png"
    assert body["items"][0]["path"] == str(newer)
    assert body["items"][0]["image_url"] == "/api/gui/screenshot/gallery/new.png"

    image = client.get("/api/gui/screenshot/gallery/new.png")
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG")
    assert client.get("/api/gui/screenshot/gallery/../new.png").status_code == 404


def test_gui_screenshot_vk_name_is_cross_platform_and_capture_reports_availability(monkeypatch):
    client = _client_with_seed(monkeypatch)

    response = client.get("/api/gui/screenshot/vk/178")

    assert response.status_code == 200
    body = response.json()
    assert body["vk"] == 178
    assert body["hex"] == "0xB2"
    assert body["display_name"] == "미디어 정지"
    assert isinstance(body["capture_supported"], bool)
    assert client.get("/api/gui/screenshot/vk/999").status_code == 422


def test_gui_screenshot_capture_key_rejects_unsupported_environment(monkeypatch):
    monkeypatch.setattr("src.screenshot.key_capture.is_key_capture_supported", lambda: False)
    client = _client_with_seed(monkeypatch)

    response = client.post("/api/gui/screenshot/capture-key", json={"timeout_sec": 1})

    assert response.status_code == 503
