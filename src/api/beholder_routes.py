"""Beholder incident API shared by the PyQt GUI and internal runtime checks."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.data import beholder, crud, models, schemas
from src.data.database import Base, SessionLocal, auto_migrate_database, base_dir, data_dir, db_path, engine
from src.data.database_coordination import (
    DatabaseAccessUnavailable,
    DatabaseDrainTimeout,
    DatabaseFaultStatePersistenceError,
    create_database_coordinator,
    database_access_error_response,
    database_drain_timeout_response,
)

router = APIRouter(prefix="/api/beholder", tags=["beholder"])
logger = logging.getLogger(__name__)
_lifecycle_replay_lock = threading.Lock()


database_coordinator = create_database_coordinator(data_dir)


def database_access_gate(route_name: str = "legacy_database_request"):
    """Compatibility entry point returning a concurrent ownerless DB lease."""

    return database_coordinator.acquire_request(route_name)


def _require_valid_sqlite_backup(path: str | Path) -> None:
    conn = None
    try:
        conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise HTTPException(status_code=422, detail="선택한 백업 DB integrity check가 실패했습니다.")
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=422, detail=f"백업 DB를 안전하게 열 수 없습니다: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def _copy_sqlite_database(source: str | Path, target: str | Path) -> None:
    src = sqlite3.connect(f"file:{Path(source)}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _checkpoint_live_database(path: str | Path) -> None:
    if not os.path.exists(path):
        return
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=0.25)
        conn.execute("PRAGMA busy_timeout=250")
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result is None or len(result) < 3:
            raise HTTPException(
                status_code=500,
                detail="현재 DB WAL checkpoint 결과를 확인할 수 없어 복구를 중단했습니다.",
            )
        busy, _wal_pages, _checkpointed_pages = result
        if int(busy) != 0:
            raise HTTPException(
                status_code=500,
                detail="현재 DB를 읽는 미조정 연결이 남아 있어 복구를 중단했습니다.",
            )
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"현재 DB WAL 정리에 실패해 복구를 중단했습니다: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def _remove_database_sidecars(path: str | Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = str(path) + suffix
        if os.path.exists(sidecar):
            os.remove(sidecar)


def _cleanup_temporary_database(path: str | Path) -> None:
    for candidate in (str(path), str(path) + "-wal", str(path) + "-shm"):
        if os.path.exists(candidate):
            os.remove(candidate)


def _strict_prepare_live_database() -> None:
    engine.dispose()
    Base.metadata.create_all(bind=engine)
    auto_migrate_database(strict=True)
    _require_valid_sqlite_backup(db_path)


BACKUP_SUMMARY_TABLES = {
    "managed_processes": "게임",
    "web_shortcuts": "웹 바로가기",
    "process_sessions": "플레이 기록",
    "global_settings": "설정",
    "beholder_incidents": "비홀더 사건",
}


def get_db():
    lease = database_coordinator.acquire_request("beholder")
    db = None
    try:
        db = SessionLocal()
        yield db
    finally:
        try:
            if db is not None:
                db.close()
        finally:
            lease.release()


class ResolveRequest(BaseModel):
    action: str


class RuntimeHeartbeatRequest(BaseModel):
    app_instance_id: str
    runtime_kind: str = "pyqt"
    shutdown: bool = False


class LifecycleFailureRequest(BaseModel):
    kind: str
    process_id: str
    process_name: str
    runtime_token: str
    attempts: int
    error_type: str


class OpenSessionReconcileRequest(BaseModel):
    running_process_ids: list[str] = []


@router.get("/incidents/active")
def get_active_incidents(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"incidents": [beholder.incident_to_dict(i) for i in beholder.active_incidents(db)]}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.query(models.BeholderIncident).filter(models.BeholderIncident.id == incident_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Beholder incident를 찾을 수 없습니다.")
    return beholder.incident_to_dict(incident)


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: int, payload: ResolveRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.query(models.BeholderIncident).filter(models.BeholderIncident.id == incident_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Beholder incident를 찾을 수 없습니다.")

    try:
        return beholder.resolve_incident_action(db, incident, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runtime/heartbeat")
def update_runtime_heartbeat(payload: RuntimeHeartbeatRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = crud.upsert_app_runtime_heartbeat(
        db,
        app_instance_id=payload.app_instance_id,
        runtime_kind=payload.runtime_kind,
        shutdown=payload.shutdown,
    )
    return {
        "ok": True,
        "app_instance_id": row.app_instance_id,
        "runtime_kind": row.runtime_kind,
        "boot_id": row.boot_id,
        "started_at": row.started_at,
        "last_heartbeat_at": row.last_heartbeat_at,
        "last_shutdown_at": row.last_shutdown_at,
    }


def _record_lifecycle_failure_incident(
    db: Session,
    *,
    kind: str,
    process_id: str,
    process_name: str,
    runtime_token: str,
    attempts: int,
    error_type: str,
) -> models.BeholderIncident:
    """Return the one incident associated with a stable lifecycle event."""

    target = f"process_id={process_id};kind={kind};token={runtime_token}"
    existing = (
        db.query(models.BeholderIncident)
        .filter(
            models.BeholderIncident.operation_kind == "runtime_lifecycle_persistence_failure",
            models.BeholderIncident.target_summary == target,
        )
        .order_by(models.BeholderIncident.id.desc())
        .first()
    )
    if existing is None:
        operation = beholder.BeholderOperation(
            kind="runtime_lifecycle_persistence_failure",
            actor="process_monitor",
            evidence={"process_id": process_id, "kind": kind},
        )
        existing = beholder.create_incident(
            db,
            severity=beholder.SEVERITY_WARNING,
            operation=operation,
            target_summary=target,
            suspected_cause=(
                f"게임 {kind} 기록을 {max(0, attempts)}회 시도했으나 "
                f"완료를 확인하지 못했습니다 ({error_type[:80]})."
            ),
            current_state_summary="OS 실행 상태 표시는 즉시 반영됐지만 DB lifecycle 확정은 보류됐습니다.",
            proposed_change_summary="다음 startup reconcile에서 동일 lease token으로 재확인합니다.",
            risk_score=55,
            risk_factors=["runtime_state_ambiguous"],
            safe_recommendation="앱과 API 연결을 확인한 뒤 재시작하여 lifecycle reconcile을 수행하세요.",
            user_title=f"{process_name} 실행 기록을 확정하지 못했습니다",
            user_summary="게임 실행 표시는 유지되지만 플레이 기록 저장 여부를 다시 확인해야 합니다.",
            user_impact="중복 기록을 만들지 않도록 동일 token 재시도 대상으로 보존했습니다.",
            recommended_action="quarantine",
            available_actions=[
                {
                    "id": "quarantine",
                    "label": "재시작 후 재확인",
                    "description": "현재 상태를 보존하고 다음 startup reconcile에서 확인합니다.",
                    "recommended": True,
                },
                {
                    "id": "deny",
                    "label": "확인 완료",
                    "description": "진단만 확인하고 사건을 닫습니다.",
                },
            ],
        )
    return existing


@router.post("/runtime/lifecycle-failure")
def record_lifecycle_failure(
    payload: LifecycleFailureRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Persist an exhausted GUI lifecycle retry as a user-visible incident."""

    with _lifecycle_replay_lock:
        existing = _record_lifecycle_failure_incident(
            db,
            kind=payload.kind,
            process_id=payload.process_id,
            process_name=payload.process_name,
            runtime_token=payload.runtime_token,
            attempts=payload.attempts,
            error_type=payload.error_type,
        )
    return {"ok": True, "incident": beholder.incident_to_dict(existing)}


@router.post("/open-sessions/reconcile")
def reconcile_open_sessions(payload: OpenSessionReconcileRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    incidents = beholder.create_open_session_recovery_incidents(
        db,
        running_process_ids=set(payload.running_process_ids),
    )
    return {"incidents": [beholder.incident_to_dict(i) for i in incidents]}


def _db_summary(path: str | Path) -> dict[str, Any]:
    db_file = Path(path)
    exists = db_file.exists()
    summary: dict[str, Any] = {
        "path": str(db_file),
        "exists": exists,
        "size": db_file.stat().st_size if exists else 0,
        "modified_at": db_file.stat().st_mtime if exists else None,
        "table_counts": {},
        "integrity": "missing" if not exists else "unknown",
        "user_summary": "DB 파일이 없습니다." if not exists else "백업 내용을 확인 중입니다.",
    }
    if not exists:
        return summary

    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            summary["integrity"] = integrity[0] if integrity else "unknown"
            existing_tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in BACKUP_SUMMARY_TABLES:
                if table in existing_tables:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    summary["table_counts"][table] = int(count)
        finally:
            conn.close()
        counts = summary["table_counts"]
        game_count = counts.get("managed_processes", 0)
        session_count = counts.get("process_sessions", 0)
        shortcut_count = counts.get("web_shortcuts", 0)
        summary["user_summary"] = (
            f"게임 {game_count}개, 웹 바로가기 {shortcut_count}개, 플레이 기록 {session_count}건이 들어 있습니다."
        )
    except Exception as exc:
        summary["integrity"] = "unreadable"
        summary["error"] = str(exc)
        summary["user_summary"] = "백업 DB를 읽어 요약할 수 없습니다. 파일 손상 또는 잠금 가능성이 있습니다."
    return summary


def _backup_files() -> list[dict[str, Any]]:
    backup_dir = Path(base_dir) / "backups"
    files = []
    for i in range(1, 4):
        path = backup_dir / f"app_data.backup.{i}.db"
        if path.exists():
            stat = path.stat()
            summary = _db_summary(path)
            files.append({
                "slot": i,
                "path": str(path),
                "modified_at": stat.st_mtime,
                "size": stat.st_size,
                "summary": summary,
                "user_summary": summary["user_summary"],
                "integrity": summary["integrity"],
            })
    return files


def _acquire_backup_read_lease(route_name: str):
    """Coordinate live-DB summaries with normal restore and fault recovery.

    Faulted mode exposes only this explicit recovery read admission.  Both
    lease types share the same active counter, so a restore cannot enter its
    replace section until every summary connection has closed.
    """

    if database_coordinator.snapshot().mode == "faulted":
        return database_coordinator.acquire_fault_recovery_read(route_name)
    return database_coordinator.acquire_request(route_name)


@router.get("/backups")
def list_backups() -> Any:
    try:
        lease = _acquire_backup_read_lease("GET /api/beholder/backups")
    except DatabaseAccessUnavailable as exc:
        return database_access_error_response(exc)
    with lease:
        return {
            "backups": _backup_files(),
            "current_db_path": db_path,
            "current": _db_summary(db_path),
        }


class RestoreRequest(BaseModel):
    slot: int


@router.post("/backups/restore-preview")
def restore_preview(payload: RestoreRequest) -> Any:
    try:
        lease = _acquire_backup_read_lease("POST /api/beholder/backups/restore-preview")
    except DatabaseAccessUnavailable as exc:
        return database_access_error_response(exc)
    with lease:
        files = {item["slot"]: item for item in _backup_files()}
        if payload.slot not in files:
            raise HTTPException(status_code=404, detail="선택한 백업을 찾을 수 없습니다.")
        current = _db_summary(db_path)
        backup = files[payload.slot]
        return {
            "backup": backup,
            "current": current,
            "impact": {
                "will_replace_current_db": True,
                "previous_snapshot_will_be_created": os.path.exists(db_path),
                "summary": (
                    f"현재 DB를 backup.{payload.slot}의 내용으로 교체합니다. "
                    "복구 직전 현재 DB는 별도 snapshot으로 보존됩니다."
                ),
            },
        }


@router.post("/backups/restore")
def restore_backup(payload: RestoreRequest) -> Any:
    files = {item["slot"]: item for item in _backup_files()}
    if payload.slot not in files:
        raise HTTPException(status_code=404, detail="선택한 백업을 찾을 수 없습니다.")
    source = files[payload.slot]["path"]
    _require_valid_sqlite_backup(source)
    timestamp = int(time.time() * 1000)
    operation_id = f"{timestamp}.{uuid.uuid4().hex}"
    before_path = os.path.join(data_dir, f"app_data.before_beholder_restore.{operation_id}.db")
    restore_tmp = os.path.join(data_dir, f"app_data.restore_tmp.{operation_id}.db")
    rollback_tmp = os.path.join(data_dir, f"app_data.rollback_tmp.{operation_id}.db")

    # Copy and validate the selected backup before rejecting normal DB traffic.
    try:
        _copy_sqlite_database(source, restore_tmp)
        _require_valid_sqlite_backup(restore_tmp)
    except Exception:
        _cleanup_temporary_database(restore_tmp)
        raise

    snapshot = database_coordinator.snapshot()
    try:
        if snapshot.mode == "faulted":
            maintenance = database_coordinator.begin_fault_recovery("beholder_backup_restore")
        else:
            maintenance = database_coordinator.begin_maintenance("beholder_backup_restore")
    except DatabaseDrainTimeout as exc:
        _cleanup_temporary_database(restore_tmp)
        return database_drain_timeout_response(exc)
    except DatabaseAccessUnavailable as exc:
        _cleanup_temporary_database(restore_tmp)
        return database_access_error_response(exc)
    except DatabaseFaultStatePersistenceError as exc:
        _cleanup_temporary_database(restore_tmp)
        logger.exception("DB restore durable guard 생성 실패")
        return JSONResponse(
            status_code=500,
            content={
                "detail": "database restore failed before live database replacement",
                "code": "database_restore_failed",
                "restore_error": str(exc),
            },
        )

    live_replaced = False
    try:
        with maintenance:
            try:
                engine.dispose()
                if os.path.exists(db_path):
                    _copy_sqlite_database(db_path, before_path)
                    _require_valid_sqlite_backup(before_path)
                _checkpoint_live_database(db_path)
                _remove_database_sidecars(db_path)
                os.replace(restore_tmp, db_path)
                live_replaced = True
                _strict_prepare_live_database()
            except Exception as restore_exc:
                engine.dispose()
                if live_replaced:
                    if os.path.exists(before_path):
                        try:
                            _copy_sqlite_database(before_path, rollback_tmp)
                            _require_valid_sqlite_backup(rollback_tmp)
                            _remove_database_sidecars(db_path)
                            os.replace(rollback_tmp, db_path)
                            _strict_prepare_live_database()
                        except Exception as rollback_exc:
                            try:
                                maintenance.mark_faulted("database_restore_rollback_failed")
                            except DatabaseFaultStatePersistenceError:
                                logger.exception(
                                    "DB restore rollback 실패 sentinel 저장 실패; durable guard를 유지합니다."
                                )
                            return JSONResponse(
                                status_code=500,
                                content={
                                    "detail": "database restore and rollback failed",
                                    "code": "database_restore_rollback_failed",
                                    "restore_error": str(restore_exc),
                                    "rollback_error": str(rollback_exc),
                                },
                            )
                        return JSONResponse(
                            status_code=500,
                            content={
                                "detail": "database restore failed and previous database was restored",
                                "code": "database_restore_rolled_back",
                                "restore_error": str(restore_exc),
                            },
                        )
                    try:
                        maintenance.mark_faulted("database_restore_rollback_unavailable")
                    except DatabaseFaultStatePersistenceError:
                        logger.exception(
                            "DB restore rollback 부재 sentinel 저장 실패; durable guard를 유지합니다."
                        )
                    return JSONResponse(
                        status_code=500,
                        content={
                            "detail": "database restore failed and no rollback snapshot was available",
                            "code": "database_restore_rollback_unavailable",
                            "restore_error": str(restore_exc),
                        },
                    )
                return JSONResponse(
                    status_code=500,
                    content={
                        "detail": "database restore failed before live database replacement",
                        "code": "database_restore_failed",
                        "restore_error": str(restore_exc),
                    },
                )
    finally:
        engine.dispose()
        for temporary in (restore_tmp, rollback_tmp):
            _cleanup_temporary_database(temporary)

    return {"ok": True, "restored_from": source, "previous_snapshot": before_path}
