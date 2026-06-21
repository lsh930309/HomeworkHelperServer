from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError
from src.data import models
from src.data import schemas
from src.data import beholder
from src.data.data_models import normalize_sidebar_mode, SIDEBAR_MODE_DISABLED, SIDEBAR_MODE_VALUES
from typing import Any, Optional
from pathlib import Path
import re
import json
import uuid
import time
import logging
import os
import psutil

from src.data.database import base_dir

logger = logging.getLogger(__name__)


def _require_snapshot(path: str | None, message: str) -> str:
    if not path:
        raise ValueError(message)
    return path


def _backup_model_snapshot_or_raise(model: Any, *, table: str, reason: str) -> str:
    return _require_snapshot(
        backup_model_snapshot(model, table=table, reason=reason),
        f"{table} 변경 전 백업을 만들지 못했습니다. 데이터 보존을 위해 변경을 중단했습니다.",
    )


def _backup_settings_snapshot_or_raise(settings: models.GlobalSettings, *, reason: str) -> str:
    return _require_snapshot(
        backup_settings_snapshot(settings, reason=reason),
        "설정 변경 전 백업을 만들지 못했습니다. 데이터 보존을 위해 저장을 중단했습니다.",
    )

def db_retry_on_lock(func):
    """데이터베이스 락 발생 시 재시도하는 데코레이터"""
    def wrapper(*args, **kwargs):
        max_retries = 3
        retry_delay = 0.1  # 100ms

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    logger.warning(f"DB locked, retrying... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay * (attempt + 1))  # 지수 백오프
                else:
                    logger.error(f"DB operation failed after {attempt + 1} attempts: {e}")
                    raise
            except IntegrityError as e:
                logger.error(f"DB integrity error: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected DB error: {e}")
                raise

    return wrapper

# process management funcions
def get_processes(db: Session):
    return db.query(models.Process).all()

def get_process_by_id(db: Session, process_id: str):
    return db.query(models.Process).filter(models.Process.id == process_id).first()

@db_retry_on_lock
def create_process(
    db: Session,
    process: schemas.ProcessCreateSchema,
    *,
    actor: str = "process_editor",
    operation_kind: str = "process_create",
    override_token: str | None = None,
):
    process_data = _dump_schema(process)
    provided_id = process_data.pop('id', None)
    process_id = provided_id if provided_id else str(uuid.uuid4())
    guard_columns = {key for key, value in process_data.items() if key in beholder.PROCESS_EDITOR_FIELDS or value is not None} | {"id"}
    operation = beholder.BeholderOperation(
        kind=operation_kind,
        actor=actor,
        allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
        allowed_columns={beholder.MANAGED_PROCESSES_TABLE: beholder.PROCESS_EDITOR_FIELDS},
        evidence={
            "changed_fields": sorted(guard_columns),
            "context": {"process_id": process_id, "process_name": process_data.get("name")},
            "proposed_values": {**process_data, "id": process_id},
        },
        override_token=override_token,
    )
    beholder.guard_process_update(db, None, process_data, operation, guard_columns)
    db_process = models.Process(id=process_id, **process_data)
    db.add(db_process)
    db.commit()
    db.refresh(db_process)
    return db_process

@db_retry_on_lock
def delete_process(
    db: Session,
    process_id: str,
    *,
    actor: str = "process_editor",
    operation_kind: str = "process_delete",
    override_token: str | None = None,
):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={beholder.MANAGED_PROCESSES_TABLE: beholder.PROCESS_FIELDS},
            evidence={
                "changed_fields": ["id"],
                "context": {"process_id": process_id, "process_name": db_process.name},
                "proposed_values": {"deleted_process_id": process_id},
            },
            override_token=override_token,
        )
        beholder.guard_process_delete(db, db_process, operation)
        _backup_model_snapshot_or_raise(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
        db.delete(db_process)
        db.commit()
    return db_process

@db_retry_on_lock
def update_process(
    db: Session,
    process_id: str,
    process: schemas.ProcessCreateSchema,
    *,
    actor: str = "process_editor",
    operation_kind: str = "process_update",
    override_token: str | None = None,
):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        update_data = _dump_schema(process, exclude_unset=True)
        update_data.pop("id", None)
        if actor == "process_editor":
            for runtime_field in beholder.PROCESS_RUNTIME_FIELDS:
                update_data.pop(runtime_field, None)
        changed = {key for key, value in update_data.items() if hasattr(db_process, key) and getattr(db_process, key) != value}
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={beholder.MANAGED_PROCESSES_TABLE: beholder.PROCESS_EDITOR_FIELDS - {"id"}},
            evidence={
                "changed_fields": sorted(changed),
                "context": {"process_id": process_id, "process_name": getattr(db_process, "name", None)},
                "proposed_values": {key: update_data.get(key) for key in sorted(changed)},
            },
            override_token=override_token,
        )
        beholder.guard_process_update(db, db_process, update_data, operation, changed)
        if changed:
            _backup_model_snapshot_or_raise(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
        for key, value in update_data.items():
            setattr(db_process, key, value)
        db.commit()
        db.refresh(db_process)
    return db_process

@db_retry_on_lock
def update_process_stamina(
    db: Session,
    process_id: str,
    *,
    stamina_current: int,
    stamina_max: int,
    stamina_updated_at: float,
    actor: str = "runtime_stamina_tracker",
    operation_kind: str = "process_stamina_update",
    override_token: str | None = None,
):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        update_data = {
            "stamina_current": stamina_current,
            "stamina_max": stamina_max,
            "stamina_updated_at": stamina_updated_at,
        }
        changed = {key for key, value in update_data.items() if getattr(db_process, key) != value}
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={beholder.MANAGED_PROCESSES_TABLE: {"stamina_current", "stamina_max", "stamina_updated_at"}},
            evidence={
                "changed_fields": sorted(changed),
                "context": {"process_id": process_id, "process_name": getattr(db_process, "name", None)},
                "proposed_values": {key: update_data.get(key) for key in sorted(changed)},
            },
            override_token=override_token,
        )
        beholder.guard_process_update(db, db_process, update_data, operation, changed)
        if changed:
            _backup_model_snapshot_or_raise(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
        for key, value in update_data.items():
            setattr(db_process, key, value)
        db.commit()
        db.refresh(db_process)
    return db_process


@db_retry_on_lock
def update_process_resource(
    db: Session,
    process_id: str,
    *,
    resource_percent: float | None,
    resource_updated_at: float | None,
    resource_status: str | None,
    resource_label: str | None = None,
    actor: str = "resource_tracker",
    operation_kind: str = "process_resource_update",
    override_token: str | None = None,
):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        update_data = {
            "resource_percent": resource_percent,
            "resource_updated_at": resource_updated_at,
            "resource_status": resource_status,
            "resource_label": resource_label,
        }
        update_data = {key: value for key, value in update_data.items() if value is not None}
        changed = {key for key, value in update_data.items() if getattr(db_process, key) != value}
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={beholder.MANAGED_PROCESSES_TABLE: {"resource_percent", "resource_updated_at", "resource_status", "resource_label"}},
            evidence={
                "changed_fields": sorted(changed),
                "context": {"process_id": process_id, "process_name": getattr(db_process, "name", None)},
                "proposed_values": {key: update_data.get(key) for key in sorted(changed)},
            },
            override_token=override_token,
        )
        beholder.guard_process_update(db, db_process, update_data, operation, changed)
        if changed:
            _backup_model_snapshot_or_raise(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
        for key, value in update_data.items():
            setattr(db_process, key, value)
        db.commit()
        db.refresh(db_process)
    return db_process


@db_retry_on_lock
def update_process_runtime_state(
    db: Session,
    process_id: str,
    *,
    last_played_timestamp: float | None = None,
    stamina_current: int | None = None,
    stamina_max: int | None = None,
    stamina_updated_at: float | None = None,
    resource_percent: float | None = None,
    resource_updated_at: float | None = None,
    resource_status: str | None = None,
    resource_label: str | None = None,
    actor: str = "process_monitor",
    operation_kind: str = "process_runtime_state_update",
    override_token: str | None = None,
):
    db_process = get_process_by_id(db, process_id)
    if db_process:
        update_data = {
            "last_played_timestamp": last_played_timestamp,
            "stamina_current": stamina_current,
            "stamina_max": stamina_max,
            "stamina_updated_at": stamina_updated_at,
            "resource_percent": resource_percent,
            "resource_updated_at": resource_updated_at,
            "resource_status": resource_status,
            "resource_label": resource_label,
        }
        update_data = {key: value for key, value in update_data.items() if value is not None}
        changed = {key for key, value in update_data.items() if getattr(db_process, key) != value}
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={
                beholder.MANAGED_PROCESSES_TABLE: {
                    "last_played_timestamp",
                    "stamina_current",
                    "stamina_max",
                    "stamina_updated_at",
                    "resource_percent",
                    "resource_updated_at",
                    "resource_status",
                    "resource_label",
                }
            },
            evidence={
                "changed_fields": sorted(changed),
                "context": {"process_id": process_id, "process_name": getattr(db_process, "name", None)},
                "proposed_values": {key: update_data.get(key) for key in sorted(changed)},
            },
            override_token=override_token,
        )
        beholder.guard_process_update(db, db_process, update_data, operation, changed)
        if changed:
            _backup_model_snapshot_or_raise(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
        for key, value in update_data.items():
            setattr(db_process, key, value)
        db.commit()
        db.refresh(db_process)
    return db_process

# shortcut management functions
def get_shortcut_by_id(db: Session, shortcut_id: str):
    return db.query(models.WebShortcut).filter(models.WebShortcut.id == shortcut_id).first()

def get_shortcuts(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.WebShortcut).offset(skip).limit(limit).all()

@db_retry_on_lock
def create_shortcut(
    db: Session,
    shortcut: schemas.WebShortcutCreate,
    *,
    actor: str = "web_shortcut_editor",
    operation_kind: str = "shortcut_create",
    override_token: str | None = None,
):
    shortcut_data = _dump_schema(shortcut)
    provided_id = shortcut_data.pop('id', None)
    shortcut_id = provided_id if provided_id else str(uuid.uuid4())
    _guard_write(
        db,
        table=beholder.WEB_SHORTCUTS_TABLE,
        columns={key for key, value in shortcut_data.items() if key in beholder.WEB_SHORTCUT_EDITOR_FIELDS or value is not None} | {"id"},
        actor=actor,
        operation_kind=operation_kind,
        allowed_fields=beholder.WEB_SHORTCUT_EDITOR_FIELDS,
        context={"shortcut_id": shortcut_id, "shortcut_name": shortcut_data.get("name")},
        override_token=override_token,
        proposed_values={**shortcut_data, "id": shortcut_id},
    )
    db_shortcut = models.WebShortcut(id=shortcut_id, **shortcut_data)
    db.add(db_shortcut)
    db.commit()
    db.refresh(db_shortcut)
    return db_shortcut

@db_retry_on_lock
def update_shortcut(
    db: Session,
    shortcut_id: str,
    shortcut: schemas.WebShortcutCreate,
    *,
    actor: str = "web_shortcut_editor",
    operation_kind: str = "shortcut_update",
    override_token: str | None = None,
):
    db_shortcut = get_shortcut_by_id(db, shortcut_id)
    if db_shortcut:
        update_data = _dump_schema(shortcut, exclude_unset=True)
        update_data.pop("id", None)
        explicit_refresh_disable_clear = (
            "refresh_time_str" in update_data
            and update_data.get("refresh_time_str") is None
            and "last_reset_timestamp" in update_data
            and update_data.get("last_reset_timestamp") is None
        )
        if actor == "web_shortcut_editor" and not explicit_refresh_disable_clear:
            update_data.pop("last_reset_timestamp", None)
        changed = {key for key, value in update_data.items() if hasattr(db_shortcut, key) and getattr(db_shortcut, key) != value}
        allowed_fields = beholder.WEB_SHORTCUT_EDITOR_FIELDS - {"id"}
        if explicit_refresh_disable_clear and "refresh_time_str" in changed:
            allowed_fields = allowed_fields | {"last_reset_timestamp"}
        _guard_write(
            db,
            table=beholder.WEB_SHORTCUTS_TABLE,
            columns=changed,
            actor=actor,
            operation_kind=operation_kind,
            allowed_fields=allowed_fields,
            context={"shortcut_id": shortcut_id, "shortcut_name": getattr(db_shortcut, "name", None)},
            override_token=override_token,
            proposed_values={key: update_data.get(key) for key in sorted(changed)},
        )
        if changed:
            _backup_model_snapshot_or_raise(db_shortcut, table=beholder.WEB_SHORTCUTS_TABLE, reason=operation_kind)
        for key, value in update_data.items():
            setattr(db_shortcut, key, value)
        db.commit()
        db.refresh(db_shortcut)
    return db_shortcut

@db_retry_on_lock
def delete_shortcut(
    db: Session,
    shortcut_id: str,
    *,
    actor: str = "web_shortcut_editor",
    operation_kind: str = "shortcut_delete",
    override_token: str | None = None,
):
    db_shortcut = get_shortcut_by_id(db, shortcut_id)
    if db_shortcut:
        _guard_write(
            db,
            table=beholder.WEB_SHORTCUTS_TABLE,
            columns={"id"},
            actor=actor,
            operation_kind=operation_kind,
            allowed_fields=beholder.WEB_SHORTCUT_EDITOR_FIELDS,
            context={"shortcut_id": shortcut_id, "shortcut_name": db_shortcut.name},
            override_token=override_token,
            proposed_values={"deleted_shortcut_id": shortcut_id},
        )
        _backup_model_snapshot_or_raise(db_shortcut, table=beholder.WEB_SHORTCUTS_TABLE, reason=operation_kind)
        db.delete(db_shortcut)
        db.commit()
    return db_shortcut

def _dump_schema(model: Any, **kwargs: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


def _model_to_dict(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


def _safe_snapshot_segment(value: Any) -> str:
    text = str(value if value is not None else "row")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._") or "row"


def backup_model_snapshot(model: Any, *, table: str, reason: str, max_backups: int = 50) -> str | None:
    try:
        backup_dir = Path(base_dir) / "backups" / "mutations" / table
        backup_dir.mkdir(parents=True, exist_ok=True)
        safe_table = _safe_snapshot_segment(table)
        safe_model_id = _safe_snapshot_segment(getattr(model, "id", "row"))
        safe_reason = _safe_snapshot_segment(reason)
        path = backup_dir / f"{safe_table}.{safe_model_id}.{int(time.time() * 1000)}.{safe_reason}.json"
        payload = {
            "created_at": time.time(),
            "reason": reason,
            "table": table,
            "row": _model_to_dict(model),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshots = sorted(
            backup_dir.glob(f"{safe_table}.{safe_model_id}.*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in snapshots[max_backups:]:
            old.unlink(missing_ok=True)
        return str(path)
    except Exception as exc:
        logger.warning("%s snapshot backup failed: %s", table, exc)
        return None


def _guard_write(
    db: Session,
    *,
    table: str,
    columns: set[str],
    actor: str,
    operation_kind: str,
    allowed_fields: set[str],
    context: dict[str, Any] | None = None,
    override_token: str | None = None,
    proposed_values: dict[str, Any] | None = None,
) -> beholder.BeholderOperation:
    operation = beholder.BeholderOperation(
        kind=operation_kind,
        actor=actor,
        allowed_tables={table},
        allowed_columns={table: allowed_fields},
        evidence={
            "changed_fields": sorted(columns),
            "context": context or {},
            "proposed_values": proposed_values or {},
        },
        override_token=override_token,
    )
    beholder.guard_table_write(db, operation, table, columns)
    return operation


def _settings_to_dict(settings: models.GlobalSettings) -> dict[str, Any]:
    fields = beholder.allowed_settings_fields_for_actor("settings_full_update")
    return {field: getattr(settings, field) for field in fields if hasattr(settings, field)}


def _changed_fields(settings: models.GlobalSettings, update_data: dict[str, Any]) -> set[str]:
    return {key for key, value in update_data.items() if hasattr(settings, key) and getattr(settings, key) != value}


def _normalize_sidebar_settings_update(current_settings: models.GlobalSettings, update_data: dict[str, Any]) -> None:
    """sidebar_mode와 legacy sidebar_enabled bool을 일관되게 동기화합니다."""
    if "sidebar_mode" not in update_data and "sidebar_enabled" not in update_data:
        return
    legacy_enabled = update_data.get(
        "sidebar_enabled",
        getattr(current_settings, "sidebar_enabled", True),
    )
    raw_mode = update_data.get("sidebar_mode")
    if raw_mode is not None and str(raw_mode).strip().lower() not in SIDEBAR_MODE_VALUES:
        update_data["sidebar_mode"] = str(raw_mode).strip().lower()
        update_data["sidebar_enabled"] = bool(legacy_enabled)
        return
    mode = normalize_sidebar_mode(update_data.get("sidebar_mode"), bool(legacy_enabled))
    update_data["sidebar_mode"] = mode
    update_data["sidebar_enabled"] = mode != SIDEBAR_MODE_DISABLED


def _schema_fields_set(model: Any) -> set[str]:
    return set(getattr(model, "model_fields_set", None) or getattr(model, "__fields_set__", None) or set())


def backup_settings_snapshot(settings: models.GlobalSettings, *, reason: str = "settings_update", max_backups: int = 20) -> str | None:
    try:
        backup_dir = Path(base_dir) / "backups" / "settings"
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / f"global_settings.{int(time.time() * 1000)}.{reason}.json"
        payload = {
            "created_at": time.time(),
            "reason": reason,
            "settings": _settings_to_dict(settings),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshots = sorted(backup_dir.glob("global_settings.*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in snapshots[max_backups:]:
            old.unlink(missing_ok=True)
        return str(path)
    except Exception as exc:
        logger.warning("settings snapshot backup failed: %s", exc)
        return None


def current_boot_id() -> str:
    """Return a stable-enough boot identifier for crash/power-loss recovery decisions."""
    try:
        return str(int(psutil.boot_time()))
    except Exception:
        return f"pid-start:{os.getpid()}"


@db_retry_on_lock
def upsert_app_runtime_heartbeat(
    db: Session,
    *,
    app_instance_id: str,
    runtime_kind: str,
    timestamp: float | None = None,
    boot_id: str | None = None,
    shutdown: bool = False,
) -> models.AppRuntimeHeartbeat:
    now = float(timestamp or time.time())
    row = db.query(models.AppRuntimeHeartbeat).filter(models.AppRuntimeHeartbeat.id == 1).first()
    if row is None:
        row = models.AppRuntimeHeartbeat(id=1, started_at=now)
    if row.app_instance_id != app_instance_id:
        row.started_at = now
    row.app_instance_id = app_instance_id
    row.runtime_kind = runtime_kind
    row.boot_id = boot_id or current_boot_id()
    row.last_heartbeat_at = now
    if shutdown:
        row.last_shutdown_at = now
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_app_runtime_heartbeat(db: Session) -> models.AppRuntimeHeartbeat | None:
    return db.query(models.AppRuntimeHeartbeat).filter(models.AppRuntimeHeartbeat.id == 1).first()



def get_game_platform_links(db: Session):
    return db.query(models.GamePlatformLink).order_by(models.GamePlatformLink.updated_at.desc()).all()


def get_game_platform_link_by_id(db: Session, link_id: str):
    return db.query(models.GamePlatformLink).filter(models.GamePlatformLink.id == link_id).first()


@db_retry_on_lock
def create_game_platform_link(
    db: Session,
    link: schemas.GamePlatformLinkCreate,
    *,
    timestamp: float | None = None,
):
    link_data = _dump_schema(link)
    provided_id = link_data.pop("id", None)
    link_id = provided_id if provided_id else str(uuid.uuid4())
    now = float(timestamp or time.time())
    link_data["pc_process_id"] = str(link_data.get("pc_process_id") or "").strip()
    link_data["android_package_name"] = str(link_data.get("android_package_name") or "").strip()
    if not link_data["pc_process_id"]:
        raise ValueError("pc_process_id가 필요합니다.")
    if not link_data["android_package_name"]:
        raise ValueError("android_package_name이 필요합니다.")
    if not link_data.get("sync_strategy"):
        link_data["sync_strategy"] = "manual"
    db_link = models.GamePlatformLink(id=link_id, created_at=now, updated_at=now, **link_data)
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link


def get_active_mobile_game_sessions(db: Session):
    return (
        db.query(models.MobileGameSession)
        .filter(models.MobileGameSession.status == "active")
        .order_by(models.MobileGameSession.started_at.desc())
        .all()
    )


def get_mobile_game_session_by_id(db: Session, session_id: str):
    return db.query(models.MobileGameSession).filter(models.MobileGameSession.id == session_id).first()


@db_retry_on_lock
def start_mobile_game_session(
    db: Session,
    *,
    game_link_id: str,
    source: str = "manual",
    started_at: float | None = None,
    timestamp: float | None = None,
):
    link = get_game_platform_link_by_id(db, game_link_id)
    if link is None:
        raise ValueError("연결된 Android-PC game link를 찾을 수 없습니다.")
    now = float(timestamp or time.time())
    start_time = float(started_at or now)
    session = models.MobileGameSession(
        id=str(uuid.uuid4()),
        game_link_id=link.id,
        pc_process_id=link.pc_process_id,
        pc_display_name=link.pc_display_name,
        android_package_name=link.android_package_name,
        source=str(source or "manual"),
        status="active",
        started_at=start_time,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@db_retry_on_lock
def end_mobile_game_session(
    db: Session,
    *,
    session_id: str,
    ended_at: float | None = None,
    timestamp: float | None = None,
):
    session = get_mobile_game_session_by_id(db, session_id)
    if session is None or session.status != "active":
        return None
    now = float(timestamp or time.time())
    end_time = float(ended_at or now)
    session.ended_at = end_time
    session.duration_seconds = max(0.0, end_time - float(session.started_at))
    session.status = "ended"
    session.updated_at = now
    db.commit()
    db.refresh(session)
    return session


def get_daily_checkin_setting(db: Session, process_id: str):
    return (
        db.query(models.DailyCheckInSetting)
        .filter(models.DailyCheckInSetting.process_id == process_id)
        .first()
    )


def get_enabled_daily_checkin_settings(db: Session):
    return (
        db.query(models.DailyCheckInSetting)
        .filter(models.DailyCheckInSetting.enabled == True)
        .order_by(models.DailyCheckInSetting.updated_at.desc())
        .all()
    )


@db_retry_on_lock
def upsert_daily_checkin_setting(
    db: Session,
    *,
    process_id: str,
    process_name: str | None,
    user_preset_id: str | None,
    provider: str,
    game_id: str,
    game_name: str | None,
    enabled: bool | None = None,
    last_attempt_at: float | None = None,
    last_result: str | None = None,
    last_message: str | None = None,
    last_period_start: float | None = None,
    last_success_at: float | None = None,
    next_run_at: float | None = None,
    timestamp: float | None = None,
):
    now = float(time.time() if timestamp is None else timestamp)
    row = get_daily_checkin_setting(db, process_id)
    if row is None:
        row = models.DailyCheckInSetting(
            process_id=process_id,
            created_at=now,
            updated_at=now,
            provider=provider,
            game_id=game_id,
            enabled=bool(enabled) if enabled is not None else False,
        )
    row.process_name = process_name
    row.user_preset_id = user_preset_id
    row.provider = provider
    row.game_id = game_id
    row.game_name = game_name
    if enabled is not None:
        row.enabled = bool(enabled)
    if last_attempt_at is not None:
        row.last_attempt_at = float(last_attempt_at)
    if last_result is not None:
        row.last_result = last_result
    if last_message is not None:
        row.last_message = last_message
    if last_period_start is not None:
        row.last_period_start = float(last_period_start)
    if last_success_at is not None:
        row.last_success_at = float(last_success_at)
    if next_run_at is not None:
        row.next_run_at = float(next_run_at)
    row.updated_at = now
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@db_retry_on_lock
def create_daily_checkin_log(db: Session, log: schemas.DailyCheckInLogCreate):
    log_data = _dump_schema(log)
    if log_data.get("created_at") is None:
        log_data["created_at"] = time.time()
    row = models.DailyCheckInLog(**log_data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_daily_checkin_logs(
    db: Session,
    *,
    process_id: str | None = None,
    game_id: str | None = None,
    limit: int = 50,
):
    query = db.query(models.DailyCheckInLog)
    if process_id:
        query = query.filter(models.DailyCheckInLog.process_id == process_id)
    if game_id:
        query = query.filter(models.DailyCheckInLog.game_id == game_id)
    return query.order_by(models.DailyCheckInLog.attempted_at.desc()).limit(max(1, min(int(limit), 200))).all()


def get_daily_checkin_logs_for_period(
    db: Session,
    *,
    process_id: str,
    game_id: str,
    period_start: float,
    period_end: float,
):
    return (
        db.query(models.DailyCheckInLog)
        .filter(models.DailyCheckInLog.process_id == process_id)
        .filter(models.DailyCheckInLog.game_id == game_id)
        .filter(models.DailyCheckInLog.period_start == float(period_start))
        .filter(models.DailyCheckInLog.period_end == float(period_end))
        .order_by(models.DailyCheckInLog.attempted_at.desc())
        .all()
    )


def get_provider_credential_health(db: Session, provider: str):
    return (
        db.query(models.ProviderCredentialHealth)
        .filter(models.ProviderCredentialHealth.provider == provider)
        .first()
    )


def get_provider_credential_health_rows(db: Session):
    return (
        db.query(models.ProviderCredentialHealth)
        .order_by(models.ProviderCredentialHealth.provider.asc())
        .all()
    )


@db_retry_on_lock
def upsert_provider_credential_health(
    db: Session,
    *,
    provider: str,
    status: str,
    reason: str | None = None,
    message: str | None = None,
    source: str | None = None,
    process_id: str | None = None,
    game_id: str | None = None,
    detected_at: float | None = None,
    timestamp: float | None = None,
):
    now = float(time.time() if timestamp is None else timestamp)
    observed_at = float(now if detected_at is None else detected_at)
    row = get_provider_credential_health(db, provider)
    if row is None:
        row = models.ProviderCredentialHealth(
            provider=provider,
            created_at=now,
            detected_at=observed_at,
            updated_at=now,
        )
    row.status = status or "unknown"
    row.reason = reason
    row.message = message
    row.source = source
    row.process_id = process_id
    row.game_id = game_id
    row.detected_at = observed_at
    row.updated_at = now
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

# global setting management functions
@db_retry_on_lock
def get_settings(db: Session):
    """ GlobalSettings를 조회합니다. 없으면 기본값으로 생성하여 반환합니다. """
    db_settings = db.query(models.GlobalSettings).filter(models.GlobalSettings.id == 1).first()

    if not db_settings:
        print("기본 설정을 생성합니다.")
        # 기본 스키마로부터 딕셔너리를 만듭니다.
        default_data = _dump_schema(schemas.GlobalSettingsSchema())
        # id를 추가하고 DB 모델 객체를 생성합니다.
        db_settings = models.GlobalSettings(id=1, **default_data)

        db.add(db_settings)
        db.commit()
        db.refresh(db_settings)

    return db_settings

@db_retry_on_lock
def update_settings(
    db: Session,
    settings: schemas.GlobalSettingsSchema,
    *,
    actor: str = "settings_full_update",
    operation_kind: str = "settings_update",
    allowed_fields: set[str] | None = None,
    override_token: str | None = None,
):
    db_settings = get_settings(db)
    if db_settings:
        update_data = _dump_schema(settings)
        supplied_fields = _schema_fields_set(settings)
        if (
            supplied_fields
            and "sidebar_enabled" in supplied_fields
            and "sidebar_mode" not in supplied_fields
            and update_data.get("sidebar_enabled") is False
            and update_data.get("sidebar_mode") == "game"
        ):
            update_data["sidebar_mode"] = SIDEBAR_MODE_DISABLED
        _normalize_sidebar_settings_update(db_settings, update_data)
        allowed = set(allowed_fields) if allowed_fields is not None else beholder.allowed_settings_fields_for_actor(actor)
        changed = _changed_fields(db_settings, update_data)
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.GLOBAL_SETTINGS_TABLE},
            allowed_columns={beholder.GLOBAL_SETTINGS_TABLE: allowed},
            evidence={
                "changed_fields": sorted(changed),
                "context": {"settings_id": 1},
                "proposed_values": {key: update_data.get(key) for key in sorted(changed)},
            },
            override_token=override_token,
        )
        beholder.guard_settings_update(db, db_settings, update_data, operation)
        if changed:
            _backup_settings_snapshot_or_raise(db_settings, reason=operation_kind)
        for key, value in update_data.items():
            if hasattr(db_settings, key):
                setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
    return db_settings


@db_retry_on_lock
def patch_settings(
    db: Session,
    updates: dict[str, Any],
    *,
    actor: str,
    allowed_fields: set[str] | None = None,
    operation_kind: str = "settings_patch",
    override_token: str | None = None,
):
    db_settings = get_settings(db)
    update_data = {key: value for key, value in updates.items() if value is not None and hasattr(db_settings, key)}
    _normalize_sidebar_settings_update(db_settings, update_data)
    allowed = set(allowed_fields) if allowed_fields is not None else beholder.allowed_settings_fields_for_actor(actor)
    changed = _changed_fields(db_settings, update_data)
    operation = beholder.BeholderOperation(
        kind=operation_kind,
        actor=actor,
        allowed_tables={beholder.GLOBAL_SETTINGS_TABLE},
        allowed_columns={beholder.GLOBAL_SETTINGS_TABLE: allowed},
        evidence={
            "changed_fields": sorted(changed),
            "context": {"settings_id": 1},
            "proposed_values": {key: update_data.get(key) for key in sorted(changed)},
        },
        override_token=override_token,
    )
    beholder.guard_settings_update(db, db_settings, update_data, operation)
    if changed:
        _backup_settings_snapshot_or_raise(db_settings, reason=operation_kind)
    for key, value in update_data.items():
        setattr(db_settings, key, value)
    db.commit()
    db.refresh(db_settings)
    return db_settings


# process session management functions
@db_retry_on_lock
def create_session(
    db: Session,
    session: schemas.ProcessSessionCreate,
    *,
    operation_kind: str = "runtime_start",
    actor: str = "process_monitor",
    override_token: str | None = None,
):
    """새로운 프로세스 세션 시작 기록"""
    runtime_evidence = getattr(session, "runtime_evidence", None) or {}
    context = {
        **runtime_evidence,
        "process_id": session.process_id,
        "process_name": session.process_name,
        "requested_start_timestamp": session.start_timestamp,
        "requested_user_preset_id": getattr(session, "user_preset_id", None),
    }
    operation = beholder.BeholderOperation(
        kind=operation_kind,
        actor=actor,
        allowed_tables={beholder.PROCESS_SESSIONS_TABLE},
        allowed_columns={beholder.PROCESS_SESSIONS_TABLE: beholder.SESSION_FIELDS},
        evidence={
            "changed_fields": ["process_id", "process_name", "start_timestamp"],
            "context": context,
            "proposed_values": {
                "process_id": session.process_id,
                "process_name": session.process_name,
                "start_timestamp": session.start_timestamp,
                "user_preset_id": getattr(session, "user_preset_id", None),
            },
        },
        override_token=override_token,
    )
    beholder.guard_session_start(db, session, operation)
    session_data = session.dict()
    session_data.pop("runtime_evidence", None)
    session_data.setdefault("session_owner", actor)
    if not session_data.get("session_owner"):
        session_data["session_owner"] = actor
    session_data.setdefault("session_status", "open")
    session_data.setdefault("heartbeat_timestamp", session_data.get("start_timestamp"))
    db_session = models.ProcessSession(**session_data)
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session


@db_retry_on_lock
def end_session(
    db: Session,
    session_id: int,
    end_timestamp: float,
    stamina_at_end: Optional[int] = None,
    resource_percent_at_end: Optional[float] = None,
    *,
    operation_kind: str = "runtime_stop",
    actor: str = "process_monitor",
    close_reason: str = "process_exit",
    override_token: str | None = None,
):
    """프로세스 세션 종료 기록"""
    db_session = db.query(models.ProcessSession).filter(models.ProcessSession.id == session_id).first()
    if db_session:
        changed_fields = ["end_timestamp", "session_duration", "session_status", "close_reason", "heartbeat_timestamp"]
        proposed_values = {
            "end_timestamp": end_timestamp,
            "session_duration": end_timestamp - db_session.start_timestamp,
            "session_status": "closed",
            "close_reason": close_reason,
            "heartbeat_timestamp": end_timestamp,
        }
        if stamina_at_end is not None:
            changed_fields.append("stamina_at_end")
            proposed_values["stamina_at_end"] = stamina_at_end
        if resource_percent_at_end is not None:
            changed_fields.append("resource_percent_at_end")
            proposed_values["resource_percent_at_end"] = resource_percent_at_end
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.PROCESS_SESSIONS_TABLE, beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={beholder.PROCESS_SESSIONS_TABLE: beholder.SESSION_FIELDS},
            evidence={
                "changed_fields": changed_fields,
                "context": {"session_id": session_id, "process_id": db_session.process_id, "process_name": db_session.process_name},
                "proposed_values": proposed_values,
            },
            override_token=override_token,
        )
        beholder.guard_session_end(db, db_session, end_timestamp, operation)
        if stamina_at_end is not None:
            beholder.guard_process_session_update(db, db_session, {"stamina_at_end"}, operation)
        if resource_percent_at_end is not None:
            beholder.guard_process_session_update(db, db_session, {"resource_percent_at_end"}, operation)
        _backup_model_snapshot_or_raise(db_session, table=beholder.PROCESS_SESSIONS_TABLE, reason=operation_kind)
        db_session.end_timestamp = end_timestamp
        db_session.session_duration = end_timestamp - db_session.start_timestamp
        db_session.session_status = "closed"
        db_session.close_reason = close_reason
        db_session.heartbeat_timestamp = end_timestamp
        if stamina_at_end is not None:
            db_session.stamina_at_end = stamina_at_end
        if resource_percent_at_end is not None:
            db_session.resource_percent_at_end = resource_percent_at_end
        db.commit()
        db.refresh(db_session)
    return db_session


def get_active_session_by_process_id(db: Session, process_id: str):
    """특정 프로세스의 활성 세션 조회 (end_timestamp가 NULL인 세션)"""
    return db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == process_id,
        models.ProcessSession.end_timestamp == None
    ).first()


def get_sessions_by_process_id(db: Session, process_id: str, skip: int = 0, limit: int = 100):
    """특정 프로세스의 모든 세션 조회"""
    return db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == process_id
    ).order_by(models.ProcessSession.start_timestamp.desc()).offset(skip).limit(limit).all()


def get_all_sessions(db: Session, skip: int = 0, limit: int = 100):
    """모든 세션 조회"""
    return db.query(models.ProcessSession).order_by(
        models.ProcessSession.start_timestamp.desc()
    ).offset(skip).limit(limit).all()


def get_last_session(db: Session, process_id: str):
    """특정 프로세스의 가장 최근 완료된 세션을 반환합니다."""
    return db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == process_id,
        models.ProcessSession.end_timestamp != None
    ).order_by(models.ProcessSession.end_timestamp.desc()).first()


@db_retry_on_lock
def update_session_stamina(
    db: Session,
    session_id: int,
    stamina_at_end: int,
    *,
    actor: str = "runtime_stamina_tracker",
    operation_kind: str = "session_stamina_update",
    override_token: str | None = None,
) -> bool:
    """세션의 종료 스태미나 값을 업데이트합니다."""
    db_session = db.query(models.ProcessSession).filter(models.ProcessSession.id == session_id).first()
    if db_session:
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.PROCESS_SESSIONS_TABLE},
            allowed_columns={beholder.PROCESS_SESSIONS_TABLE: {"stamina_at_end"}},
            evidence={
                "changed_fields": ["stamina_at_end"],
                "context": {"session_id": session_id},
                "proposed_values": {"stamina_at_end": stamina_at_end},
            },
            override_token=override_token,
        )
        beholder.guard_process_session_update(db, db_session, {"stamina_at_end"}, operation)
        _backup_model_snapshot_or_raise(db_session, table=beholder.PROCESS_SESSIONS_TABLE, reason=operation_kind)
        db_session.stamina_at_end = stamina_at_end
        db.commit()
        db.refresh(db_session)
        return True
    return False


@db_retry_on_lock
def update_session_resource(
    db: Session,
    session_id: int,
    resource_percent_at_end: float,
    *,
    actor: str = "resource_slow_followup",
    operation_kind: str = "resource_session_percent_rewrite",
    override_token: str | None = None,
) -> bool:
    """세션의 종료 외부 리소스 백분율을 업데이트합니다."""
    db_session = db.query(models.ProcessSession).filter(models.ProcessSession.id == session_id).first()
    if db_session:
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.PROCESS_SESSIONS_TABLE},
            allowed_columns={beholder.PROCESS_SESSIONS_TABLE: {"resource_percent_at_end"}},
            evidence={
                "changed_fields": ["resource_percent_at_end"],
                "context": {"session_id": session_id},
                "proposed_values": {"resource_percent_at_end": resource_percent_at_end},
            },
            override_token=override_token,
        )
        beholder.guard_process_session_update(db, db_session, {"resource_percent_at_end"}, operation)
        _backup_model_snapshot_or_raise(db_session, table=beholder.PROCESS_SESSIONS_TABLE, reason=operation_kind)
        db_session.resource_percent_at_end = resource_percent_at_end
        db.commit()
        db.refresh(db_session)
        return True
    return False


@db_retry_on_lock
def mark_shortcut_opened(
    db: Session,
    shortcut_id: str,
    opened_at: float,
    *,
    actor: str = "web_shortcut_runtime",
    operation_kind: str = "shortcut_opened",
    override_token: str | None = None,
):
    shortcut = get_shortcut_by_id(db, shortcut_id)
    if not shortcut:
        return None
    if shortcut.refresh_time_str:
        _guard_write(
            db,
            table=beholder.WEB_SHORTCUTS_TABLE,
            columns={"last_reset_timestamp"},
            actor=actor,
            operation_kind=operation_kind,
            allowed_fields={"last_reset_timestamp"},
            context={"shortcut_id": shortcut_id, "shortcut_name": shortcut.name},
            override_token=override_token,
            proposed_values={"last_reset_timestamp": opened_at},
        )
        _backup_model_snapshot_or_raise(shortcut, table=beholder.WEB_SHORTCUTS_TABLE, reason=operation_kind)
        shortcut.last_reset_timestamp = opened_at
        db.add(shortcut)
        db.commit()
        db.refresh(shortcut)
    return shortcut
