import datetime as dt
import sqlite3
import tempfile

import pytest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.beholder_routes import router as beholder_router
from src.data import beholder, crud, models, schemas


def _write_minimal_app_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE managed_processes (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE web_shortcuts (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE process_sessions (id INTEGER PRIMARY KEY, process_id TEXT)")
        conn.execute("CREATE TABLE global_settings (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO managed_processes (id, name) VALUES (?, ?)", [("game-a", "Game A"), ("game-b", "Game B")])
        conn.execute("INSERT INTO web_shortcuts (id, name) VALUES ('web-a', 'Web A')")
        conn.executemany("INSERT INTO process_sessions (id, process_id) VALUES (?, ?)", [(1, "game-a"), (2, "game-a"), (3, "game-b")])
        conn.execute("INSERT INTO global_settings (id) VALUES (1)")
        conn.commit()
    finally:
        conn.close()


def _session_factory(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import src.api.beholder_routes as routes
    import src.data.crud as crud_mod

    monkeypatch.setattr(routes, "SessionLocal", TestingSession)
    monkeypatch.setattr(crud_mod, "base_dir", tempfile.mkdtemp(prefix="hh-test-data-"))
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
            actor="process_monitor",
            operation_kind="runtime_stop",
        )
        pytest.fail("Beholder should block extreme stale session close")
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
        crud.end_session(db, session.id, dt.datetime(2026, 5, 8, 0, 0).timestamp(), actor="process_monitor")
    except beholder.BeholderBlocked as exc:
        token = beholder.issue_override_token(db, exc.incident)

    closed = crud.end_session(
        db,
        session.id,
        dt.datetime(2026, 5, 8, 0, 0).timestamp(),
        actor="process_monitor",
        override_token=token,
    )
    assert closed.end_timestamp is not None
    assert closed.session_status == "closed"
    assert db.query(models.BeholderIncident).one().override_used_at is not None


def test_session_end_override_token_cannot_bypass_later_distinct_guard(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 1, 1, 0, 0).timestamp()
    end = dt.datetime(2026, 5, 8, 0, 0).timestamp()
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=start)
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(db, session.id, end, stamina_at_end=-1, actor="process_monitor")
        pytest.fail("long session should be blocked before stamina guard")
    except beholder.BeholderBlocked as exc:
        assert "extreme_duration_without_sufficient_evidence" in exc.incident.risk_factors
        token = beholder.issue_override_token(db, exc.incident)

    try:
        crud.end_session(db, session.id, end, stamina_at_end=-1, actor="process_monitor", override_token=token)
        pytest.fail("the long-session override must not bypass the later negative-stamina guard")
    except beholder.BeholderBlocked as exc:
        assert "invalid_negative_stamina" in exc.incident.risk_factors

    db.expire_all()
    unchanged = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert unchanged.end_timestamp is None
    assert unchanged.stamina_at_end is None


def test_session_end_override_token_is_bound_to_close_reason(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 1, 1, 0, 0).timestamp()
    end = dt.datetime(2026, 5, 8, 0, 0).timestamp()
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=start)
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(db, session.id, end, actor="process_monitor", close_reason="process_exit")
        pytest.fail("long session should be blocked")
    except beholder.BeholderBlocked as exc:
        token = beholder.issue_override_token(db, exc.incident)

    try:
        crud.end_session(
            db,
            session.id,
            end,
            actor="process_monitor",
            close_reason="manual_override",
            override_token=token,
        )
        pytest.fail("override for one close_reason must not allow another")
    except beholder.BeholderBlocked as exc:
        assert "extreme_duration_without_sufficient_evidence" in exc.incident.risk_factors

    db.expire_all()
    unchanged = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert unchanged.end_timestamp is None


def test_runtime_stop_override_allows_retry_timestamp_drift(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 1, 1, 0, 0).timestamp()
    first_end = dt.datetime(2026, 5, 8, 0, 0).timestamp()
    retry_end = first_end + 1
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=start)
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(db, session.id, first_end, actor="process_monitor", close_reason="process_exit")
        pytest.fail("long session should be blocked")
    except beholder.BeholderBlocked as exc:
        token = beholder.issue_override_token(db, exc.incident)

    closed = crud.end_session(
        db,
        session.id,
        retry_end,
        actor="process_monitor",
        close_reason="process_exit",
        override_token=token,
    )

    assert closed.end_timestamp == retry_end
    assert db.query(models.BeholderIncident).one().override_used_at is not None


def test_session_end_override_token_covers_later_stamina_guard(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 10, 0).timestamp()
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=start)
    db.add(session)
    db.commit()
    db.refresh(session)

    end = dt.datetime(2026, 5, 8, 11, 0).timestamp()
    try:
        crud.end_session(db, session.id, end, stamina_at_end=-1, actor="process_monitor")
        pytest.fail("negative stamina should be blocked by the later session-stamina guard")
    except beholder.BeholderBlocked as exc:
        token = beholder.issue_override_token(db, exc.incident)

    closed = crud.end_session(
        db,
        session.id,
        end,
        stamina_at_end=-1,
        actor="process_monitor",
        override_token=token,
    )

    assert closed.end_timestamp == end
    assert closed.stamina_at_end == -1
    assert db.query(models.BeholderIncident).one().override_used_at is not None


def test_session_end_blocks_non_runtime_actor(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 10, 0).timestamp()
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=start)
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(
            db,
            session.id,
            dt.datetime(2026, 5, 8, 10, 5).timestamp(),
            actor="manual_debug_tool",
        )
        pytest.fail("non-runtime actors must not close sessions directly")
    except beholder.BeholderBlocked as exc:
        assert "actor_not_runtime_owner" in exc.incident.risk_factors

    db.expire_all()
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None


def test_beholder_active_incidents_api_and_resolve(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    op = beholder.BeholderOperation(kind="runtime_stop", actor="process_monitor")
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


def test_beholder_backup_preview_includes_user_safe_db_summary(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.api.beholder_routes as routes

    data_dir = tmp_path / "homework_helper_data"
    backup_dir = tmp_path / "backups"
    data_dir.mkdir()
    backup_dir.mkdir()
    current_db = data_dir / "app_data.db"
    backup_db = backup_dir / "app_data.backup.1.db"
    _write_minimal_app_db(current_db)
    _write_minimal_app_db(backup_db)

    monkeypatch.setattr(routes, "base_dir", str(tmp_path))
    monkeypatch.setattr(routes, "data_dir", str(data_dir))
    monkeypatch.setattr(routes, "db_path", str(current_db))
    monkeypatch.setattr(routes, "SessionLocal", SessionLocal)

    app = FastAPI()
    app.include_router(beholder_router)
    client = TestClient(app)

    listed = client.get("/api/beholder/backups")
    assert listed.status_code == 200
    backup = listed.json()["backups"][0]
    assert backup["summary"]["table_counts"]["managed_processes"] == 2
    assert backup["summary"]["table_counts"]["process_sessions"] == 3
    assert "게임 2개" in backup["user_summary"]
    assert backup["integrity"] == "ok"

    preview = client.post("/api/beholder/backups/restore-preview", json={"slot": 1})
    assert preview.status_code == 200
    body = preview.json()
    assert body["current"]["table_counts"]["web_shortcuts"] == 1
    assert body["backup"]["summary"]["table_counts"]["global_settings"] == 1
    assert body["impact"]["will_replace_current_db"] is True
    assert "snapshot" in body["impact"]["summary"]


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
        pytest.fail("duplicate open session should be blocked")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert payload["recommended_action"] == "continue_existing_session"
    assert "continue_existing_session" in {action["id"] for action in payload["available_actions"]}
    assert payload["user_title"]
    assert "앱 재시작 후 현재 실행 상태 판단 필요" in payload["risk_labels"]
    assert "runtime_state_ambiguous" not in payload["risk_labels"]


def test_legacy_open_session_duplicate_recommends_abandon_and_start_new(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    original = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=dt.datetime(2026, 5, 1, 10, 0).timestamp(),
        end_timestamp=None,
        session_status=None,
    )
    db.add(original)
    db.commit()
    db.refresh(original)

    try:
        crud.create_session(db, schemas.ProcessSessionCreate(
            process_id="game-a",
            process_name="Game A",
            start_timestamp=dt.datetime(2026, 5, 8, 10, 0).timestamp(),
            runtime_evidence={"current_process_running": True},
        ))
        pytest.fail("legacy open session should block duplicate session creation")
    except beholder.BeholderBlocked as exc:
        incident = exc.incident
        payload = beholder.incident_to_dict(incident)

    assert payload["recommended_action"] == "abandon_legacy_and_start_new"
    assert "duplicate_legacy_open_session" in payload["risk_factors"]

    result = beholder.resolve_incident_action(db, incident, "abandon_legacy_and_start_new")
    assert result["action"] == "abandon_legacy_and_start_new"
    db.refresh(original)
    assert original.session_status == "abandoned"
    assert original.session_duration == 0
    assert db.query(models.ProcessSession).filter_by(process_id="game-a", end_timestamp=None).count() == 1


def test_open_session_recovery_closes_at_last_app_heartbeat(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 10, 0).timestamp()
    heartbeat = dt.datetime(2026, 5, 8, 10, 30).timestamp()
    crud.upsert_app_runtime_heartbeat(
        db,
        app_instance_id="app-a",
        runtime_kind="pyqt",
        timestamp=heartbeat,
        boot_id="boot-a",
    )
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=start,
        session_status="open",
        heartbeat_timestamp=heartbeat,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    incidents = beholder.create_open_session_recovery_incidents(db, running_process_ids=set())

    assert len(incidents) == 1
    payload = beholder.incident_to_dict(incidents[0])
    assert payload["recommended_action"] == "close_at_last_app_heartbeat"

    result = beholder.resolve_incident_action(db, incidents[0], "close_at_last_app_heartbeat")
    assert result["action"] == "close_at_last_app_heartbeat"
    db.refresh(session)
    assert session.end_timestamp == heartbeat
    assert session.session_duration == heartbeat - start
    assert session.close_reason == "beholder_power_loss_close_at_last_heartbeat"


def test_open_session_recovery_decide_later_keeps_incident_pending(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 10, 0).timestamp()
    heartbeat = dt.datetime(2026, 5, 8, 10, 30).timestamp()
    crud.upsert_app_runtime_heartbeat(
        db,
        app_instance_id="app-a",
        runtime_kind="pyqt",
        timestamp=heartbeat,
        boot_id="boot-a",
    )
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=start,
        session_status="open",
        heartbeat_timestamp=heartbeat,
    )
    db.add(session)
    db.commit()

    incident = beholder.create_open_session_recovery_incidents(db, running_process_ids=set())[0]
    payload = beholder.incident_to_dict(incident)
    action_ids = {action["id"] for action in payload["available_actions"]}
    assert "decide_later" in action_ids
    assert "deny" not in action_ids

    result = beholder.resolve_incident_action(db, incident, "decide_later")

    assert result["action"] == "decide_later"
    db.expire_all()
    still_pending = db.query(models.BeholderIncident).filter_by(id=incident.id).one()
    assert still_pending.status == beholder.STATUS_PENDING
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None


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
            actor="sidebar_settings_dialog",
            allowed_fields={"theme"},
        )
        pytest.fail("sidebar settings patch must not mutate disallowed fields")
    except beholder.BeholderBlocked as exc:
        assert "unauthorized_column_write" in exc.incident.risk_factors

    settings = crud.get_settings(db)
    assert settings.sidebar_height_ratio == 1.0


def test_sidebar_settings_actor_is_labeled_as_pyqt_sidebar_dialog(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    crud.get_settings(db)

    try:
        crud.patch_settings(
            db,
            {"sidebar_height_ratio": 0.5},
            actor="sidebar_settings_dialog",
            allowed_fields={"theme"},
        )
        pytest.fail("sidebar settings dialog writes outside its field scope should be guarded")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert payload["actor"] == "sidebar_settings_dialog"
    assert beholder._actor_label(payload["actor"]) == "기존 GUI 사이드바 설정 창"


def test_settings_guard_blocks_small_personalized_default_regression(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    crud.patch_settings(
        db,
        {"screenshot_save_dir": "C:/Shots"},
        actor="sidebar_settings_dialog",
        allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
    )

    try:
        crud.patch_settings(
            db,
            {"screenshot_save_dir": ""},
            actor="sidebar_settings_dialog",
            allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
        )
        pytest.fail("personalized path reset should be blocked")
    except beholder.BeholderBlocked as exc:
        assert "personalized_settings_default_regression" in exc.incident.risk_factors
        assert "screenshot_save_dir" in exc.incident.risk_factors

    assert crud.get_settings(db).screenshot_save_dir == "C:/Shots"


def test_settings_guard_blocks_invalid_value_ranges(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    crud.patch_settings(
        db,
        {"sidebar_height_ratio": 0.8},
        actor="sidebar_settings_dialog",
        allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
    )

    try:
        crud.patch_settings(
            db,
            {"sidebar_height_ratio": 2.0},
            actor="sidebar_settings_dialog",
            allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
        )
        pytest.fail("invalid setting ranges should be blocked centrally")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)
        assert "invalid_setting_value" in payload["risk_factors"]
        assert payload["recommended_action"] == "deny"
        assert "설정" in payload["user_title"]

    settings = crud.get_settings(db)
    assert settings.sidebar_height_ratio == 0.8


def test_sidebar_mode_is_guarded_and_normalizes_legacy_bool(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()

    crud.patch_settings(
        db,
        {
            "sidebar_mode": "always",
            "sidebar_handle_auto_hide": False,
            "sidebar_trigger_y_start": 0.2,
            "sidebar_trigger_y_end": 0.8,
        },
        actor="sidebar_settings_dialog",
        allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
    )

    settings = crud.get_settings(db)
    assert settings.sidebar_mode == "always"
    assert settings.sidebar_enabled is True
    assert settings.sidebar_handle_auto_hide is False
    assert settings.sidebar_trigger_y_start == 0.2
    assert settings.sidebar_trigger_y_end == 0.8

    crud.patch_settings(
        db,
        {"sidebar_enabled": False},
        actor="sidebar_settings_dialog",
        allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
    )

    settings = crud.get_settings(db)
    assert settings.sidebar_mode == "disabled"
    assert settings.sidebar_enabled is False


def test_full_settings_legacy_disabled_sidebar_without_mode_stays_disabled(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    legacy_payload = schemas.GlobalSettingsSchema(sidebar_enabled=False)

    saved = crud.update_settings(
        db,
        legacy_payload,
        actor="settings_full_update",
        allowed_fields=beholder.allowed_settings_fields_for_actor("settings_full_update"),
    )

    assert saved.sidebar_mode == "disabled"
    assert saved.sidebar_enabled is False


def test_settings_guard_blocks_invalid_sidebar_mode(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()

    try:
        crud.patch_settings(
            db,
            {"sidebar_mode": "sometimes"},
            actor="sidebar_settings_dialog",
            allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
        )
        pytest.fail("invalid sidebar modes should be blocked centrally")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)
        assert "invalid_setting_value" in payload["risk_factors"]
        assert "sidebar_mode" in payload["risk_factors"]


def test_settings_guard_blocks_invalid_sidebar_trigger_range(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()

    try:
        crud.patch_settings(
            db,
            {"sidebar_trigger_y_start": 0.9, "sidebar_trigger_y_end": 0.1},
            actor="sidebar_settings_dialog",
            allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
        )
        pytest.fail("invalid sidebar trigger ranges should be blocked centrally")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)
        assert "invalid_setting_value" in payload["risk_factors"]
        assert "invalid_setting_relation" in payload["risk_factors"]
        assert "sidebar_trigger_y_start>sidebar_trigger_y_end" in payload["risk_factors"]


def test_settings_override_bypasses_later_guards_for_same_scoped_mutation(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    crud.patch_settings(
        db,
        {"screenshot_save_dir": "D:/CustomScreenshots", "sidebar_height_ratio": 0.8},
        actor="sidebar_settings_dialog",
        allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
    )

    risky_update = {"sidebar_height_ratio": 2.0, "screenshot_save_dir": ""}
    try:
        crud.patch_settings(
            db,
            risky_update,
            actor="sidebar_settings_dialog",
            allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
        )
        pytest.fail("invalid sidebar height should be blocked before personalized reset")
    except beholder.BeholderBlocked as exc:
        assert "invalid_setting_value" in exc.incident.risk_factors
        token = beholder.issue_override_token(db, exc.incident)

    crud.patch_settings(
        db,
        risky_update,
        actor="sidebar_settings_dialog",
        allowed_fields=beholder.SIDEBAR_SETTINGS_FIELDS,
        override_token=token,
    )

    db.expire_all()
    settings = crud.get_settings(db)
    assert settings.screenshot_save_dir == ""
    assert settings.sidebar_height_ratio == 2.0


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
        pytest.fail("deleting a process with an open session should be blocked")
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


def test_delete_process_resolution_aborts_when_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    monkeypatch.setattr(crud_mod, "backup_model_snapshot", lambda *args, **kwargs: None)
    db = SessionLocal()
    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="delete-snapshot",
        name="Delete Snapshot",
        monitoring_path="C:/Games/DeleteSnapshot.exe",
        launch_path="C:/Games/DeleteSnapshot.lnk",
    ))
    session = models.ProcessSession(
        process_id=process.id,
        process_name=process.name,
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        session_status="open",
    )
    db.add(session)
    db.commit()

    try:
        crud.delete_process(db, process.id)
        pytest.fail("open-session delete should create a Beholder incident")
    except beholder.BeholderBlocked as exc:
        incident = exc.incident

    with pytest.raises(ValueError, match="백업"):
        beholder.resolve_incident_action(db, incident, "close_sessions_and_delete_process")

    db.rollback()
    db.expire_all()
    assert db.query(models.Process).filter_by(id=process.id).one_or_none() is not None
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None
    assert still_open.session_status == "open"


def test_close_at_heartbeat_resolution_aborts_when_session_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 10, 0).timestamp()
    heartbeat = dt.datetime(2026, 5, 8, 10, 30).timestamp()
    crud.upsert_app_runtime_heartbeat(
        db,
        app_instance_id="app-a",
        runtime_kind="pyqt",
        timestamp=heartbeat,
        boot_id="boot-a",
    )
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=start,
        session_status="open",
        heartbeat_timestamp=heartbeat,
    )
    db.add(session)
    db.commit()
    incident = beholder.create_open_session_recovery_incidents(db, running_process_ids=set())[0]
    monkeypatch.setattr(crud_mod, "backup_model_snapshot", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="백업"):
        beholder.resolve_incident_action(db, incident, "close_at_last_app_heartbeat")

    db.rollback()
    db.expire_all()
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None
    assert still_open.session_status == "open"


def test_delete_process_aborts_when_direct_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="direct-delete-snapshot",
        name="Direct Delete Snapshot",
        monitoring_path="C:/Games/DirectDeleteSnapshot.exe",
        launch_path="C:/Games/DirectDeleteSnapshot.lnk",
    ))
    monkeypatch.setattr(crud_mod, "backup_model_snapshot", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="백업"):
        crud.delete_process(db, process.id)

    db.rollback()
    db.expire_all()
    assert db.query(models.Process).filter_by(id=process.id).one_or_none() is not None


def test_delete_process_allow_once_aborts_when_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="allow-delete-snapshot",
        name="Allow Delete Snapshot",
        monitoring_path="C:/Games/AllowDeleteSnapshot.exe",
        launch_path="C:/Games/AllowDeleteSnapshot.lnk",
    ))
    session = models.ProcessSession(
        process_id=process.id,
        process_name=process.name,
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        session_status="open",
    )
    db.add(session)
    db.commit()

    try:
        crud.delete_process(db, process.id)
        pytest.fail("open-session delete should create an allow_once-capable incident")
    except beholder.BeholderBlocked as exc:
        token = beholder.issue_override_token(db, exc.incident)

    monkeypatch.setattr(crud_mod, "backup_model_snapshot", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="백업"):
        crud.delete_process(db, process.id, override_token=token)

    db.rollback()
    db.expire_all()
    assert db.query(models.Process).filter_by(id=process.id).one_or_none() is not None
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None
    assert still_open.session_status == "open"


def test_settings_save_aborts_when_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    settings = crud.get_settings(db)
    assert settings.theme == "system"
    monkeypatch.setattr(crud_mod, "backup_settings_snapshot", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="백업"):
        crud.patch_settings(
            db,
            {"theme": "dark"},
            actor="global_settings_dialog",
            allowed_fields={"theme"},
        )

    db.rollback()
    db.expire_all()
    assert crud.get_settings(db).theme == "system"


def test_shortcut_delete_aborts_when_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    shortcut = crud.create_shortcut(db, schemas.WebShortcutCreate(
        id="delete-shortcut-snapshot",
        name="Delete Shortcut Snapshot",
        url="https://example.test",
    ))
    monkeypatch.setattr(crud_mod, "backup_model_snapshot", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="백업"):
        crud.delete_shortcut(db, shortcut.id)

    db.rollback()
    db.expire_all()
    assert db.query(models.WebShortcut).filter_by(id=shortcut.id).one_or_none() is not None


def test_end_session_aborts_when_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 10, 0).timestamp()
    end = dt.datetime(2026, 5, 8, 11, 0).timestamp()
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=start)
    db.add(session)
    db.commit()
    db.refresh(session)
    monkeypatch.setattr(crud_mod, "backup_model_snapshot", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="백업"):
        crud.end_session(db, session.id, end, actor="process_monitor")

    db.rollback()
    db.expire_all()
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None


def test_resolving_delete_process_incident_refreshes_client_process_cache(monkeypatch):
    from src.api.client import ApiClient

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.managed_processes = ["stale"]
    client.web_shortcuts = []
    client.latest_beholder_incident = None
    client._pending_beholder_overrides = {}
    monkeypatch.setattr(ApiClient, "_fetch_all_processes", lambda self: ["fresh"])

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "action": "close_sessions_and_delete_process",
                "process_id": "game-a",
                "incident": {"operation_kind": "process_delete", "actor": "process_editor"},
            }

    import src.api.client as client_mod
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: _Response())

    result = client.resolve_beholder_incident(incident_id=1, action="close_sessions_and_delete_process")

    assert result["action"] == "close_sessions_and_delete_process"
    assert client.managed_processes == ["fresh"]


def test_restoring_backup_refreshes_all_client_caches(monkeypatch):
    from src.api.client import ApiClient
    from src.data.data_models import GlobalSettings

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.managed_processes = ["old-process"]
    client.web_shortcuts = ["old-shortcut"]
    client.global_settings = GlobalSettings(theme="light")
    client._pending_beholder_overrides = {("settings_update", "global_settings_dialog"): "token"}
    monkeypatch.setattr(ApiClient, "_fetch_all_processes", lambda self: ["new-process"])
    monkeypatch.setattr(ApiClient, "_fetch_all_web_shortcuts", lambda self: ["new-shortcut"])
    monkeypatch.setattr(ApiClient, "_fetch_global_settings", lambda self: GlobalSettings(theme="dark"))

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    import src.api.client as client_mod
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: _Response())

    result = client.restore_beholder_backup(slot=1)

    assert result == {"ok": True}
    assert client.managed_processes == ["new-process"]
    assert client.web_shortcuts == ["new-shortcut"]
    assert client.global_settings.theme == "dark"
    assert client._pending_beholder_overrides == {}


def test_settings_safe_save_keeps_unused_override_token(monkeypatch):
    from src.api.client import ApiClient
    from src.data.data_models import GlobalSettings

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.global_settings = GlobalSettings(theme="system")
    client.latest_beholder_incident = None
    client._pending_beholder_overrides = {("settings_update", "global_settings_dialog"): "token"}
    seen_headers = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return GlobalSettings(theme="dark").to_dict()

    import src.api.client as client_mod

    def _patch(*args, **kwargs):
        seen_headers.append(kwargs.get("headers") or {})
        return _Response()

    monkeypatch.setattr(client_mod.requests, "patch", _patch)

    assert client.save_global_settings(GlobalSettings(theme="dark"), actor="global_settings_dialog") is True

    assert seen_headers[0]["X-HH-Beholder-Override"] == "token"
    assert client._pending_beholder_overrides[("settings_update", "global_settings_dialog")] == "token"
    assert client.global_settings.theme == "dark"


def test_dialog_settings_save_sends_only_actor_owned_fields(monkeypatch):
    from src.api.client import ApiClient
    from src.data.data_models import GlobalSettings

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.global_settings = GlobalSettings()
    client.latest_beholder_incident = None
    client._pending_beholder_overrides = {}
    seen_payloads = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return GlobalSettings(sidebar_mode="always", theme="dark").to_dict()

    import src.api.client as client_mod

    def _patch(*args, **kwargs):
        seen_payloads.append(kwargs.get("json") or {})
        return _Response()

    monkeypatch.setattr(client_mod.requests, "patch", _patch)

    settings = GlobalSettings(sidebar_mode="always", theme="dark")
    assert client.save_global_settings(settings, actor="sidebar_settings_dialog") is True

    assert "sidebar_mode" in seen_payloads[0]
    assert "theme" not in seen_payloads[0]


def test_remote_settings_dialog_can_save_only_remote_server_mode(monkeypatch):
    from src.api.client import ApiClient
    from src.data.data_models import GlobalSettings

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.global_settings = GlobalSettings()
    client.latest_beholder_incident = None
    client._pending_beholder_overrides = {}
    seen_payloads = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return GlobalSettings(remote_server_mode_enabled=True).to_dict()

    import src.api.client as client_mod

    def _patch(*args, **kwargs):
        seen_payloads.append(kwargs.get("json") or {})
        return _Response()

    monkeypatch.setattr(client_mod.requests, "patch", _patch)

    settings = GlobalSettings(remote_server_mode_enabled=True, theme="dark")
    assert client.save_global_settings(settings, actor="remote_settings_dialog") is True

    assert seen_payloads[0]["remote_server_mode_enabled"] is True
    assert "theme" not in seen_payloads[0]
    assert client.global_settings.remote_server_mode_enabled is True


def test_remote_settings_dialog_has_user_facing_actor_label():
    from src.data import beholder

    assert beholder._actor_label("remote_settings_dialog") == "기존 GUI 원격 설정 창"


def test_settings_override_returns_after_first_consumed_guard(monkeypatch):
    from src.data import beholder as beholder_mod

    settings = models.GlobalSettings(sidebar_trigger_y_start=0.25, sidebar_mode="always")
    update_data = {"sidebar_trigger_y_start": 2.0, "sidebar_mode": "game"}
    operation = beholder_mod.BeholderOperation(
        kind="settings_update",
        actor="sidebar_settings_dialog",
        allowed_tables={beholder_mod.GLOBAL_SETTINGS_TABLE},
        allowed_columns={beholder_mod.GLOBAL_SETTINGS_TABLE: {"sidebar_trigger_y_start", "sidebar_mode"}},
        evidence={
            "changed_fields": ["sidebar_trigger_y_start", "sidebar_mode"],
            "context": {"settings_id": 1},
            "proposed_values": update_data,
        },
        override_token="token",
    )
    consume_calls = []
    monkeypatch.setattr(
        beholder_mod,
        "consume_override_token",
        lambda *_args, **_kwargs: consume_calls.append(True) or True,
    )

    beholder_mod.guard_settings_update(None, settings, update_data, operation)

    assert len(consume_calls) == 1


def test_runtime_heartbeat_keeps_unused_override_token(monkeypatch):
    from src.api.client import ApiClient

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.app_instance_id = "app-a"
    client._pending_beholder_overrides = {("runtime_start", "process_monitor"): "token"}

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    import src.api.client as client_mod
    monkeypatch.setattr(client_mod.requests, "post", lambda *args, **kwargs: _Response())

    assert client.send_runtime_heartbeat() == {"ok": True}
    assert client._pending_beholder_overrides[("runtime_start", "process_monitor")] == "token"


def test_runtime_state_client_splits_last_played_from_stamina(monkeypatch):
    from src.api.client import ApiClient
    from src.data.data_models import ManagedProcess

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.managed_processes = []
    client.web_shortcuts = []
    client.latest_beholder_incident = None
    client._pending_beholder_overrides = {}
    monkeypatch.setattr(ApiClient, "_fetch_all_processes", lambda self: ["fresh"])
    payloads = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    import src.api.client as client_mod

    def _patch(*args, **kwargs):
        payloads.append(kwargs["json"])
        return _Response()

    monkeypatch.setattr(client_mod.requests, "patch", _patch)
    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
        last_played_timestamp=123.0,
        stamina_current=120,
        stamina_max=100,
        stamina_updated_at=124.0,
    )

    assert client.update_process_runtime_state(process) is True

    assert payloads == [
        {"last_played_timestamp": 123.0},
        {"stamina_current": 120, "stamina_max": 100, "stamina_updated_at": 124.0},
    ]
    assert client.managed_processes == ["fresh"]


def test_stamina_refresh_client_uses_hoyolab_specific_patch(monkeypatch):
    from src.api.client import ApiClient

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client.managed_processes = []
    client.web_shortcuts = []
    client.latest_beholder_incident = None
    client._pending_beholder_overrides = {}
    monkeypatch.setattr(ApiClient, "_fetch_all_processes", lambda self: ["fresh-stamina"])
    calls = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    import src.api.client as client_mod

    def _patch(*args, **kwargs):
        calls.append((args, kwargs))
        return _Response()

    monkeypatch.setattr(client_mod.requests, "patch", _patch)

    assert client.update_process_stamina("game-a", 92, 240, 1778497000.0) is True

    assert calls[0][0] == ("http://testserver/processes/game-a/stamina",)
    assert calls[0][1]["json"] == {
        "stamina_current": 92,
        "stamina_max": 240,
        "stamina_updated_at": 1778497000.0,
    }
    assert calls[0][1]["headers"] == {
        "X-HH-Beholder-Actor": "hoyolab_slow_followup",
        "X-HH-Beholder-Operation": "process_stamina_refresh",
    }
    assert client.managed_processes == ["fresh-stamina"]


def test_resource_session_refresh_client_uses_resource_specific_patch(monkeypatch):
    from src.api.client import ApiClient

    client = object.__new__(ApiClient)
    client.base_url = "http://testserver"
    client._pending_beholder_overrides = {}
    calls = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    import src.api.client as client_mod

    def _patch(*args, **kwargs):
        calls.append((args, kwargs))
        return _Response()

    monkeypatch.setattr(client_mod.requests, "patch", _patch)

    assert client.update_session_resource(7, 12.5) is True

    assert calls[0][0] == ("http://testserver/sessions/7/resource",)
    assert calls[0][1]["params"] == {"resource_percent_at_end": 12.5}
    assert calls[0][1]["headers"] == {
        "X-HH-Beholder-Actor": "resource_slow_followup",
        "X-HH-Beholder-Operation": "resource_session_percent_rewrite",
    }


def test_hoyolab_reconcile_persists_only_final_stamina_fields():
    from src.core.hoyolab_reconcile import _StaminaPersistTask
    from src.data.data_models import ManagedProcess

    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
        last_played_timestamp=123.0,
        stamina_tracking_enabled=True,
        hoyolab_game_id="genshin",
        stamina_current=100,
        stamina_max=240,
        stamina_updated_at=1000.0,
    )

    class FakeDataManager:
        runtime_updates = []
        stamina_updates = []
        session_updates = []

        def get_process_by_id(self, process_id):
            assert process_id == "game-a"
            return process

        def update_process_runtime_state(self, updated_process):
            self.runtime_updates.append(updated_process)
            return True

        def update_process_stamina(self, process_id, stamina_current, stamina_max, stamina_updated_at):
            self.stamina_updates.append((process_id, stamina_current, stamina_max, stamina_updated_at))
            return True

        def update_session_stamina(self, session_id, stamina_at_end):
            self.session_updates.append((session_id, stamina_at_end))
            return True

    class Finished:
        def __init__(self):
            self.payloads = []

        def emit(self, *args):
            self.payloads.append(args)

    class Signals:
        def __init__(self):
            self.finished = Finished()

    data_manager = FakeDataManager()
    signals = Signals()
    task = _StaminaPersistTask(
        process_id="game-a",
        process_name="Game A",
        session_id=7,
        lifecycle_token=1,
        request_seq=1,
        fetched_current=90,
        fetched_max=240,
        fetched_at=1778497000.0,
        exit_timestamp=1778497000.0,
        allow_session_correction=True,
        applied_session_stamina=100,
        data_manager=data_manager,
        should_abort=lambda: False,
        signals=signals,
    )

    task.run()

    assert data_manager.stamina_updates == [("game-a", 90, 240, 1778497000.0)]
    assert data_manager.runtime_updates == []
    assert data_manager.session_updates == [(7, 90)]
    assert signals.finished.payloads[0][3]["persist_succeeded"] is True


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
        pytest.fail("negative stamina should be blocked")
    except beholder.BeholderBlocked as exc:
        assert "invalid_negative_stamina" in exc.incident.risk_factors

    db.expire_all()
    unchanged = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert unchanged.stamina_at_end == 10


def test_end_session_blocks_negative_stamina_and_keeps_session_open(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 12, 0).timestamp()
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=start,
        end_timestamp=None,
        stamina_at_end=10,
        session_status="open",
        session_owner="process_monitor",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(
            db,
            session.id,
            start + 120,
            stamina_at_end=-1,
            actor="process_monitor",
            operation_kind="runtime_stop",
        )
        pytest.fail("end_session should not bypass stamina_at_end guard")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)
        assert "invalid_negative_stamina" in payload["risk_factors"]
        assert "음수 스태미나 기록" in payload["risk_labels"]

    db.expire_all()
    unchanged = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert unchanged.end_timestamp is None
    assert unchanged.session_status == "open"
    assert unchanged.stamina_at_end == 10


def test_process_editor_cannot_mutate_runtime_fields(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="game-runtime",
        name="Runtime Game",
        monitoring_path="C:/Games/Runtime.exe",
        launch_path="C:/Games/Runtime.lnk",
    ))
    crud.update_process_runtime_state(
        db,
        process.id,
        last_played_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
    )

    crud.update_process(db, process.id, schemas.ProcessCreateSchema(
        name="Runtime Game Renamed",
        monitoring_path="C:/Games/Runtime.exe",
        launch_path="C:/Games/Runtime.lnk",
        last_played_timestamp=dt.datetime(2026, 5, 9, 12, 0).timestamp(),
    ))

    db.expire_all()
    unchanged = db.query(models.Process).filter_by(id=process.id).one()
    assert unchanged.name == "Runtime Game Renamed"
    assert unchanged.last_played_timestamp == dt.datetime(2026, 5, 8, 12, 0).timestamp()


def test_web_shortcut_editor_preserves_and_cannot_mutate_runtime_reset_timestamp(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    shortcut = crud.create_shortcut(db, schemas.WebShortcutCreate(
        id="daily-check",
        name="Daily Check",
        url="https://example.test",
        refresh_time_str="05:00",
    ))
    opened_at = dt.datetime(2026, 5, 8, 12, 0).timestamp()
    crud.mark_shortcut_opened(db, shortcut.id, opened_at)

    edited = crud.update_shortcut(db, shortcut.id, schemas.WebShortcutCreate(
        name="Daily Check 2",
        url="https://example.test/2",
        refresh_time_str="05:00",
    ))
    assert edited.refresh_time_str == "05:00"
    assert edited.last_reset_timestamp == opened_at

    cleared = crud.update_shortcut(db, shortcut.id, schemas.WebShortcutCreate(
        name="Daily Check 2",
        url="https://example.test/2",
        refresh_time_str=None,
        last_reset_timestamp=None,
    ))
    assert cleared.last_reset_timestamp is None

    crud.update_shortcut(db, shortcut.id, schemas.WebShortcutCreate(
        name="Daily Check 2",
        url="https://example.test/2",
        refresh_time_str="05:00",
    ))
    crud.mark_shortcut_opened(db, shortcut.id, opened_at)
    newer_opened_at = opened_at + 3600
    crud.mark_shortcut_opened(db, shortcut.id, newer_opened_at)
    edited_again = crud.update_shortcut(db, shortcut.id, schemas.WebShortcutCreate(
        name="Daily Check 3",
        url="https://example.test/3",
        refresh_time_str="05:00",
        last_reset_timestamp=opened_at,
    ))
    assert edited_again.last_reset_timestamp == newer_opened_at

    db.expire_all()
    unchanged = db.query(models.WebShortcut).filter_by(id=shortcut.id).one()
    assert unchanged.last_reset_timestamp == newer_opened_at


def test_process_runtime_stamina_guard_blocks_impossible_range(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="stamina-range",
        name="Stamina Range",
        monitoring_path="C:/Games/Stamina.exe",
        launch_path="C:/Games/Stamina.lnk",
    ))
    crud.update_process_stamina(
        db,
        process.id,
        stamina_current=20,
        stamina_max=100,
        stamina_updated_at=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
    )

    try:
        crud.update_process_stamina(
            db,
            process.id,
            stamina_current=120,
            stamina_max=100,
            stamina_updated_at=dt.datetime(2026, 5, 8, 12, 5).timestamp(),
        )
        pytest.fail("current stamina greater than max should be blocked")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)
        assert "invalid_process_value" in payload["risk_factors"]
        assert "invalid_stamina_range" in payload["risk_factors"]
        assert payload["recommended_action"] == "deny"
        assert payload["user_impact"]

    db.expire_all()
    unchanged = db.query(models.Process).filter_by(id=process.id).one()
    assert unchanged.stamina_current == 20
    assert unchanged.stamina_max == 100


def test_process_runtime_override_is_bound_to_exact_values(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="runtime-override",
        name="Runtime Override",
        monitoring_path="C:/Games/RuntimeOverride.exe",
        launch_path="C:/Games/RuntimeOverride.lnk",
    ))

    try:
        crud.update_process_runtime_state(
            db,
            process.id,
            stamina_current=120,
            stamina_max=100,
            stamina_updated_at=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        )
        pytest.fail("invalid runtime stamina should be blocked")
    except beholder.BeholderBlocked as exc:
        token = beholder.issue_override_token(db, exc.incident)

    try:
        crud.update_process_runtime_state(
            db,
            process.id,
            stamina_current=130,
            stamina_max=100,
            stamina_updated_at=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
            override_token=token,
        )
        pytest.fail("override for one runtime value set must not allow another")
    except beholder.BeholderBlocked as exc:
        assert "invalid_stamina_range" in exc.incident.risk_factors


def test_beholder_payload_explains_risks_and_action_outcomes(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    crud.get_settings(db)

    try:
        crud.patch_settings(
            db,
            {"sidebar_height_ratio": 0.5},
            actor="sidebar_settings_dialog",
            allowed_fields={"theme"},
        )
        pytest.fail("sidebar settings patch must not mutate disallowed fields")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert "risk_labels" in payload
    assert "현재 화면에서 바꿀 수 없는 항목 포함" in payload["risk_labels"]
    deny = next(action for action in payload["available_actions"] if action["id"] == "deny")
    assert deny["recommended"] is True
    assert deny["outcome"]
    assert deny["recommended_reason"]


def test_beholder_payload_localizes_invalid_value_risks(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    crud.get_settings(db)

    try:
        crud.patch_settings(
            db,
            {"sidebar_height_ratio": 2.0},
            actor="sidebar_settings_dialog",
            allowed_fields={"sidebar_height_ratio"},
        )
        pytest.fail("invalid sidebar height range should be blocked")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert "설정 값 범위 오류" in payload["risk_labels"]
    assert "사이드바 높이 비율 변경" in payload["risk_labels"]
    assert all("sidebar_height_ratio" not in label for label in payload["risk_labels"])


def test_beholder_payload_localizes_session_end_risks(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    start = dt.datetime(2026, 5, 8, 10, 0).timestamp()
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=start,
        end_timestamp=start + 60,
        session_duration=60,
        session_status="closed",
        session_owner="process_monitor",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        crud.end_session(
            db,
            session.id,
            start - 60,
            actor="manual_debug_tool",
            operation_kind="runtime_stop",
        )
        pytest.fail("negative duration and closed status should be blocked")
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert "종료 시간이 시작 시간보다 빠름" in payload["risk_labels"]
    assert "이미 닫힌 기록을 다시 종료하려는 요청" in payload["risk_labels"]
    assert "런타임 담당자가 아닌 요청" in payload["risk_labels"]
    assert all("invalid_current_status" not in label for label in payload["risk_labels"])


def test_beholder_rejects_resolving_non_pending_incidents(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    incident = beholder.create_incident(
        db,
        severity=beholder.SEVERITY_WARNING,
        operation=beholder.BeholderOperation(kind="runtime_start", actor="process_monitor"),
        target_summary="process_id=game-a",
        suspected_cause="duplicate",
        current_state_summary="open session exists",
        proposed_change_summary="start new session",
        risk_score=65,
        risk_factors=["duplicate_open_session"],
        safe_recommendation="refresh",
    )
    beholder.mark_incident(db, incident.id, beholder.STATUS_RESOLVED)
    db.refresh(incident)

    try:
        beholder.resolve_incident_action(db, incident, "close_previous_and_start_new")
        pytest.fail("already resolved incident should not execute side effects")
    except ValueError as exc:
        assert "이미 처리된" in str(exc)


def test_beholder_rejects_unoffered_incident_actions(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    session = models.ProcessSession(process_id="game-a", process_name="Game A", start_timestamp=1.0)
    db.add(session)
    db.commit()
    incident = beholder.create_incident(
        db,
        severity=beholder.SEVERITY_WARNING,
        operation=beholder.BeholderOperation(kind="settings_update", actor="global_settings_dialog"),
        target_summary="global_settings",
        suspected_cause="test",
        current_state_summary="settings",
        proposed_change_summary="settings update",
        risk_score=70,
        risk_factors=["test"],
        safe_recommendation="deny",
        available_actions=[{"id": "deny", "label": "차단 유지"}],
    )

    try:
        beholder.resolve_incident_action(db, incident, "abandon_open_sessions")
        pytest.fail("actions absent from available_actions must be rejected")
    except ValueError as exc:
        assert "제공하지 않은" in str(exc)

    db.expire_all()
    still_open = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert still_open.end_timestamp is None


def test_open_sessions_context_without_target_matches_nothing(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    db = SessionLocal()
    for process_id in ("game-a", "game-b"):
        db.add(models.ProcessSession(process_id=process_id, process_name=process_id, start_timestamp=1.0))
    db.commit()
    incident = beholder.create_incident(
        db,
        severity=beholder.SEVERITY_WARNING,
        operation=beholder.BeholderOperation(kind="runtime_recovery", actor="runtime_recovery"),
        target_summary="runtime_recovery",
        suspected_cause="test",
        current_state_summary="open sessions",
        proposed_change_summary="abandon",
        risk_score=70,
        risk_factors=["test"],
        safe_recommendation="deny",
        available_actions=[{"id": "abandon_open_sessions", "label": "버리기"}],
        resolution_metadata={"action_context": {}},
    )

    try:
        beholder.resolve_incident_action(db, incident, "abandon_open_sessions")
        pytest.fail("empty action context must not select every open session")
    except ValueError as exc:
        assert "열린 세션" in str(exc)

    db.expire_all()
    assert db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.is_(None)).count() == 2


def test_hoyolab_followup_session_stamina_rewrite_is_allowed(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        end_timestamp=dt.datetime(2026, 5, 8, 13, 0).timestamp(),
        session_duration=3600,
        stamina_at_end=100,
        session_status="closed",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    assert crud.update_session_stamina(
        db,
        session.id,
        92,
        actor="hoyolab_slow_followup",
        operation_kind="hoyolab_session_stamina_rewrite",
    ) is True

    db.expire_all()
    updated = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert updated.stamina_at_end == 92
    assert beholder.active_incidents(db) == []


def test_hoyolab_followup_session_stamina_rewrite_aborts_when_snapshot_fails(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    session = models.ProcessSession(
        process_id="game-a",
        process_name="Game A",
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        end_timestamp=dt.datetime(2026, 5, 8, 13, 0).timestamp(),
        session_duration=3600,
        stamina_at_end=100,
        session_status="closed",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    monkeypatch.setattr(crud_mod, "backup_model_snapshot", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="백업"):
        crud.update_session_stamina(
            db,
            session.id,
            92,
            actor="hoyolab_slow_followup",
            operation_kind="hoyolab_session_stamina_rewrite",
        )

    db.rollback()
    db.expire_all()
    unchanged = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert unchanged.stamina_at_end == 100


def test_resource_followup_session_percent_rewrite_is_allowed(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    session = models.ProcessSession(
        process_id="nikke",
        process_name="NIKKE",
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        end_timestamp=dt.datetime(2026, 5, 8, 13, 0).timestamp(),
        session_duration=3600,
        resource_percent_at_end=10.0,
        session_status="closed",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    assert crud.update_session_resource(
        db,
        session.id,
        12.5,
        actor="resource_slow_followup",
        operation_kind="resource_session_percent_rewrite",
    ) is True

    db.expire_all()
    updated = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert updated.resource_percent_at_end == 12.5
    assert beholder.active_incidents(db) == []


def test_resource_session_percent_range_is_guarded(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    session = models.ProcessSession(
        process_id="nikke",
        process_name="NIKKE",
        start_timestamp=dt.datetime(2026, 5, 8, 12, 0).timestamp(),
        end_timestamp=dt.datetime(2026, 5, 8, 13, 0).timestamp(),
        session_duration=3600,
        resource_percent_at_end=10.0,
        session_status="closed",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    with pytest.raises(beholder.BeholderBlocked) as exc_info:
        crud.update_session_resource(db, session.id, 120.0)

    assert "invalid_resource_percent" in exc_info.value.incident.risk_factors
    db.expire_all()
    unchanged = db.query(models.ProcessSession).filter_by(id=session.id).one()
    assert unchanged.resource_percent_at_end == 10.0


def test_process_monitor_does_not_persist_stop_state_after_blocked_close(monkeypatch):
    from src.core.process_monitor import ProcessMonitor
    from src.data.data_models import ManagedProcess
    import src.core.process_monitor as process_monitor_module

    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
        last_played_timestamp=123.0,
    )

    class FakeDataManager:
        managed_processes = [process]
        runtime_state_saved = False

        def end_session(self, session_id, end_timestamp, stamina_at_end=None):
            return None

        def update_process_runtime_state(self, updated_process):
            self.runtime_state_saved = True
            return True

    monkeypatch.setattr(process_monitor_module.psutil, "process_iter", lambda _attrs: [])

    data_manager = FakeDataManager()
    monitor = ProcessMonitor(data_manager)
    monitor.active_monitored_processes["game-a"] = {
        "pid": 100,
        "exe": "/games/a.exe",
        "start_time_approx": 1.0,
        "session_id": 7,
    }

    result = monitor.check_and_update_statuses()

    assert result.changed is False
    assert result.stopped == []
    assert data_manager.runtime_state_saved is False
    assert process.last_played_timestamp == 123.0
    assert "game-a" in monitor.active_monitored_processes


def test_process_monitor_pauses_duplicate_runtime_stop_after_beholder_block(monkeypatch):
    from src.core.process_monitor import ProcessMonitor
    from src.data.data_models import ManagedProcess
    import src.core.process_monitor as process_monitor_module

    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
        last_played_timestamp=123.0,
    )

    class FakeDataManager:
        managed_processes = [process]
        latest_beholder_incident = {"operation_kind": "runtime_stop"}
        end_calls = 0

        def end_session(self, session_id, end_timestamp, stamina_at_end=None):
            self.end_calls += 1
            return None

        def update_process_runtime_state(self, updated_process):
            raise AssertionError("blocked stop must not save runtime state")

    monkeypatch.setattr(process_monitor_module.psutil, "process_iter", lambda _attrs: [])

    data_manager = FakeDataManager()
    monitor = ProcessMonitor(data_manager)
    monitor.active_monitored_processes["game-a"] = {
        "pid": 100,
        "exe": "/games/a.exe",
        "start_time_approx": 1.0,
        "session_id": 7,
    }

    first = monitor.check_and_update_statuses()
    second = monitor.check_and_update_statuses()

    assert first.changed is False
    assert second.changed is False
    assert data_manager.end_calls == 1
    assert monitor.active_monitored_processes["game-a"]["runtime_stop_pending"] is True
    assert process.last_played_timestamp == 123.0


def test_process_monitor_does_not_rebind_late_resolution_for_exited_game(monkeypatch):
    from src.core.process_monitor import ProcessMonitor
    from src.data.data_models import ManagedProcess
    import src.core.process_monitor as process_monitor_module

    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
    )

    class FakeDataManager:
        managed_processes = [process]

    monkeypatch.setattr(process_monitor_module.psutil, "pid_exists", lambda _pid: False)
    monkeypatch.setattr(process_monitor_module.psutil, "process_iter", lambda _attrs: [])

    monitor = ProcessMonitor(FakeDataManager())
    monitor.apply_beholder_resolution({
        "session_id": 9,
        "process_id": "game-a",
        "action": "continue_existing_session",
        "incident": {
            "operation_kind": "runtime_start",
            "resolution_metadata": {
                "action_context": {"process_id": "game-a", "exe": "/games/a.exe", "pid": 100},
            },
        },
    })

    assert "game-a" not in monitor.active_monitored_processes


def test_process_monitor_rejects_reused_pid_for_late_resolution(monkeypatch):
    from src.core.process_monitor import ProcessMonitor
    from src.data.data_models import ManagedProcess
    import src.core.process_monitor as process_monitor_module

    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
    )

    class FakeProcess:
        def exe(self):
            return "/other/process.exe"

        def create_time(self):
            return 1.0

        def is_running(self):
            return True

    class FakeDataManager:
        managed_processes = [process]

    monkeypatch.setattr(process_monitor_module.psutil, "Process", lambda _pid: FakeProcess())
    monkeypatch.setattr(process_monitor_module.psutil, "process_iter", lambda _attrs: [])

    monitor = ProcessMonitor(FakeDataManager())

    assert monitor._is_runtime_process_running(
        "game-a",
        {"pid": 100, "exe": "/games/a.exe", "requested_start_timestamp": 1.0},
    ) is False


def test_process_monitor_pending_stop_skips_hoyolab_exit_refresh(monkeypatch):
    from src.core.process_monitor import ProcessMonitor
    from src.data.data_models import ManagedProcess
    import src.core.process_monitor as process_monitor_module

    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
        last_played_timestamp=123.0,
        stamina_tracking_enabled=True,
        hoyolab_game_id="genshin",
    )

    class FakeDataManager:
        managed_processes = [process]

    monkeypatch.setattr(process_monitor_module.psutil, "process_iter", lambda _attrs: [])
    monkeypatch.setattr(
        ProcessMonitor,
        "_update_stamina_on_game_exit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pending stop should skip stamina refresh")),
    )

    monitor = ProcessMonitor(FakeDataManager())
    monitor.active_monitored_processes["game-a"] = {
        "pid": 100,
        "exe": "/games/a.exe",
        "start_time_approx": 1.0,
        "session_id": 7,
        "runtime_stop_pending": True,
    }

    result = monitor.check_and_update_statuses()

    assert result.changed is False
    assert process.last_played_timestamp == 123.0


def test_process_monitor_retries_runtime_start_after_allow_once(monkeypatch):
    from src.core.process_monitor import ProcessMonitor
    from src.data.data_models import ManagedProcess

    process = ManagedProcess(
        id="game-a",
        name="Game A",
        monitoring_path="/games/a.exe",
        launch_path="/games/a.exe",
    )

    class FakeDataManager:
        managed_processes = [process]

    monitor = ProcessMonitor(FakeDataManager())
    monitor.active_monitored_processes["game-a"] = {
        "pid": 100,
        "exe": "/games/a.exe",
        "start_time_approx": 1.0,
        "session_id": None,
    }

    monitor.apply_beholder_resolution({
        "override_token": "token",
        "incident": {
            "operation_kind": "runtime_start",
            "resolution_metadata": {
                "override_scope": {
                    "context": {"process_id": "game-a"},
                },
            },
        },
    })

    assert "game-a" not in monitor.active_monitored_processes
