import datetime as dt
import sqlite3

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
        assert False, "duplicate open session should be blocked"
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
        assert False, "legacy open session should block duplicate session creation"
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


def test_settings_guard_blocks_small_personalized_default_regression(monkeypatch, tmp_path):
    SessionLocal = _session_factory(monkeypatch)
    import src.data.crud as crud_mod
    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    db = SessionLocal()
    crud.patch_settings(
        db,
        {"screenshot_save_dir": "C:/Shots"},
        actor="new_gui_settings",
        allowed_fields=beholder.NEW_GUI_SETTINGS_FIELDS,
    )

    try:
        crud.patch_settings(
            db,
            {"screenshot_save_dir": ""},
            actor="new_gui_settings",
            allowed_fields=beholder.NEW_GUI_SETTINGS_FIELDS,
        )
        assert False, "personalized path reset should be blocked"
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
        {"sidebar_trigger_y_start": 0.2, "sidebar_trigger_y_end": 0.8},
        actor="new_gui_settings",
        allowed_fields=beholder.NEW_GUI_SETTINGS_FIELDS,
    )

    try:
        crud.patch_settings(
            db,
            {"sidebar_trigger_y_start": 0.95, "sidebar_trigger_y_end": 0.1},
            actor="new_gui_settings",
            allowed_fields=beholder.NEW_GUI_SETTINGS_FIELDS,
        )
        assert False, "invalid setting relations should be blocked centrally"
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)
        assert "invalid_setting_value" in payload["risk_factors"]
        assert "invalid_setting_relation" in payload["risk_factors"]
        assert payload["recommended_action"] == "deny"
        assert "설정" in payload["user_title"]

    settings = crud.get_settings(db)
    assert settings.sidebar_trigger_y_start == 0.2
    assert settings.sidebar_trigger_y_end == 0.8


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

    try:
        crud.update_process(db, process.id, schemas.ProcessCreateSchema(
            name="Runtime Game",
            monitoring_path="C:/Games/Runtime.exe",
            launch_path="C:/Games/Runtime.lnk",
            last_played_timestamp=dt.datetime(2026, 5, 9, 12, 0).timestamp(),
        ))
        assert False, "editor updates must not mutate runtime-owned process fields"
    except beholder.BeholderBlocked as exc:
        assert "unauthorized_column_write" in exc.incident.risk_factors
        assert "last_played_timestamp" in exc.incident.risk_factors

    db.expire_all()
    unchanged = db.query(models.Process).filter_by(id=process.id).one()
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
        refresh_time_str=None,
    ))
    assert edited.refresh_time_str is None
    assert edited.last_reset_timestamp == opened_at

    try:
        crud.update_shortcut(db, shortcut.id, schemas.WebShortcutCreate(
            name="Daily Check 2",
            url="https://example.test/2",
            refresh_time_str=None,
            last_reset_timestamp=None,
        ))
        assert False, "editor updates must not mutate runtime-owned shortcut fields"
    except beholder.BeholderBlocked as exc:
        assert "unauthorized_column_write" in exc.incident.risk_factors
        assert "last_reset_timestamp" in exc.incident.risk_factors

    db.expire_all()
    unchanged = db.query(models.WebShortcut).filter_by(id=shortcut.id).one()
    assert unchanged.last_reset_timestamp == opened_at


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
        assert False, "current stamina greater than max should be blocked"
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


def test_beholder_payload_explains_risks_and_action_outcomes(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
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
            {"sidebar_trigger_y_start": 0.9, "sidebar_trigger_y_end": 0.1},
            actor="new_gui_settings",
            allowed_fields={"sidebar_trigger_y_start", "sidebar_trigger_y_end"},
        )
        assert False, "invalid sidebar trigger range should be blocked"
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert "설정 값 범위 오류" in payload["risk_labels"]
    assert "설정 조합 오류" in payload["risk_labels"]
    assert "사이드바 트리거 시작 위치 값이 사이드바 트리거 종료 위치보다 큼" in payload["risk_labels"]
    assert all("sidebar_trigger" not in label for label in payload["risk_labels"])


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
        assert False, "negative duration and closed status should be blocked"
    except beholder.BeholderBlocked as exc:
        payload = beholder.incident_to_dict(exc.incident)

    assert "종료 시간이 시작 시간보다 빠름" in payload["risk_labels"]
    assert "이미 닫힌 기록을 다시 종료하려는 요청" in payload["risk_labels"]
    assert "런타임 담당자가 아닌 요청" in payload["risk_labels"]
    assert all("invalid_current_status" not in label for label in payload["risk_labels"])
