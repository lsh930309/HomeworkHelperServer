"""Beholder incident API shared by PyQt and the new Tauri GUI."""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.data import beholder, crud, models
from src.data.database import SessionLocal, base_dir, data_dir, db_path, engine

router = APIRouter(prefix="/api/beholder", tags=["beholder"])


_RESTORE_LOCK = threading.Lock()


def _require_valid_sqlite_backup(path: str | Path) -> None:
    try:
        with sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or str(result[0]).lower() != "ok":
                raise HTTPException(status_code=422, detail="선택한 백업 DB integrity check가 실패했습니다.")
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=422, detail=f"백업 DB를 안전하게 열 수 없습니다: {exc}") from exc


def _copy_sqlite_database(source: str | Path, target: str | Path) -> None:
    with sqlite3.connect(f"file:{Path(source)}?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

BACKUP_SUMMARY_TABLES = {
    "managed_processes": "게임",
    "web_shortcuts": "웹 바로가기",
    "process_sessions": "플레이 기록",
    "global_settings": "설정",
    "beholder_incidents": "비홀더 사건",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ResolveRequest(BaseModel):
    action: str


class RuntimeHeartbeatRequest(BaseModel):
    app_instance_id: str
    runtime_kind: str = "pyqt"
    shutdown: bool = False


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


@router.get("/backups")
def list_backups() -> dict[str, Any]:
    return {"backups": _backup_files(), "current_db_path": db_path, "current": _db_summary(db_path)}


class RestoreRequest(BaseModel):
    slot: int


@router.post("/backups/restore-preview")
def restore_preview(payload: RestoreRequest) -> dict[str, Any]:
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
def restore_backup(payload: RestoreRequest) -> dict[str, Any]:
    files = {item["slot"]: item for item in _backup_files()}
    if payload.slot not in files:
        raise HTTPException(status_code=404, detail="선택한 백업을 찾을 수 없습니다.")
    source = files[payload.slot]["path"]
    _require_valid_sqlite_backup(source)

    with _RESTORE_LOCK:
        before_path = os.path.join(data_dir, f"app_data.before_beholder_restore.{int(time.time())}.db")
        if os.path.exists(db_path):
            _copy_sqlite_database(db_path, before_path)

        # Close pooled SQLite handles before replacing the live DB; otherwise Windows
        # file locks or stale pooled connections can make restore appear successful
        # while the app continues to serve the old database.
        engine.dispose()
        for suffix in ("-wal", "-shm"):
            sidecar = db_path + suffix
            if os.path.exists(sidecar):
                os.remove(sidecar)
        _copy_sqlite_database(source, db_path)
        engine.dispose()

    return {"ok": True, "restored_from": source, "previous_snapshot": before_path}
