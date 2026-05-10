"""API facade for the next-generation main GUI.

The Tauri/React GUI talks to this router instead of opening the SQLite
database directly.  This preserves the existing AppData database path, backup
flow, WAL settings, and migration behavior owned by ``src.data.database``.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
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
    password: str = ""
    output_dir: str
    exe_path: str
    has_password: bool = False


class ScreenshotKeyCaptureRequest(BaseModel):
    timeout_sec: float = 10.0

    class Config:
        extra = "forbid"


class ClipboardFileRequest(BaseModel):
    path: str

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
    if "screenshot_capture_mode" in data and data["screenshot_capture_mode"] not in {"fullscreen", "game_window"}:
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
            payload = {
                "kind": "stamina",
                "percent": round(percent, 2),
                "label": f"{current}/{max_stamina}",
                "current": current,
                "max": max_stamina,
                "hoyolab_game_id": process.hoyolab_game_id,
            }
            if _resource_icon_path(process):
                payload["resource_icon_url"] = f"/api/gui/processes/{process.id}/resource-icon"
            return payload

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
        payload = {"kind": "time", "percent": round(percent, 2), "label": label}
        if _resource_icon_path(process):
            payload["resource_icon_url"] = f"/api/gui/processes/{process.id}/resource-icon"
        return payload
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


def _server_day_bounds(now_dt: dt.datetime, reset_time: dt.time) -> tuple[dt.datetime, dt.datetime]:
    reset_today = now_dt.replace(hour=reset_time.hour, minute=reset_time.minute, second=0, microsecond=0)
    if now_dt.time() < reset_time:
        start = reset_today - dt.timedelta(days=1)
        end = reset_today - dt.timedelta(microseconds=1)
    else:
        start = reset_today
        end = reset_today + dt.timedelta(days=1) - dt.timedelta(microseconds=1)
    return start, end


def _scheduler_event_label(kind: str) -> str:
    return {
        "mandatory_time": "고정 접속",
        "cycle_deadline": "주기 마감",
        "sleep_correction": "수면 보정",
        "daily_reset": "일일 리셋",
        "stamina": "스태미나",
        "status_incomplete": "미완료",
    }.get(kind, "알림")


def _scheduler_severity_label(severity: str) -> str:
    return {
        "due": "지금 확인 필요",
        "soon": "곧 확인 필요",
        "info": "참고",
    }.get(severity, severity)


def _scheduler_due_label(due_at: dt.datetime, now_dt: dt.datetime) -> str:
    delta = due_at - now_dt
    seconds = int(delta.total_seconds())
    clock = due_at.strftime("%H:%M")
    if abs(seconds) < 60:
        return f"지금 · {clock}"
    if seconds > 0:
        minutes = max(1, seconds // 60)
        if minutes < 60:
            return f"{minutes}분 후 · {clock}"
        hours = minutes // 60
        rest = minutes % 60
        return f"{hours}시간 {rest}분 후 · {clock}" if rest else f"{hours}시간 후 · {clock}"
    minutes = max(1, abs(seconds) // 60)
    if minutes < 60:
        return f"{minutes}분 지남 · {clock}"
    hours = minutes // 60
    rest = minutes % 60
    return f"{hours}시간 {rest}분 지남 · {clock}" if rest else f"{hours}시간 지남 · {clock}"


def _scheduler_event(
    *,
    kind: str,
    process: models.Process,
    due_at: dt.datetime,
    severity: str,
    message: str,
    now_dt: dt.datetime,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "kind_label": _scheduler_event_label(kind),
        "process_id": process.id,
        "process_name": process.name,
        "due_at": due_at.isoformat(),
        "due_label": _scheduler_due_label(due_at, now_dt),
        "severity": severity,
        "severity_label": _scheduler_severity_label(severity),
        "message": message,
    }


def _scheduler_preview_for_process(
    process: models.Process,
    settings: models.GlobalSettings,
    now_dt: dt.datetime,
    status: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    last_played_dt = dt.datetime.fromtimestamp(float(process.last_played_timestamp)) if process.last_played_timestamp else None

    if settings.notify_on_mandatory_time and process.is_mandatory_time_enabled and process.mandatory_times_str:
        for mandatory in process.mandatory_times_str:
            mandatory_time = _parse_time(mandatory)
            if not mandatory_time:
                continue
            due_at = now_dt.replace(hour=mandatory_time.hour, minute=mandatory_time.minute, second=0, microsecond=0)
            if now_dt >= due_at and (last_played_dt is None or last_played_dt < due_at):
                events.append(_scheduler_event(
                    kind="mandatory_time",
                    process=process,
                    due_at=due_at,
                    severity="due",
                    message=f"{process.name}의 고정 접속 시각({mandatory})이 지났습니다.",
                    now_dt=now_dt,
                ))

    if process.user_cycle_hours and last_played_dt:
        deadline = last_played_dt + dt.timedelta(hours=float(process.user_cycle_hours))
        notify_at = deadline - dt.timedelta(hours=float(settings.cycle_deadline_advance_notify_hours or 0))
        if settings.notify_on_cycle_deadline and notify_at <= now_dt < deadline:
            events.append(_scheduler_event(
                kind="cycle_deadline",
                process=process,
                due_at=deadline,
                severity="soon",
                message=f"{process.name}의 사용자 주기 마감이 다가옵니다.",
                now_dt=now_dt,
            ))
        sleep_period = _next_sleep_period(now_dt, settings)
        if settings.notify_on_sleep_correction and sleep_period:
            sleep_start, sleep_end = sleep_period
            trigger = sleep_start - dt.timedelta(hours=float(settings.sleep_correction_advance_notify_hours or 0))
            if sleep_start <= deadline < sleep_end and trigger <= now_dt < sleep_start:
                events.append(_scheduler_event(
                    kind="sleep_correction",
                    process=process,
                    due_at=deadline,
                    severity="soon",
                    message=f"{process.name}의 마감이 수면 시간과 겹쳐 미리 접속하는 것이 좋습니다.",
                    now_dt=now_dt,
                ))

    reset_time = _parse_time(process.server_reset_time_str)
    if settings.notify_on_daily_reset and reset_time:
        start, end = _server_day_bounds(now_dt, reset_time)
        played_today = bool(last_played_dt and start <= last_played_dt <= end)
        reminder_at = end - dt.timedelta(hours=1)
        if not played_today and reminder_at <= now_dt < end:
            events.append(_scheduler_event(
                kind="daily_reset",
                process=process,
                due_at=end,
                severity="soon",
                message=f"{process.name}의 서버 하루 마감이 다가오지만 오늘 플레이 기록이 없습니다.",
                now_dt=now_dt,
            ))

    if settings.stamina_notify_enabled and process.stamina_tracking_enabled:
        stamina = _predicted_stamina(process)
        if stamina:
            current, maximum = stamina
            threshold = int(settings.stamina_notify_threshold or 0)
            if maximum > 0 and current >= maximum - threshold:
                events.append(_scheduler_event(
                    kind="stamina",
                    process=process,
                    due_at=now_dt,
                    severity="soon" if current < maximum else "due",
                    message=f"{process.name}의 스태미나가 곧 가득 찹니다. ({current}/{maximum})",
                    now_dt=now_dt,
                ))

    if status == "미완료" and not events:
        events.append(_scheduler_event(
            kind="status_incomplete",
            process=process,
            due_at=now_dt,
            severity="due",
            message=f"{process.name}은 현재 미완료 상태입니다.",
            now_dt=now_dt,
        ))
    return events


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
        "default_volume": process.default_volume,
        "default_muted": bool(process.default_muted),
        "status": status,
        "progress": _progress(process, now_dt),
        "icon_url": f"/api/dashboard/icons/{process.id}?size=128",
    }


def _resource_icon_path(process: models.Process) -> str | None:
    if not process.user_preset_id:
        return None
    preset = GamePresetManager().get_preset_by_id(process.user_preset_id)
    if not preset:
        return None
    icon_path = preset.get("icon_path")
    icon_type = preset.get("icon_type")
    if not icon_path:
        return None
    try:
        from src.utils.icon_helper import resolve_preset_icon_path

        return resolve_preset_icon_path(icon_path, icon_type)
    except Exception:
        return None


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


def _notification_toggles(settings: models.GlobalSettings) -> list[dict[str, Any]]:
    toggles = [
        ("notify_on_mandatory_time", "고정 접속", settings.notify_on_mandatory_time),
        ("notify_on_cycle_deadline", "주기 마감", settings.notify_on_cycle_deadline),
        ("notify_on_sleep_correction", "수면 보정", settings.notify_on_sleep_correction),
        ("notify_on_daily_reset", "일일 리셋", settings.notify_on_daily_reset),
        ("stamina_notify_enabled", "스태미나", settings.stamina_notify_enabled),
    ]
    return [{"key": key, "label": label, "enabled": bool(enabled)} for key, label, enabled in toggles]


@router.get("/health")
def get_gui_health() -> dict[str, Any]:
    """Lightweight readiness endpoint for the packaged Tauri preview shell."""
    return {
        "ok": True,
        "app": "HomeworkHelper",
        "pid": os.getpid(),
        "schema_ready": True,
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


@router.get("/scheduler/preview")
def get_scheduler_preview(now: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Preview scheduler/notifier decisions using the same DB-backed settings."""
    settings = crud.get_settings(db)
    processes = crud.get_processes(db)
    try:
        now_dt = dt.datetime.fromisoformat(now) if now else dt.datetime.now()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="now는 ISO datetime 형식이어야 합니다.") from exc
    active_ids = _running_process_ids(processes)
    rows = []
    events: list[dict[str, Any]] = []
    counts = {"실행중": 0, "미완료": 0, "완료됨": 0}
    for process in sorted(processes, key=lambda item: (item.name or "").casefold()):
        status = _visual_status(process, settings, now_dt, active_ids)
        counts[status] = counts.get(status, 0) + 1
        process_events = _scheduler_preview_for_process(process, settings, now_dt, status)
        events.extend(process_events)
        rows.append({
            "process_id": process.id,
            "process_name": process.name,
            "status": status,
            "event_count": len(process_events),
            "events": process_events,
        })
    notification_toggles = _notification_toggles(settings)
    enabled_notifications = [item["label"] for item in notification_toggles if item["enabled"]]
    disabled_notifications = [item["label"] for item in notification_toggles if not item["enabled"]]
    return {
        "generated_at": now_dt.isoformat(),
        "settings": {
            "notify_on_mandatory_time": settings.notify_on_mandatory_time,
            "notify_on_cycle_deadline": settings.notify_on_cycle_deadline,
            "notify_on_sleep_correction": settings.notify_on_sleep_correction,
            "notify_on_daily_reset": settings.notify_on_daily_reset,
            "stamina_notify_enabled": settings.stamina_notify_enabled,
            "stamina_notify_threshold": settings.stamina_notify_threshold,
        },
        "status_counts": counts,
        "events": events,
        "processes": rows,
        "notification_toggles": notification_toggles,
        "enabled_notifications": enabled_notifications,
        "disabled_notifications": disabled_notifications,
        "coverage_summary": f"켜짐 {len(enabled_notifications)}개 · 꺼짐 {len(disabled_notifications)}개",
        "user_summary": f"미완료 {counts.get('미완료', 0)}개, 예정/필요 알림 {len(events)}건",
    }


@router.get("/processes/{process_id}/resource-icon")
def get_process_resource_icon(process_id: str, db: Session = Depends(get_db)):
    process = crud.get_process_by_id(db, process_id)
    if not process:
        raise HTTPException(status_code=404, detail="게임을 찾을 수 없습니다.")
    path = _resource_icon_path(process)
    if not path or not os.path.exists(path):
        return Response(status_code=204)
    return FileResponse(path, media_type="image/png")


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




def _restart_packaged_preview_shell(want_admin: bool) -> bool | None:
    if os.name != "nt" or "--run-server" not in sys.argv:
        return None
    from pathlib import Path

    gui_exe = Path(sys.executable).with_name("homework_helper_gui.exe")
    if not gui_exe.exists():
        return None
    try:
        import ctypes

        operation = "runas" if want_admin else "open"
        result = ctypes.windll.shell32.ShellExecuteW(None, operation, str(gui_exe), None, str(gui_exe.parent), 1)
        if int(result) <= 32:
            return False
        threading.Timer(0.8, lambda: os._exit(0)).start()
        return True
    except Exception:
        return False

@router.post("/settings/apply-privilege")
def apply_privilege_setting(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = crud.get_settings(db)
    want_admin = bool(settings.run_as_admin)
    currently_admin = bool(is_admin())

    preview_restart = _restart_packaged_preview_shell(want_admin)
    if preview_restart is not None:
        requested = bool(preview_restart)
        action = "restart_new_gui_preview"
    elif want_admin and not currently_admin:
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
        if process.hoyolab_game_id != request.game_id:
            raise HTTPException(status_code=422, detail="선택한 게임의 HoYoLab 설정과 조회 대상이 일치하지 않습니다.")
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
        password="",
        output_dir=str(cfg.get("output_dir") or ""),
        exe_path=str(cfg.get("exe_path") or ""),
        has_password=bool(cfg.get("password")),
    )
    return _dump_model(payload)


def _recording_gallery_dir(settings: models.GlobalSettings) -> Path | None:
    configured = getattr(settings, "obs_recording_output_dir", "") or ""
    if configured:
        return Path(configured).expanduser()
    try:
        from src.recording.obs_config_reader import read_obs_config

        detected = str(read_obs_config().get("output_dir") or "")
        if detected:
            return Path(detected).expanduser()
    except Exception:
        pass
    return None


def _validate_gallery_file(filename: str, gallery_dir: Path | None, suffixes: set[str], missing_detail: str) -> Path:
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name or gallery_dir is None:
        raise HTTPException(status_code=404, detail=missing_detail)
    try:
        root = gallery_dir.resolve(strict=True)
        path = (gallery_dir / safe_name).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in suffixes:
            raise HTTPException(status_code=404, detail=missing_detail)
        return path
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=missing_detail) from exc


@router.get("/recording/gallery")
def list_recording_gallery(limit: int = 5, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = crud.get_settings(db)
    gallery_dir = _recording_gallery_dir(settings)
    limit = max(1, min(int(limit or 5), 24))
    suffixes = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
    files: list[Any] = []
    if gallery_dir and gallery_dir.exists() and gallery_dir.is_dir():
        files = sorted(
            [path for path in gallery_dir.iterdir() if path.is_file() and path.suffix.lower() in suffixes],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    items = []
    for path in files[:limit]:
        stat = path.stat()
        items.append({
            "name": path.name,
            "path": str(path),
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
            "file_url": f"/api/gui/recording/gallery/{path.name}",
        })
    return {
        "enabled": bool(getattr(settings, "recording_enabled", False)),
        "directory": str(gallery_dir) if gallery_dir else "",
        "exists": bool(gallery_dir and gallery_dir.exists() and gallery_dir.is_dir()),
        "total": len(files),
        "items": items,
    }


@router.get("/recording/gallery/{filename}")
def get_recording_gallery_file(filename: str, db: Session = Depends(get_db)):
    settings = crud.get_settings(db)
    gallery_dir = _recording_gallery_dir(settings)
    suffixes = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
    path = _validate_gallery_file(filename, gallery_dir, suffixes, "녹화 파일을 찾을 수 없습니다.")
    media_type = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.post("/clipboard/file-payload")
def describe_clipboard_file_payload(request: ClipboardFileRequest) -> dict[str, Any]:
    from pathlib import Path

    from src.utils.clipboard import describe_file_clipboard_payload

    path = Path(request.path).expanduser()
    return dict(describe_file_clipboard_payload(path))


@router.post("/clipboard/copy-file")
def copy_clipboard_file(request: ClipboardFileRequest) -> dict[str, Any]:
    from pathlib import Path

    from src.utils.clipboard import copy_file_to_clipboard, describe_file_clipboard_payload, is_native_file_clipboard_supported

    path = Path(request.path).expanduser()
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="복사할 파일을 찾을 수 없습니다.")
    if not is_native_file_clipboard_supported():
        raise HTTPException(status_code=503, detail="이 환경에서는 파일 클립보드 복사를 사용할 수 없습니다.")
    copy_file_to_clipboard(path)
    payload = dict(describe_file_clipboard_payload(path))
    payload["copied"] = True
    return payload


def _screenshot_gallery_dir(settings: models.GlobalSettings):
    from pathlib import Path

    configured = getattr(settings, "screenshot_save_dir", "") or ""
    if configured:
        return Path(configured).expanduser()
    from src.screenshot.capture import _DEFAULT_SAVE_DIR

    return Path(_DEFAULT_SAVE_DIR).expanduser()


@router.get("/screenshot/gallery")
def list_screenshot_gallery(limit: int = 6, db: Session = Depends(get_db)) -> dict[str, Any]:
    from src.utils.clipboard import is_native_file_clipboard_supported

    settings = crud.get_settings(db)
    gallery_dir = _screenshot_gallery_dir(settings)
    limit = max(1, min(int(limit or 6), 24))
    suffixes = {".png", ".jpg", ".jpeg", ".bmp"}
    files: list[Any] = []
    if gallery_dir.exists() and gallery_dir.is_dir():
        files = sorted(
            [path for path in gallery_dir.iterdir() if path.is_file() and path.suffix.lower() in suffixes],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    items = []
    for path in files[:limit]:
        stat = path.stat()
        items.append({
            "name": path.name,
            "path": str(path),
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
            "image_url": f"/api/gui/screenshot/gallery/{path.name}",
        })
    return {
        "enabled": bool(getattr(settings, "screenshot_enabled", True)),
        "directory": str(gallery_dir),
        "exists": gallery_dir.exists() and gallery_dir.is_dir(),
        "total": len(files),
        "items": items,
        "native_copy_supported": is_native_file_clipboard_supported(),
    }


@router.get("/screenshot/gallery/{filename}")
def get_screenshot_gallery_file(filename: str, db: Session = Depends(get_db)):
    settings = crud.get_settings(db)
    gallery_dir = _screenshot_gallery_dir(settings)
    path = _validate_gallery_file(filename, gallery_dir, {".png", ".jpg", ".jpeg", ".bmp"}, "스크린샷 파일을 찾을 수 없습니다.")
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    if path.suffix.lower() == ".bmp":
        media_type = "image/bmp"
    return FileResponse(path, media_type=media_type)


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
    return _build_launch_plan(process)["launch_target"]


def _launch_type_label(launch_type: str) -> str:
    return {
        "direct": "프로세스 직접 실행",
        "shortcut": "바로가기 실행",
        "launcher": "런처 우선 실행",
    }.get(launch_type, "기본 실행")


def _build_launch_plan(process: models.Process, settings: models.GlobalSettings | None = None) -> dict[str, Any]:
    launch_type = process.preferred_launch_type or "shortcut"
    fallback_chain: list[str] = []
    launcher_path = None

    if launch_type == "direct":
        fallback_chain = ["monitoring_path", "launch_path"]
        target = process.monitoring_path or process.launch_path
    elif launch_type == "shortcut":
        fallback_chain = ["launch_path", "monitoring_path"]
        target = process.launch_path or process.monitoring_path
    elif launch_type == "launcher":
        fallback_chain = ["preset_launcher_pattern", "launch_path", "monitoring_path"]
        if process.user_preset_id:
            preset = GamePresetManager().get_preset_by_id(process.user_preset_id)
            if preset and preset.get("launcher_patterns"):
                launch_dir = os.path.dirname(process.launch_path or process.monitoring_path or "")
                for pattern in preset["launcher_patterns"]:
                    candidate = os.path.join(launch_dir, pattern)
                    if os.path.exists(candidate):
                        launcher_path = candidate
                        break
        target = launcher_path or process.launch_path or process.monitoring_path
    else:
        fallback_chain = ["launch_path", "monitoring_path"]
        target = process.launch_path or process.monitoring_path

    return {
        "process_id": process.id,
        "process_name": process.name,
        "preferred_launch_type": launch_type,
        "launch_type_label": _launch_type_label(launch_type),
        "launch_target": target,
        "launcher_path": launcher_path,
        "fallback_chain": fallback_chain,
        "run_as_admin": bool(getattr(settings, "run_as_admin", False)) if settings is not None else None,
        "hide_on_game": bool(getattr(settings, "hide_on_game", False)) if settings is not None else None,
        "user_message": (
            f"{_launch_type_label(launch_type)}으로 '{process.name}'을(를) 실행합니다."
            if target else f"'{process.name}'의 실행 경로가 비어 있어 실행할 수 없습니다."
        ),
    }


@router.get("/processes/{process_id}/launch-plan")
def get_launch_plan(process_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the launch target chosen for the current preference without starting it."""
    process = crud.get_process_by_id(db, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    return _build_launch_plan(process, crud.get_settings(db))


@router.post("/processes/{process_id}/launch")
def launch_process(process_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Launch a configured process through the existing launcher code path."""
    process = crud.get_process_by_id(db, process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
    settings = crud.get_settings(db)
    plan = _build_launch_plan(process, settings)
    target = plan["launch_target"]
    if not target:
        raise HTTPException(status_code=400, detail="실행 경로가 없습니다.")
    success = Launcher(run_as_admin=bool(settings.run_as_admin)).launch_process(target)
    if not success:
        raise HTTPException(status_code=500, detail=f"{plan['launch_type_label']} 실패: {target}")
    return {"ok": True, **plan}
