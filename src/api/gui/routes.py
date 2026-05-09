"""API facade for the next-generation main GUI.

The Tauri/React GUI talks to this router instead of opening the SQLite
database directly.  This preserves the existing AppData database path, backup
flow, WAL settings, and migration behavior owned by ``src.data.database``.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import time
from typing import Any, Iterable
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.launcher import Launcher
from src.data import crud, models, schemas
from src.data.database import SessionLocal
from src.utils.game_preset_manager import GamePresetManager

try:
    from src.utils.windows import set_startup_shortcut
except Exception:
    def set_startup_shortcut(enable: bool) -> bool:
        return False

try:
    from src.utils.admin import is_admin, restart_as_normal, run_as_admin
except Exception:
    def is_admin() -> bool:
        return False

    def restart_as_normal() -> bool:
        return False

    def run_as_admin() -> bool:
        return False

router = APIRouter(prefix="/api/gui", tags=["main-gui"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _dump_model(model: BaseModel, **kwargs: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


class SettingsPatch(BaseModel):
    sleep_start_time_str: str | None = None
    sleep_end_time_str: str | None = None
    sleep_correction_advance_notify_hours: float | None = None
    cycle_deadline_advance_notify_hours: float | None = None
    run_on_startup: bool | None = None
    always_on_top: bool | None = None
    run_as_admin: bool | None = None
    notify_on_mandatory_time: bool | None = None
    notify_on_cycle_deadline: bool | None = None
    notify_on_sleep_correction: bool | None = None
    notify_on_daily_reset: bool | None = None
    stamina_notify_enabled: bool | None = None
    stamina_notify_threshold: int | None = None
    theme: str | None = None
    hide_on_game: bool | None = None
    sidebar_enabled: bool | None = None
    sidebar_auto_hide_ms: int | None = None
    sidebar_edge_width_px: int | None = None
    sidebar_trigger_y_start: float | None = None
    sidebar_trigger_y_end: float | None = None
    sidebar_effect: str | None = None
    sidebar_height_ratio: float | None = None
    sidebar_opacity: float | None = None
    sidebar_clock_enabled: bool | None = None
    sidebar_clock_format: str | None = None
    sidebar_playtime_enabled: bool | None = None
    sidebar_playtime_prefix: str | None = None
    sidebar_volume_section_enabled: bool | None = None
    screenshot_enabled: bool | None = None
    screenshot_save_dir: str | None = None
    screenshot_gamepad_trigger: bool | None = None
    screenshot_disable_gamebar: bool | None = None
    screenshot_capture_mode: str | None = None
    screenshot_gamepad_button_index: int | None = None
    screenshot_trigger_vk: int | None = None
    recording_enabled: bool | None = None
    obs_host: str | None = None
    obs_port: int | None = None
    obs_password: str | None = None
    obs_exe_path: str | None = None
    obs_auto_launch: bool | None = None
    obs_launch_hidden: bool | None = None
    obs_watch_output_dir: bool | None = None
    obs_recording_output_dir: str | None = None
    recording_hold_threshold_ms: int | None = None

    class Config:
        extra = "forbid"


class HoYoLabCredentialsPatch(BaseModel):
    ltuid: int
    ltoken_v2: str
    ltmid_v2: str
    starrail_uid: int | None = None
    zzz_uid: int | None = None

    class Config:
        extra = "forbid"


class HoYoLabExtractRequest(BaseModel):
    browser: str

    class Config:
        extra = "forbid"


class HoYoLabStaminaRequest(BaseModel):
    game_id: str
    process_id: str | None = None
    persist_to_process: bool = False

    class Config:
        extra = "forbid"


class ObsConfigPayload(BaseModel):
    port: int
    password: str
    output_dir: str
    exe_path: str


class ScreenshotKeyCaptureRequest(BaseModel):
    timeout_sec: float = 10.0

    class Config:
        extra = "forbid"


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_HOYOLAB_GAME_IDS = {"honkai_starrail", "zenless_zone_zero"}
_HOYOLAB_BROWSERS = {"chrome", "edge", "firefox"}


def _validate_time_or_none(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    if not _TIME_RE.match(value):
        raise HTTPException(status_code=422, detail=f"{field}은 HH:MM 형식이어야 합니다.")
    return value


def _validate_url(value: str, field: str = "url") -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail=f"{field}은 http(s) URL이어야 합니다.")
    return value


def _settings_patch_fields() -> set[str]:
    return set(SettingsPatch.model_fields if hasattr(SettingsPatch, "model_fields") else SettingsPatch.__fields__)


def _validate_number_range(data: dict[str, Any], field: str, minimum: float, maximum: float) -> None:
    if field not in data or data[field] is None:
        return
    value = data[field]
    if not isinstance(value, (int, float)) or value < minimum or value > maximum:
        raise HTTPException(status_code=422, detail=f"{field} 값은 {minimum}~{maximum} 범위여야 합니다.")


def _normalize_settings_patch(data: dict[str, Any]) -> dict[str, Any]:
    for field in ("sleep_start_time_str", "sleep_end_time_str"):
        if field in data:
            data[field] = _validate_time_or_none(data[field], field) or "00:00"
    if "theme" in data and data["theme"] not in {"system", "light", "dark"}:
        raise HTTPException(status_code=422, detail="theme 값이 올바르지 않습니다.")
    if "screenshot_capture_mode" in data and data["screenshot_capture_mode"] not in {"fullscreen", "game_window", "window"}:
        raise HTTPException(status_code=422, detail="screenshot_capture_mode 값이 올바르지 않습니다.")

    _validate_number_range(data, "sleep_correction_advance_notify_hours", 0, 5)
    _validate_number_range(data, "cycle_deadline_advance_notify_hours", 0, 12)
    _validate_number_range(data, "stamina_notify_threshold", 1, 100)
    _validate_number_range(data, "sidebar_auto_hide_ms", 0, 60000)
    _validate_number_range(data, "sidebar_edge_width_px", 1, 50)
    _validate_number_range(data, "sidebar_trigger_y_start", 0, 1)
    _validate_number_range(data, "sidebar_trigger_y_end", 0, 1)
    _validate_number_range(data, "sidebar_height_ratio", 0.3, 1.0)
    _validate_number_range(data, "sidebar_opacity", 0.1, 1.0)
    _validate_number_range(data, "screenshot_gamepad_button_index", -1, 32)
    _validate_number_range(data, "screenshot_trigger_vk", 0, 255)
    _validate_number_range(data, "obs_port", 1, 65535)
    _validate_number_range(data, "recording_hold_threshold_ms", 100, 2000)
    y_start = data.get("sidebar_trigger_y_start")
    y_end = data.get("sidebar_trigger_y_end")
    if y_start is not None and y_end is not None and y_start > y_end:
        raise HTTPException(status_code=422, detail="sidebar_trigger_y_start는 sidebar_trigger_y_end보다 클 수 없습니다.")
    for field in ("sidebar_effect", "sidebar_clock_format", "sidebar_playtime_prefix", "screenshot_save_dir", "obs_host", "obs_password", "obs_exe_path", "obs_recording_output_dir"):
        if field in data and data[field] is None:
            data[field] = ""
    if "obs_host" in data and not str(data["obs_host"]).strip():
        data["obs_host"] = "localhost"
    return data


def _normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return path


def _running_process_ids(processes: Iterable[models.Process]) -> set[str]:
    """Return process ids that are actually running on the OS.

    The legacy PyQt GUI marks [실행중] from ProcessMonitor's live process cache,
    not from stale open DB sessions.  The preview GUI has no long-running
    ProcessMonitor yet, so it performs a read-only psutil snapshot instead.
    """
    wanted = {
        normalized: process.id
        for process in processes
        if (normalized := _normalize_path(process.monitoring_path))
    }
    if not wanted:
        return set()

    try:
        import psutil
    except Exception:
        return set()

    running: set[str] = set()
    try:
        iterator = psutil.process_iter(["exe"])
        for proc in iterator:
            try:
                exe = _normalize_path(proc.info.get("exe"))
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, FileNotFoundError):
                continue
            except Exception:
                continue
            if exe in wanted:
                running.add(wanted[exe])
    except Exception:
        return set()
    return running


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
        "stamina_current": process.stamina_current,
        "stamina_max": process.stamina_max,
        "stamina_updated_at": process.stamina_updated_at,
        "status": status,
        "progress": _progress(process, now_dt),
        "icon_url": f"/api/dashboard/icons/{process.id}?size=128",
    }


def _shortcut_state(shortcut: models.WebShortcut, now_dt: dt.datetime) -> str:
    refresh_time = _parse_time(shortcut.refresh_time_str)
    if not refresh_time:
        return "default"
    reset_today = now_dt.replace(hour=refresh_time.hour, minute=refresh_time.minute, second=0, microsecond=0)
    if now_dt < reset_today:
        reset_today -= dt.timedelta(days=1)
    last_reset = (
        dt.datetime.fromtimestamp(float(shortcut.last_reset_timestamp))
        if shortcut.last_reset_timestamp
        else None
    )
    return "done" if last_reset and last_reset >= reset_today else "due"


def _shortcut_to_gui(shortcut: models.WebShortcut, now_dt: dt.datetime | None = None) -> dict[str, Any]:
    now_dt = now_dt or dt.datetime.now()
    return {
        "id": shortcut.id,
        "name": shortcut.name,
        "url": shortcut.url,
        "refresh_time_str": shortcut.refresh_time_str,
        "last_reset_timestamp": shortcut.last_reset_timestamp,
        "state": _shortcut_state(shortcut, now_dt),
    }


def _settings_to_gui(settings: models.GlobalSettings) -> dict[str, Any]:
    fields = schemas.GlobalSettingsSchema.model_fields if hasattr(schemas.GlobalSettingsSchema, "model_fields") else schemas.GlobalSettingsSchema.__fields__
    return {field: getattr(settings, field) for field in fields}


def _hoyolab_status_payload() -> dict[str, Any]:
    from src.services.hoyolab import HoYoLabService
    from src.utils.browser_cookie_extractor import DPAPI_AVAILABLE, CRYPTO_AVAILABLE
    from src.utils.hoyolab_config import DPAPI_AVAILABLE as CREDENTIAL_DPAPI_AVAILABLE
    from src.utils.hoyolab_config import HoYoLabConfig

    config = HoYoLabConfig()
    service = HoYoLabService(config=config)
    credentials_file_exists = config.credentials_path.exists()
    configured = service.is_configured()
    return {
        "configured": configured,
        "credentials_file_exists": credentials_file_exists,
        "credentials_loadable": configured,
        "credentials_path": str(config.credentials_path),
        "service_available": service.is_available(),
        "dpapi_available": bool(CREDENTIAL_DPAPI_AVAILABLE),
        "extractor_available": bool(DPAPI_AVAILABLE and CRYPTO_AVAILABLE),
        "supported_browsers": ["chrome", "edge", "firefox"],
        "supported_games": [
            {"id": game_id, "name": meta["name"], "stamina_name": meta["stamina_name"]}
            for game_id, meta in HoYoLabService.GAME_TYPES.items()
        ],
    }


def _stamina_to_payload(info: Any) -> dict[str, Any]:
    return {
        "game_id": info.game_id,
        "game_name": info.game_name,
        "current": info.current,
        "max": info.max,
        "recover_time": info.recover_time,
        "full_time": info.full_time.isoformat() if info.full_time else None,
        "updated_at": info.updated_at.isoformat(),
        "updated_at_timestamp": info.updated_at.timestamp(),
    }


@router.get("/main-state")
def get_main_state(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return a DB-safe snapshot for the Tauri/React main window."""
    processes = crud.get_processes(db)
    shortcuts = crud.get_shortcuts(db, limit=500)
    settings = crud.get_settings(db)
    active_ids = _running_process_ids(processes)
    now_dt = dt.datetime.now()
    return {
        "generated_at": now_dt.isoformat(),
        "settings": _settings_to_gui(settings),
        "processes": [
            _process_to_gui_row(process, _visual_status(process, settings, now_dt, active_ids), now_dt)
            for process in sorted(processes, key=lambda p: (p.name or "").casefold())
        ],
        "web_shortcuts": [_shortcut_to_gui(shortcut, now_dt) for shortcut in shortcuts],
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


@router.post("/processes", status_code=201)
def create_process(process_data: schemas.ProcessCreateSchema, db: Session = Depends(get_db)) -> dict[str, Any]:
    _validate_time_or_none(process_data.server_reset_time_str, "server_reset_time_str")
    for mandatory in process_data.mandatory_times_str or []:
        _validate_time_or_none(mandatory, "mandatory_times_str")
    if process_data.preferred_launch_type not in {"shortcut", "direct", "launcher"}:
        raise HTTPException(status_code=422, detail="preferred_launch_type 값이 올바르지 않습니다.")
    process = crud.create_process(db, process_data)
    now_dt = dt.datetime.now()
    return _process_to_gui_row(process, _visual_status(process, crud.get_settings(db), now_dt, set()), now_dt)


@router.put("/processes/{process_id}")
def update_process(
    process_id: str,
    process_data: schemas.ProcessCreateSchema,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_time_or_none(process_data.server_reset_time_str, "server_reset_time_str")
    for mandatory in process_data.mandatory_times_str or []:
        _validate_time_or_none(mandatory, "mandatory_times_str")
    if process_data.preferred_launch_type not in {"shortcut", "direct", "launcher"}:
        raise HTTPException(status_code=422, detail="preferred_launch_type 값이 올바르지 않습니다.")
    process = crud.update_process(db, process_id, process_data)
    if process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    now_dt = dt.datetime.now()
    return _process_to_gui_row(process, _visual_status(process, crud.get_settings(db), now_dt, _running_process_ids([process])), now_dt)


@router.delete("/processes/{process_id}")
def delete_process(process_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    process = crud.delete_process(db, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return {"message": "프로세스가 삭제되었습니다."}


@router.post("/web-shortcuts", status_code=201)
def create_web_shortcut(shortcut_data: schemas.WebShortcutCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    _validate_url(shortcut_data.url)
    shortcut_data.refresh_time_str = _validate_time_or_none(shortcut_data.refresh_time_str, "refresh_time_str")
    shortcut = crud.create_shortcut(db, shortcut_data)
    return _shortcut_to_gui(shortcut)


@router.put("/web-shortcuts/{shortcut_id}")
def update_web_shortcut(
    shortcut_id: str,
    shortcut_data: schemas.WebShortcutCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_url(shortcut_data.url)
    shortcut_data.refresh_time_str = _validate_time_or_none(shortcut_data.refresh_time_str, "refresh_time_str")
    if not shortcut_data.refresh_time_str:
        shortcut_data.last_reset_timestamp = None
    shortcut = crud.update_shortcut(db, shortcut_id, shortcut_data)
    if shortcut is None:
        raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
    return _shortcut_to_gui(shortcut)


@router.delete("/web-shortcuts/{shortcut_id}")
def delete_web_shortcut(shortcut_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    shortcut = crud.delete_shortcut(db, shortcut_id)
    if shortcut is None:
        raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
    return {"message": "웹 바로 가기가 삭제되었습니다."}


@router.post("/web-shortcuts/{shortcut_id}/open")
def mark_web_shortcut_opened(shortcut_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    shortcut = crud.mark_shortcut_opened(db, shortcut_id, time.time(), actor="new_gui_web_shortcut_runtime")
    if shortcut is None:
        raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
    return _shortcut_to_gui(shortcut) | {"ok": True}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = crud.get_settings(db)
    return _settings_to_gui(settings)


@router.patch("/settings")
def patch_settings(settings_patch: SettingsPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = crud.get_settings(db)
    data = _normalize_settings_patch(_dump_model(settings_patch, exclude_unset=True))

    startup_changed = "run_on_startup" in data and bool(data["run_on_startup"]) != bool(settings.run_on_startup)
    settings = crud.patch_settings(
        db,
        data,
        actor="new_gui_settings",
        allowed_fields=_settings_patch_fields(),
    )

    startup_applied: bool | None = None
    if startup_changed:
        startup_applied = set_startup_shortcut(bool(settings.run_on_startup))

    body = _settings_to_gui(settings)
    body["startup_applied"] = startup_applied
    body["admin_restart_required"] = "run_as_admin" in data
    return body


@router.post("/settings/apply-privilege")
def apply_privilege_setting(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = crud.get_settings(db)
    want_admin = bool(settings.run_as_admin)
    currently_admin = bool(is_admin())

    if want_admin and not currently_admin:
        requested = bool(run_as_admin())
        action = "run_as_admin"
    elif not want_admin and currently_admin:
        requested = bool(restart_as_normal())
        action = "restart_as_normal"
    else:
        requested = True
        action = "none"

    return {
        "ok": requested,
        "action": action,
        "want_admin": want_admin,
        "currently_admin": currently_admin,
    }


@router.get("/hoyolab/status")
def get_hoyolab_status() -> dict[str, Any]:
    """Return HoYoLab credential/API capability state without exposing secrets."""
    return _hoyolab_status_payload()


@router.put("/hoyolab/credentials")
def save_hoyolab_credentials(credentials: HoYoLabCredentialsPatch) -> dict[str, Any]:
    if credentials.ltuid <= 0:
        raise HTTPException(status_code=422, detail="ltuid 값이 올바르지 않습니다.")
    if not credentials.ltoken_v2.strip() or not credentials.ltmid_v2.strip():
        raise HTTPException(status_code=422, detail="필수 HoYoLab 쿠키 값이 비어 있습니다.")

    from src.services.hoyolab import reset_hoyolab_service
    from src.utils.hoyolab_config import HoYoLabConfig

    config = HoYoLabConfig()
    ok = config.save_credentials(
        credentials.ltuid,
        credentials.ltoken_v2.strip(),
        credentials.ltmid_v2.strip(),
        starrail_uid=credentials.starrail_uid,
        zzz_uid=credentials.zzz_uid,
    )
    reset_hoyolab_service()
    if not ok:
        raise HTTPException(status_code=500, detail="HoYoLab 인증 정보 저장에 실패했습니다.")
    return _hoyolab_status_payload() | {"ok": True}


@router.delete("/hoyolab/credentials")
def clear_hoyolab_credentials() -> dict[str, Any]:
    from src.services.hoyolab import reset_hoyolab_service
    from src.utils.hoyolab_config import HoYoLabConfig

    ok = HoYoLabConfig().clear_credentials()
    reset_hoyolab_service()
    if not ok:
        raise HTTPException(status_code=500, detail="HoYoLab 인증 정보 삭제에 실패했습니다.")
    return _hoyolab_status_payload() | {"ok": True}


@router.post("/hoyolab/extract")
def extract_hoyolab_credentials(request: HoYoLabExtractRequest) -> dict[str, Any]:
    browser = request.browser.lower()
    if browser not in _HOYOLAB_BROWSERS:
        raise HTTPException(status_code=422, detail="지원하지 않는 브라우저입니다.")

    from src.services.hoyolab import reset_hoyolab_service
    from src.utils.browser_cookie_extractor import BrowserCookieExtractor
    from src.utils.hoyolab_config import HoYoLabConfig

    extractor = BrowserCookieExtractor()
    cookies = extractor.extract_from_browser(browser)
    if not cookies:
        raise HTTPException(status_code=404, detail=f"{browser}에서 HoYoLab 쿠키를 찾을 수 없습니다.")
    ok = HoYoLabConfig().save_credentials(
        int(cookies.get("ltuid") or cookies.get("ltuid_v2") or 0),
        str(cookies.get("ltoken_v2") or ""),
        str(cookies.get("ltmid_v2") or ""),
    )
    reset_hoyolab_service()
    if not ok:
        raise HTTPException(status_code=500, detail="추출한 HoYoLab 인증 정보 저장에 실패했습니다.")
    return _hoyolab_status_payload() | {"ok": True, "browser": browser}


@router.post("/hoyolab/stamina")
def get_hoyolab_stamina(request: HoYoLabStaminaRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if request.game_id not in _HOYOLAB_GAME_IDS:
        raise HTTPException(status_code=422, detail="지원하지 않는 HoYoLab 게임입니다.")

    from src.services.hoyolab import get_hoyolab_service

    service = get_hoyolab_service()
    if not service.is_available():
        raise HTTPException(status_code=503, detail="HoYoLab API 라이브러리(genshin.py)를 사용할 수 없습니다.")
    if not service.is_configured():
        raise HTTPException(status_code=400, detail="HoYoLab 인증 정보가 설정되어 있지 않습니다.")

    info = service.get_stamina(request.game_id)
    if info is None:
        raise HTTPException(status_code=502, detail="HoYoLab 스태미나 조회에 실패했습니다.")

    body = _stamina_to_payload(info)
    if request.persist_to_process:
        if not request.process_id:
            raise HTTPException(status_code=422, detail="persist_to_process에는 process_id가 필요합니다.")
        process = crud.get_process_by_id(db, request.process_id)
        if process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        updated = crud.update_process_stamina(
            db,
            process.id,
            stamina_current=info.current,
            stamina_max=info.max,
            stamina_updated_at=info.updated_at.timestamp(),
            actor="new_gui_hoyolab_runtime",
            operation_kind="process_stamina_refresh",
        )
        body["process"] = _process_to_gui_row(updated, _visual_status(updated, crud.get_settings(db), dt.datetime.now(), _running_process_ids([updated])), dt.datetime.now())
    return body


@router.get("/recording/obs-config")
def read_recording_obs_config() -> dict[str, Any]:
    from src.recording.obs_config_reader import read_obs_config

    cfg = read_obs_config()
    payload = ObsConfigPayload(
        port=int(cfg.get("port") or 4455),
        password=str(cfg.get("password") or ""),
        output_dir=str(cfg.get("output_dir") or ""),
        exe_path=str(cfg.get("exe_path") or ""),
    )
    return _dump_model(payload)


@router.get("/screenshot/vk/{vk}")
def get_screenshot_vk_name(vk: int) -> dict[str, Any]:
    from src.screenshot.key_capture import is_key_capture_supported, vk_to_display_name

    if vk < 0 or vk > 255:
        raise HTTPException(status_code=422, detail="VK 값은 0~255 범위여야 합니다.")
    return {
        "vk": vk,
        "hex": f"0x{vk:02X}",
        "display_name": vk_to_display_name(vk),
        "capture_supported": is_key_capture_supported(),
    }


@router.post("/screenshot/capture-key")
def capture_screenshot_trigger_key(request: ScreenshotKeyCaptureRequest) -> dict[str, Any]:
    import threading

    from src.screenshot.key_capture import capture_one_key, is_key_capture_supported, vk_to_display_name

    if not is_key_capture_supported():
        raise HTTPException(status_code=503, detail="이 환경에서는 키 캡처를 사용할 수 없습니다.")
    timeout_sec = max(1.0, min(float(request.timeout_sec), 30.0))
    event = threading.Event()
    captured: dict[str, int | None] = {"vk": None}

    def on_captured(vk: int) -> None:
        captured["vk"] = vk
        event.set()

    def on_timeout() -> None:
        event.set()

    capture_one_key(timeout_sec=timeout_sec, on_captured=on_captured, on_timeout=on_timeout)
    event.wait(timeout_sec + 1.0)
    vk = captured["vk"]
    if vk is None:
        raise HTTPException(status_code=408, detail="키 입력 시간이 초과되었거나 ESC로 취소되었습니다.")
    return {
        "vk": vk,
        "hex": f"0x{vk:02X}",
        "display_name": vk_to_display_name(vk),
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
