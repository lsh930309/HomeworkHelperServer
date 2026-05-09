import inspect
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data import beholder, crud, models, schemas
from src.data.data_models import GlobalSettings as RuntimeGlobalSettings

ROOT = Path(__file__).resolve().parents[1]


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _schema_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _custom_settings() -> schemas.GlobalSettingsSchema:
    return schemas.GlobalSettingsSchema(
        sleep_start_time_str="01:15",
        sleep_end_time_str="07:45",
        sleep_correction_advance_notify_hours=1.5,
        cycle_deadline_advance_notify_hours=3.0,
        run_on_startup=True,
        always_on_top=True,
        run_as_admin=True,
        notify_on_mandatory_time=False,
        notify_on_cycle_deadline=False,
        notify_on_sleep_correction=False,
        notify_on_daily_reset=False,
        stamina_notify_enabled=False,
        stamina_notify_threshold=35,
        theme="dark",
        hide_on_game=False,
        sidebar_enabled=True,
        sidebar_auto_hide_ms=4321,
        sidebar_edge_width_px=7,
        sidebar_trigger_y_start=0.22,
        sidebar_trigger_y_end=0.81,
        sidebar_effect="glass",
        sidebar_height_ratio=0.67,
        sidebar_opacity=0.73,
        sidebar_clock_enabled=False,
        sidebar_clock_format="%H:%M",
        sidebar_playtime_enabled=False,
        sidebar_playtime_prefix="플레이",
        sidebar_volume_section_enabled=False,
        screenshot_enabled=True,
        screenshot_save_dir="C:/Shots",
        screenshot_gamepad_trigger=False,
        screenshot_disable_gamebar=True,
        screenshot_capture_mode="game_window",
        screenshot_gamepad_button_index=4,
        screenshot_trigger_vk=179,
        recording_enabled=True,
        obs_host="127.0.0.1",
        obs_port=4456,
        obs_password="secret",
        obs_exe_path="C:/OBS/obs64.exe",
        obs_auto_launch=True,
        obs_launch_hidden=False,
        obs_watch_output_dir=False,
        obs_recording_output_dir="C:/Recordings",
        recording_hold_threshold_ms=1200,
    )


def _assert_settings_match(actual: models.GlobalSettings, expected: schemas.GlobalSettingsSchema):
    for key, value in _schema_dump(expected).items():
        assert getattr(actual, key) == value, key


def test_global_settings_contract_covers_model_schema_runtime_and_migrations():
    schema_source = schemas.GlobalSettingsSchema.model_fields if hasattr(schemas.GlobalSettingsSchema, "model_fields") else schemas.GlobalSettingsSchema.__fields__
    schema_fields = set(schema_source)
    model_columns = {column.name for column in models.GlobalSettings.__table__.columns} - {"id"}
    runtime_params = set(inspect.signature(RuntimeGlobalSettings.__init__).parameters) - {"self"}
    database_source = (ROOT / "src" / "data" / "database.py").read_text(encoding="utf-8")
    legacy_migration_source = (ROOT / "homework_helper.pyw").read_text(encoding="utf-8")

    assert schema_fields == model_columns
    assert schema_fields <= runtime_params
    additive_fields = {
        "theme", "hide_on_game",
        "sidebar_enabled", "sidebar_auto_hide_ms", "sidebar_edge_width_px",
        "sidebar_trigger_y_start", "sidebar_trigger_y_end", "sidebar_effect",
        "sidebar_height_ratio", "sidebar_opacity", "sidebar_clock_enabled",
        "sidebar_clock_format", "sidebar_playtime_enabled", "sidebar_playtime_prefix",
        "sidebar_volume_section_enabled", "screenshot_enabled", "screenshot_save_dir",
        "screenshot_gamepad_trigger", "screenshot_disable_gamebar", "screenshot_capture_mode",
        "screenshot_gamepad_button_index", "screenshot_trigger_vk", "recording_enabled",
        "obs_host", "obs_port", "obs_password", "obs_exe_path", "obs_auto_launch",
        "obs_launch_hidden", "obs_watch_output_dir", "obs_recording_output_dir",
        "recording_hold_threshold_ms", "stamina_notify_enabled", "stamina_notify_threshold",
    }
    for field in additive_fields:
        assert field in database_source, f"auto_migrate_database missing {field}"

    critical_fields = {"sidebar_trigger_y_start", "sidebar_trigger_y_end", "sidebar_effect", "screenshot_trigger_vk"}
    for field in critical_fields:
        assert field in legacy_migration_source, f"legacy schema check missing {field}"


def test_runtime_heartbeat_table_is_migrated_for_beholder_recovery():
    database_source = (ROOT / "src" / "data" / "database.py").read_text(encoding="utf-8")
    legacy_migration_source = (ROOT / "homework_helper.pyw").read_text(encoding="utf-8")
    model_columns = {column.name for column in models.AppRuntimeHeartbeat.__table__.columns}

    assert {"app_instance_id", "runtime_kind", "boot_id", "started_at", "last_heartbeat_at", "last_shutdown_at"} <= model_columns
    assert "app_runtime_heartbeats" in database_source
    assert "app_runtime_heartbeats" in legacy_migration_source


def test_pyqt_full_settings_update_preserves_custom_global_settings(monkeypatch, tmp_path):
    import src.data.crud as crud_mod

    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    SessionLocal = _session_factory()
    db = SessionLocal()
    custom = _custom_settings()

    saved = crud.update_settings(
        db,
        custom,
        actor="settings_full_update",
        allowed_fields=beholder.allowed_settings_fields_for_actor("settings_full_update"),
    )

    _assert_settings_match(saved, custom)
    snapshots = list((tmp_path / "backups" / "settings").glob("global_settings.*.json"))
    assert snapshots, "full settings update should leave a pre-mutation settings snapshot"


def test_new_gui_patch_preserves_full_custom_settings(monkeypatch, tmp_path):
    import src.data.crud as crud_mod

    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    SessionLocal = _session_factory()
    db = SessionLocal()
    custom = _custom_settings()
    crud.update_settings(db, custom, actor="settings_full_update")

    patched = crud.patch_settings(
        db,
        {"theme": "light", "always_on_top": False},
        actor="new_gui_settings",
        allowed_fields=beholder.RUNTIME_SETTINGS_FIELDS,
    )

    expected = _schema_dump(custom)
    expected["theme"] = "light"
    expected["always_on_top"] = False
    for key, value in expected.items():
        assert getattr(patched, key) == value, key


def test_process_crud_writes_snapshot_and_preserves_data_contract(monkeypatch, tmp_path):
    import src.data.crud as crud_mod

    monkeypatch.setattr(crud_mod, "base_dir", str(tmp_path))
    SessionLocal = _session_factory()
    db = SessionLocal()

    process = crud.create_process(db, schemas.ProcessCreateSchema(
        id="game-contract",
        name="Contract Game",
        monitoring_path="C:/Games/Contract.exe",
        launch_path="C:/Games/Contract.lnk",
        mandatory_times_str=["12:00"],
        preferred_launch_type="shortcut",
        stamina_tracking_enabled=True,
        hoyolab_game_id="zenless_zone_zero",
        default_volume=55,
        default_muted=False,
    ))
    crud.update_process(db, process.id, schemas.ProcessCreateSchema(
        name="Contract Game 2",
        monitoring_path="C:/Games/Contract.exe",
        launch_path="C:/Games/Contract.lnk",
        mandatory_times_str=["12:00", "18:00"],
        preferred_launch_type="direct",
        stamina_tracking_enabled=True,
        hoyolab_game_id="zenless_zone_zero",
        default_volume=45,
        default_muted=True,
    ))

    updated = crud.get_process_by_id(db, process.id)
    assert updated.name == "Contract Game 2"
    assert updated.mandatory_times_str == ["12:00", "18:00"]
    assert updated.preferred_launch_type == "direct"
    assert updated.default_volume == 45
    assert updated.default_muted is True
    snapshots = list((tmp_path / "backups" / "mutations" / "managed_processes").glob("*.json"))
    assert snapshots, "process update should leave a pre-mutation row snapshot"
