from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError
from src.data import models
from src.data import schemas
from src.data import beholder
from typing import Any, Optional
from pathlib import Path
import json
import uuid
import time
import logging
import os
import psutil

from src.data.database import base_dir

logger = logging.getLogger(__name__)

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
        evidence={"changed_fields": sorted(guard_columns), "context": {"process_id": process_id, "process_name": process_data.get("name")}},
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
            evidence={"changed_fields": ["id"], "context": {"process_id": process_id, "process_name": db_process.name}},
            override_token=override_token,
        )
        beholder.guard_process_delete(db, db_process, operation)
        backup_model_snapshot(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
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
        changed = {key for key, value in update_data.items() if hasattr(db_process, key) and getattr(db_process, key) != value}
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={beholder.MANAGED_PROCESSES_TABLE: beholder.PROCESS_EDITOR_FIELDS - {"id"}},
            evidence={"changed_fields": sorted(changed), "context": {"process_id": process_id, "process_name": getattr(db_process, "name", None)}},
            override_token=override_token,
        )
        beholder.guard_process_update(db, db_process, update_data, operation, changed)
        if changed:
            backup_model_snapshot(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
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
            evidence={"changed_fields": sorted(changed), "context": {"process_id": process_id, "process_name": getattr(db_process, "name", None)}},
            override_token=override_token,
        )
        beholder.guard_process_update(db, db_process, update_data, operation, changed)
        if changed:
            backup_model_snapshot(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
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
        }
        update_data = {key: value for key, value in update_data.items() if value is not None}
        changed = {key for key, value in update_data.items() if getattr(db_process, key) != value}
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.MANAGED_PROCESSES_TABLE},
            allowed_columns={beholder.MANAGED_PROCESSES_TABLE: {"last_played_timestamp", "stamina_current", "stamina_max", "stamina_updated_at"}},
            evidence={"changed_fields": sorted(changed), "context": {"process_id": process_id, "process_name": getattr(db_process, "name", None)}},
            override_token=override_token,
        )
        beholder.guard_process_update(db, db_process, update_data, operation, changed)
        if changed:
            backup_model_snapshot(db_process, table=beholder.MANAGED_PROCESSES_TABLE, reason=operation_kind)
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
        changed = {key for key, value in update_data.items() if hasattr(db_shortcut, key) and getattr(db_shortcut, key) != value}
        _guard_write(
            db,
            table=beholder.WEB_SHORTCUTS_TABLE,
            columns=changed,
            actor=actor,
            operation_kind=operation_kind,
            allowed_fields=beholder.WEB_SHORTCUT_EDITOR_FIELDS - {"id"},
            context={"shortcut_id": shortcut_id, "shortcut_name": getattr(db_shortcut, "name", None)},
            override_token=override_token,
        )
        if changed:
            backup_model_snapshot(db_shortcut, table=beholder.WEB_SHORTCUTS_TABLE, reason=operation_kind)
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
        )
        backup_model_snapshot(db_shortcut, table=beholder.WEB_SHORTCUTS_TABLE, reason=operation_kind)
        db.delete(db_shortcut)
        db.commit()
    return db_shortcut

def _dump_schema(model: Any, **kwargs: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


def _model_to_dict(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


def backup_model_snapshot(model: Any, *, table: str, reason: str, max_backups: int = 50) -> str | None:
    try:
        backup_dir = Path(base_dir) / "backups" / "mutations" / table
        backup_dir.mkdir(parents=True, exist_ok=True)
        model_id = getattr(model, "id", "row")
        path = backup_dir / f"{table}.{model_id}.{int(time.time() * 1000)}.{reason}.json"
        payload = {
            "created_at": time.time(),
            "reason": reason,
            "table": table,
            "row": _model_to_dict(model),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshots = sorted(backup_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in snapshots[max_backups:]:
            old.unlink(missing_ok=True)
        return str(path)
    except Exception as exc:
        logger.warning("%s snapshot backup failed: %s", table, exc)
        return None


def _guard_write(db: Session, *, table: str, columns: set[str], actor: str, operation_kind: str, allowed_fields: set[str], context: dict[str, Any] | None = None, override_token: str | None = None) -> beholder.BeholderOperation:
    operation = beholder.BeholderOperation(
        kind=operation_kind,
        actor=actor,
        allowed_tables={table},
        allowed_columns={table: allowed_fields},
        evidence={"changed_fields": sorted(columns), "context": context or {}},
        override_token=override_token,
    )
    beholder.guard_table_write(db, operation, table, columns)
    return operation


def _settings_to_dict(settings: models.GlobalSettings) -> dict[str, Any]:
    fields = beholder.allowed_settings_fields_for_actor("settings_full_update")
    return {field: getattr(settings, field) for field in fields if hasattr(settings, field)}


def _changed_fields(settings: models.GlobalSettings, update_data: dict[str, Any]) -> set[str]:
    return {key for key, value in update_data.items() if hasattr(settings, key) and getattr(settings, key) != value}


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
        allowed = set(allowed_fields) if allowed_fields is not None else beholder.allowed_settings_fields_for_actor(actor)
        changed = _changed_fields(db_settings, update_data)
        operation = beholder.BeholderOperation(
            kind=operation_kind,
            actor=actor,
            allowed_tables={beholder.GLOBAL_SETTINGS_TABLE},
            allowed_columns={beholder.GLOBAL_SETTINGS_TABLE: allowed},
            evidence={"changed_fields": sorted(changed)},
            override_token=override_token,
        )
        beholder.guard_settings_update(db, db_settings, update_data, operation)
        if changed:
            backup_settings_snapshot(db_settings, reason=operation_kind)
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
    allowed = set(allowed_fields) if allowed_fields is not None else beholder.allowed_settings_fields_for_actor(actor)
    changed = _changed_fields(db_settings, update_data)
    operation = beholder.BeholderOperation(
        kind=operation_kind,
        actor=actor,
        allowed_tables={beholder.GLOBAL_SETTINGS_TABLE},
        allowed_columns={beholder.GLOBAL_SETTINGS_TABLE: allowed},
        evidence={"changed_fields": sorted(changed)},
        override_token=override_token,
    )
    beholder.guard_settings_update(db, db_settings, update_data, operation)
    if changed:
        backup_settings_snapshot(db_settings, reason=operation_kind)
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
    operation = beholder.BeholderOperation(
        kind=operation_kind,
        actor=actor,
        allowed_tables={beholder.PROCESS_SESSIONS_TABLE},
        allowed_columns={beholder.PROCESS_SESSIONS_TABLE: beholder.SESSION_FIELDS},
        evidence={
            "changed_fields": ["process_id", "process_name", "start_timestamp"],
            "context": runtime_evidence,
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
        proposed_values = {"end_timestamp": end_timestamp}
        if stamina_at_end is not None:
            changed_fields.append("stamina_at_end")
            proposed_values["stamina_at_end"] = stamina_at_end
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
        override_bypassed = beholder.consume_override_token(db, override_token, operation_kind)
        if not override_bypassed:
            beholder.guard_session_end(db, db_session, end_timestamp, operation)
            if stamina_at_end is not None:
                beholder.guard_process_session_update(db, db_session, {"stamina_at_end"}, operation)
        backup_model_snapshot(db_session, table=beholder.PROCESS_SESSIONS_TABLE, reason=operation_kind)
        db_session.end_timestamp = end_timestamp
        db_session.session_duration = end_timestamp - db_session.start_timestamp
        db_session.session_status = "closed"
        db_session.close_reason = close_reason
        db_session.heartbeat_timestamp = end_timestamp
        if stamina_at_end is not None:
            db_session.stamina_at_end = stamina_at_end
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
        backup_model_snapshot(db_session, table=beholder.PROCESS_SESSIONS_TABLE, reason=operation_kind)
        db_session.stamina_at_end = stamina_at_end
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
        )
        backup_model_snapshot(shortcut, table=beholder.WEB_SHORTCUTS_TABLE, reason=operation_kind)
        shortcut.last_reset_timestamp = opened_at
        db.add(shortcut)
        db.commit()
        db.refresh(shortcut)
    return shortcut
