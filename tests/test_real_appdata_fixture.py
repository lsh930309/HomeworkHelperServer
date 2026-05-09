import os
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def _sqlite_backup_copy(source: Path, target: Path) -> None:
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def _fixture_zip() -> Path:
    return Path(os.environ.get("HOMEWORKHELPER_REAL_DATA_ZIP", ROOT / "HomeworkHelper.zip"))


def _require_real_data() -> bool:
    return os.environ.get("HOMEWORKHELPER_REQUIRE_REAL_DATA") == "1"


def _run_real_data() -> bool:
    return os.environ.get("HOMEWORKHELPER_RUN_REAL_DATA") == "1"


@pytest.fixture()
def real_appdata(tmp_path, monkeypatch):
    zip_path = _fixture_zip()
    if not _run_real_data():
        pytest.skip("real AppData fixture checks are opt-in through tools/verify_project.py")
    if not zip_path.exists():
        if _require_real_data():
            pytest.fail(f"required real AppData fixture is missing: {zip_path}")
        pytest.skip(f"real AppData fixture is missing: {zip_path}")

    app_root = tmp_path / "HomeworkHelper"
    app_root.mkdir()
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(app_root)

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return app_root


def test_real_appdata_zip_structure_and_db_integrity(real_appdata):
    db_path = real_appdata / "homework_helper_data" / "app_data.db"
    assert db_path.exists()
    assert (real_appdata / "homework_helper_data" / "app_data.db-wal").exists()
    assert (real_appdata / "homework_helper_data" / "app_data.db-shm").exists()
    assert any((real_appdata / "backups").glob("app_data.backup.*.db"))
    assert any((real_appdata / "icon_cache").glob("*_v5_multires_128px.png"))

    con = sqlite3.connect(db_path)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert {"global_settings", "managed_processes", "process_sessions", "web_shortcuts"} <= tables
        assert con.execute("SELECT COUNT(*) FROM global_settings").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM managed_processes").fetchone()[0] >= 1
        assert con.execute("SELECT COUNT(*) FROM process_sessions").fetchone()[0] >= 1
    finally:
        con.close()


def test_real_appdata_main_gui_state_and_icon_cache_use_clone(real_appdata, monkeypatch, tmp_path):
    db_source = real_appdata / "homework_helper_data" / "app_data.db"
    db_clone = tmp_path / "app_data.clone.db"
    _sqlite_backup_copy(db_source, db_clone)

    engine = create_engine(
        f"sqlite:///{db_clone.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from src.data import database
    from src.api.gui import routes as gui_routes
    from src.api.dashboard import routes as dashboard_routes
    from src.api.dashboard import icons

    monkeypatch.setattr(database, "SessionLocal", TestingSession)
    monkeypatch.setattr(gui_routes, "SessionLocal", TestingSession)
    monkeypatch.setattr(icons, "ICON_CACHE_DIR", str(real_appdata / "icon_cache"))
    monkeypatch.setattr(dashboard_routes, "get_icon_for_size", icons.get_icon_for_size)
    monkeypatch.setattr(dashboard_routes, "extract_icon_from_exe", icons.extract_icon_from_exe)

    app = FastAPI()
    app.include_router(gui_routes.router)
    app.include_router(dashboard_routes.router)
    client = TestClient(app)

    state_response = client.get("/api/gui/main-state")
    assert state_response.status_code == 200
    state = state_response.json()
    assert state["db_continuity"]["direct_sqlite_access"] is False
    assert len(state["processes"]) >= 1
    assert "settings" in state and "theme" in state["settings"]

    png_hits = 0
    for process in state["processes"]:
        icon_response = client.get(process["icon_url"])
        assert icon_response.status_code == 200
        if icon_response.headers["content-type"].startswith("image/png"):
            assert icon_response.content.startswith(b"\x89PNG\r\n\x1a\n")
            png_hits += 1
    assert png_hits >= 1


def test_real_appdata_beholder_detects_legacy_open_sessions(real_appdata, monkeypatch, tmp_path):
    db_source = real_appdata / "homework_helper_data" / "app_data.db"
    db_clone = tmp_path / "app_data.beholder.clone.db"
    _sqlite_backup_copy(db_source, db_clone)

    engine = create_engine(
        f"sqlite:///{db_clone.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from src.data import beholder, models

    db = TestingSession()
    try:
        open_count = db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.is_(None)).count()
        assert open_count >= 1

        incidents = beholder.create_open_session_recovery_incidents(db, running_process_ids=set())

        assert incidents
        payloads = [beholder.incident_to_dict(item) for item in incidents]
        assert any(payload["recommended_action"] in {"abandon_open_sessions", "close_at_last_app_heartbeat"} for payload in payloads)
    finally:
        db.close()
