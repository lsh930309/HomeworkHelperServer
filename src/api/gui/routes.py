"""API facade for the next-generation main GUI.

The Tauri/React GUI talks to this router instead of opening the SQLite
database directly.  This preserves the existing AppData database path, backup
flow, WAL settings, and migration behavior owned by ``src.data.database``.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.core.launcher import Launcher
from src.data import crud, models
from src.data.database import SessionLocal
from src.utils.game_preset_manager import GamePresetManager

router = APIRouter(prefix="/api/gui", tags=["main-gui"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _predicted_stamina(process: models.Process) -> tuple[int, int] | None:
    if process.stamina_current is None or process.stamina_max is None:
        return None
    if process.stamina_updated_at is None:
        return int(process.stamina_current), int(process.stamina_max)

    elapsed_seconds = max(0.0, dt.datetime.now().timestamp() - float(process.stamina_updated_at))
    recovered = int(elapsed_seconds / 360)
    predicted = min(int(process.stamina_current) + recovered, int(process.stamina_max))
    return predicted, int(process.stamina_max)


def _progress(process: models.Process, now_dt: dt.datetime) -> dict[str, Any]:
    if process.stamina_tracking_enabled and process.hoyolab_game_id:
        stamina = _predicted_stamina(process)
        if stamina:
            current, max_stamina = stamina
            percent = (current / max_stamina) * 100 if max_stamina > 0 else 0
            return {
                "kind": "stamina",
                "percent": round(percent, 2),
                "label": f"{current}/{max_stamina}",
                "current": current,
                "max": max_stamina,
                "hoyolab_game_id": process.hoyolab_game_id,
            }

    if not process.last_played_timestamp or not process.user_cycle_hours:
        return {"kind": "time", "percent": 0.0, "label": "기록 없음"}

    try:
        last_played_dt = dt.datetime.fromtimestamp(float(process.last_played_timestamp))
        elapsed_hours = (now_dt - last_played_dt).total_seconds() / 3600
        cycle_hours = max(float(process.user_cycle_hours), 0.01)
        percent = min(elapsed_hours / cycle_hours, 1.0) * 100
        remaining_hours = max(cycle_hours - elapsed_hours, 0)
        if remaining_hours >= 24:
            days = int(remaining_hours // 24)
            hours = int(remaining_hours % 24)
            label = f"{days}일 {hours}시간" if hours else f"{days}일"
        elif remaining_hours >= 1:
            label = f"{int(remaining_hours)}시간"
        else:
            label = f"{int(remaining_hours * 60)}분"
        return {"kind": "time", "percent": round(percent, 2), "label": label}
    except Exception:
        return {"kind": "time", "percent": 0.0, "label": "계산 오류"}


def _parse_time(value: str | None) -> dt.time | None:
    try:
        return dt.datetime.strptime(value or "", "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _next_sleep_period(now_dt: dt.datetime, settings: models.GlobalSettings) -> tuple[dt.datetime, dt.datetime] | None:
    sleep_start = _parse_time(settings.sleep_start_time_str)
    sleep_end = _parse_time(settings.sleep_end_time_str)
    if not sleep_start or not sleep_end:
        return None

    start_today = now_dt.replace(hour=sleep_start.hour, minute=sleep_start.minute, second=0, microsecond=0)
    end_today = now_dt.replace(hour=sleep_end.hour, minute=sleep_end.minute, second=0, microsecond=0)
    if sleep_start > sleep_end:
        if now_dt.time() >= sleep_start:
            return start_today, end_today + dt.timedelta(days=1)
        if now_dt.time() < sleep_end:
            return start_today - dt.timedelta(days=1), end_today
        return start_today, end_today + dt.timedelta(days=1)
    if sleep_start <= now_dt.time() < sleep_end:
        return start_today, end_today
    if now_dt.time() < sleep_start:
        return start_today, end_today
    return start_today + dt.timedelta(days=1), end_today + dt.timedelta(days=1)


def _visual_status(
    process: models.Process,
    settings: models.GlobalSettings,
    now_dt: dt.datetime,
    active_ids: set[str],
) -> str:
    if process.id in active_ids:
        return "실행중"

    incomplete = False
    last_played_dt = (
        dt.datetime.fromtimestamp(float(process.last_played_timestamp))
        if process.last_played_timestamp
        else None
    )

    reset_time = _parse_time(process.server_reset_time_str)
    if reset_time:
        reset_today = now_dt.replace(hour=reset_time.hour, minute=reset_time.minute, second=0, microsecond=0)
        current_server_day_start = reset_today - dt.timedelta(days=1) if now_dt.time() < reset_time else reset_today
        if last_played_dt is None or last_played_dt < current_server_day_start:
            incomplete = True

    if not incomplete and process.is_mandatory_time_enabled and process.mandatory_times_str:
        for mandatory in process.mandatory_times_str:
            mandatory_time = _parse_time(mandatory)
            if not mandatory_time:
                continue
            mandatory_today = now_dt.replace(
                hour=mandatory_time.hour,
                minute=mandatory_time.minute,
                second=0,
                microsecond=0,
            )
            if now_dt >= mandatory_today and (last_played_dt is None or last_played_dt < mandatory_today):
                incomplete = True
                break

    original_deadline = None
    if process.user_cycle_hours and last_played_dt:
        original_deadline = last_played_dt + dt.timedelta(hours=float(process.user_cycle_hours))
        if now_dt > original_deadline:
            incomplete = True

    if not incomplete and process.user_cycle_hours and last_played_dt and original_deadline:
        if now_dt < original_deadline:
            sleep_period = _next_sleep_period(now_dt, settings)
            if sleep_period:
                sleep_start, sleep_end = sleep_period
                if sleep_start <= original_deadline < sleep_end:
                    trigger = sleep_start - dt.timedelta(
                        hours=float(settings.sleep_correction_advance_notify_hours or 0)
                    )
                    if now_dt >= trigger and last_played_dt < trigger:
                        incomplete = True

    return "미완료" if incomplete else "완료됨"


def _process_to_gui_row(process: models.Process, status: str, now_dt: dt.datetime) -> dict[str, Any]:
    return {
        "id": process.id,
        "name": process.name,
        "monitoring_path": process.monitoring_path,
        "launch_path": process.launch_path,
        "preferred_launch_type": process.preferred_launch_type or "shortcut",
        "last_played_timestamp": process.last_played_timestamp,
        "server_reset_time_str": process.server_reset_time_str,
        "user_cycle_hours": process.user_cycle_hours,
        "mandatory_times_str": process.mandatory_times_str or [],
        "is_mandatory_time_enabled": bool(process.is_mandatory_time_enabled),
        "user_preset_id": process.user_preset_id,
        "stamina_tracking_enabled": bool(process.stamina_tracking_enabled),
        "hoyolab_game_id": process.hoyolab_game_id,
        "status": status,
        "progress": _progress(process, now_dt),
        "icon_url": f"/api/dashboard/icons/{process.id}?size=128",
    }


def _shortcut_to_gui(shortcut: models.WebShortcut) -> dict[str, Any]:
    return {
        "id": shortcut.id,
        "name": shortcut.name,
        "url": shortcut.url,
        "refresh_time_str": shortcut.refresh_time_str,
        "last_reset_timestamp": shortcut.last_reset_timestamp,
    }


def _settings_to_gui(settings: models.GlobalSettings) -> dict[str, Any]:
    return {
        "theme": settings.theme,
        "always_on_top": bool(settings.always_on_top),
        "hide_on_game": bool(settings.hide_on_game),
        "run_as_admin": bool(settings.run_as_admin),
        "run_on_startup": bool(settings.run_on_startup),
        "sidebar_enabled": bool(settings.sidebar_enabled),
        "sidebar_auto_hide_ms": int(settings.sidebar_auto_hide_ms or 0),
        "screenshot_enabled": bool(settings.screenshot_enabled),
        "recording_enabled": bool(settings.recording_enabled),
    }


@router.get("/main-state")
def get_main_state(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return a DB-safe snapshot for the Tauri/React main window."""
    processes = crud.get_processes(db)
    shortcuts = crud.get_shortcuts(db, limit=500)
    settings = crud.get_settings(db)
    active_ids = {
        session.process_id
        for session in db.query(models.ProcessSession)
        .filter(models.ProcessSession.end_timestamp.is_(None))
        .all()
    }
    now_dt = dt.datetime.now()
    return {
        "generated_at": now_dt.isoformat(),
        "settings": _settings_to_gui(settings),
        "processes": [
            _process_to_gui_row(process, _visual_status(process, settings, now_dt, active_ids), now_dt)
            for process in sorted(processes, key=lambda p: (p.name or "").casefold())
        ],
        "web_shortcuts": [_shortcut_to_gui(shortcut) for shortcut in shortcuts],
        "dashboard_url": "/dashboard",
        "icon_quality": {
            "source": "dashboard-icon-cache",
            "preferred_sizes": [32, 48, 64, 96, 128, 256],
        },
        "db_continuity": {
            "mode": "api-only",
            "direct_sqlite_access": False,
            "appdata_path_owned_by_backend": True,
        },
    }


def _resolve_launch_target(process: models.Process) -> str | None:
    launch_type = process.preferred_launch_type or "shortcut"
    if launch_type == "direct":
        return process.monitoring_path or process.launch_path
    if launch_type == "shortcut":
        return process.launch_path or process.monitoring_path
    if launch_type == "launcher":
        launcher_path = None
        if process.user_preset_id:
            preset = GamePresetManager().get_preset_by_id(process.user_preset_id)
            if preset and preset.get("launcher_patterns"):
                launch_dir = os.path.dirname(process.launch_path or process.monitoring_path or "")
                for pattern in preset["launcher_patterns"]:
                    candidate = os.path.join(launch_dir, pattern)
                    if os.path.exists(candidate):
                        launcher_path = candidate
                        break
        return launcher_path or process.launch_path or process.monitoring_path
    return process.launch_path or process.monitoring_path


@router.post("/processes/{process_id}/launch")
def launch_process(process_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Launch a configured process through the existing launcher code path."""
    process = crud.get_process_by_id(db, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    target = _resolve_launch_target(process)
    if not target:
        raise HTTPException(status_code=400, detail="실행 경로가 없습니다.")
    settings = crud.get_settings(db)
    success = Launcher(run_as_admin=bool(settings.run_as_admin)).launch_process(target)
    if not success:
        raise HTTPException(status_code=500, detail="프로세스 실행에 실패했습니다.")
    return {"ok": True, "process_id": process.id, "launch_target": target}
