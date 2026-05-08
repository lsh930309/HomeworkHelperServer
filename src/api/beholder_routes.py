"""Beholder incident API shared by PyQt and the new Tauri GUI."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.data import beholder, models
from src.data.database import SessionLocal, base_dir, data_dir, db_path

router = APIRouter(prefix="/api/beholder", tags=["beholder"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ResolveRequest(BaseModel):
    action: str


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


def _backup_files() -> list[dict[str, Any]]:
    backup_dir = Path(base_dir) / "backups"
    files = []
    for i in range(1, 4):
        path = backup_dir / f"app_data.backup.{i}.db"
        if path.exists():
            stat = path.stat()
            files.append({"slot": i, "path": str(path), "modified_at": stat.st_mtime, "size": stat.st_size})
    return files


@router.get("/backups")
def list_backups() -> dict[str, Any]:
    return {"backups": _backup_files(), "current_db_path": db_path}


class RestoreRequest(BaseModel):
    slot: int


@router.post("/backups/restore-preview")
def restore_preview(payload: RestoreRequest) -> dict[str, Any]:
    files = {item["slot"]: item for item in _backup_files()}
    if payload.slot not in files:
        raise HTTPException(status_code=404, detail="선택한 백업을 찾을 수 없습니다.")
    current_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    return {"backup": files[payload.slot], "current": {"path": db_path, "size": current_size}}


@router.post("/backups/restore")
def restore_backup(payload: RestoreRequest) -> dict[str, Any]:
    files = {item["slot"]: item for item in _backup_files()}
    if payload.slot not in files:
        raise HTTPException(status_code=404, detail="선택한 백업을 찾을 수 없습니다.")
    source = files[payload.slot]["path"]
    before_path = os.path.join(data_dir, f"app_data.before_beholder_restore.{int(time.time())}.db")
    if os.path.exists(db_path):
        shutil.copy2(db_path, before_path)
    for suffix in ("-wal", "-shm"):
        sidecar = db_path + suffix
        if os.path.exists(sidecar):
            os.remove(sidecar)
    shutil.copy2(source, db_path)
    return {"ok": True, "restored_from": source, "previous_snapshot": before_path}
