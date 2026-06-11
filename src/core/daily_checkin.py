"""Daily check-in domain helpers and API-first provider runner.

The host app owns the schedule and persistence, while the actual provider calls
reuse the existing HoYoLab / BlablaLink service modules.  This module is kept
Qt-free so both the FastAPI process and tests can share the same behavior.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Iterable

from src.data.data_models import ManagedProcess
from src.utils.resource_tracking import is_nikke_outpost_resource

logger = logging.getLogger(__name__)

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - zoneinfo is available on supported runtimes
    ZoneInfo = None  # type: ignore[assignment]


PROVIDER_HOYOLAB = "hoyolab"
PROVIDER_NIKKE_BLABLALINK = "nikke_blablalink"

GAME_HONKAI_STARRAIL = "honkai_starrail"
GAME_ZENLESS_ZONE_ZERO = "zenless_zone_zero"
GAME_NIKKE = "nikke"

SUCCESS_STATUSES = {"success", "already_done"}
TRANSIENT_RETRY_STATUSES = {"network_error"}
USER_ACTION_REQUIRED_STATUSES = {
    "auth_required",
    "challenge_required",
    "game_login_required",
    "role_not_found",
    "route_error",
    "unavailable",
    "unsupported",
}
FAILURE_STATUSES = TRANSIENT_RETRY_STATUSES | USER_ACTION_REQUIRED_STATUSES

TRANSIENT_RETRY_AFTER_SECONDS = 30 * 60
PERIODIC_CHECK_INTERVAL_SECONDS = 5 * 60


def _kst_tz() -> dt.tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Asia/Seoul")
        except Exception:
            pass
    return dt.timezone(dt.timedelta(hours=9), name="KST")


KST = _kst_tz()


@dataclass(frozen=True)
class DailyCheckInDescriptor:
    game_id: str
    game_name: str
    provider: str
    provider_label: str
    reset_hour: int
    reset_minute: int = 0


@dataclass(frozen=True)
class DailyCheckInAttemptResult:
    provider: str
    game_id: str
    game_name: str
    status: str
    attempted_at: float
    message: str = ""
    post_called: bool = False
    raw_debug: dict[str, Any] | None = None


DAILY_CHECKIN_DESCRIPTORS: dict[str, DailyCheckInDescriptor] = {
    GAME_HONKAI_STARRAIL: DailyCheckInDescriptor(
        game_id=GAME_HONKAI_STARRAIL,
        game_name="붕괴: 스타레일",
        provider=PROVIDER_HOYOLAB,
        provider_label="HoYoLab",
        reset_hour=1,
    ),
    GAME_ZENLESS_ZONE_ZERO: DailyCheckInDescriptor(
        game_id=GAME_ZENLESS_ZONE_ZERO,
        game_name="젠레스 존 제로",
        provider=PROVIDER_HOYOLAB,
        provider_label="HoYoLab",
        reset_hour=1,
    ),
    GAME_NIKKE: DailyCheckInDescriptor(
        game_id=GAME_NIKKE,
        game_name="승리의 여신: 니케",
        provider=PROVIDER_NIKKE_BLABLALINK,
        provider_label="BlablaLink",
        reset_hour=9,
    ),
}


def descriptor_for_game(game_id: str | None) -> DailyCheckInDescriptor | None:
    return DAILY_CHECKIN_DESCRIPTORS.get(str(game_id or ""))


def descriptor_for_process(process: Any) -> DailyCheckInDescriptor | None:
    """Return the supported check-in target represented by a registered process."""
    preset_id = getattr(process, "user_preset_id", None)
    if preset_id in DAILY_CHECKIN_DESCRIPTORS:
        return DAILY_CHECKIN_DESCRIPTORS[preset_id]

    hoyolab_game_id = getattr(process, "hoyolab_game_id", None)
    if hoyolab_game_id in {GAME_HONKAI_STARRAIL, GAME_ZENLESS_ZONE_ZERO}:
        return DAILY_CHECKIN_DESCRIPTORS[hoyolab_game_id]

    if is_nikke_outpost_resource(
        getattr(process, "resource_provider", None),
        getattr(process, "resource_key", None),
    ):
        return DAILY_CHECKIN_DESCRIPTORS[GAME_NIKKE]

    return None


def iter_registered_daily_checkin_processes(processes: Iterable[Any]) -> list[tuple[Any, DailyCheckInDescriptor]]:
    targets: list[tuple[Any, DailyCheckInDescriptor]] = []
    for process in processes:
        descriptor = descriptor_for_process(process)
        if descriptor is not None:
            targets.append((process, descriptor))
    return targets


def normalise_process(process: Any) -> ManagedProcess:
    if isinstance(process, ManagedProcess):
        return process
    if hasattr(process, "__table__"):
        return ManagedProcess.from_dict(
            {column.name: getattr(process, column.name) for column in process.__table__.columns}
        )
    if isinstance(process, dict):
        return ManagedProcess.from_dict(dict(process))
    return ManagedProcess.from_dict(dict(getattr(process, "__dict__", {})))


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def checkin_period_for_descriptor(
    descriptor: DailyCheckInDescriptor,
    at: dt.datetime | float | None = None,
) -> tuple[dt.datetime, dt.datetime]:
    """Return the current KST reset window as timezone-aware datetimes."""
    if at is None:
        current = now_kst()
    elif isinstance(at, (int, float)):
        current = dt.datetime.fromtimestamp(float(at), KST)
    elif at.tzinfo is None:
        current = at.replace(tzinfo=KST)
    else:
        current = at.astimezone(KST)

    reset_today = current.replace(
        hour=descriptor.reset_hour,
        minute=descriptor.reset_minute,
        second=0,
        microsecond=0,
    )
    if current < reset_today:
        start = reset_today - dt.timedelta(days=1)
    else:
        start = reset_today
    return start, start + dt.timedelta(days=1)


def checkin_period_timestamps(
    descriptor: DailyCheckInDescriptor,
    at: dt.datetime | float | None = None,
) -> tuple[float, float]:
    start, end = checkin_period_for_descriptor(descriptor, at)
    return start.timestamp(), end.timestamp()


def next_reset_timestamp(descriptor: DailyCheckInDescriptor, at: dt.datetime | float | None = None) -> float:
    return checkin_period_timestamps(descriptor, at)[1]


def is_failure_status(status: str | None) -> bool:
    return bool(status and status not in SUCCESS_STATUSES)


def _log_status(log: Any) -> str:
    return str(getattr(log, "status", "") or (log.get("status") if isinstance(log, dict) else ""))


def _log_attempted_at(log: Any) -> float:
    value = getattr(log, "attempted_at", None)
    if value is None and isinstance(log, dict):
        value = log.get("attempted_at")
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def should_attempt_daily_checkin(
    current_period_logs: Iterable[Any],
    *,
    now_ts: float | None = None,
    retry_after_seconds: int = TRANSIENT_RETRY_AFTER_SECONDS,
) -> bool:
    """Apply the v1 conservative due policy to logs from the current reset period."""
    logs = sorted(list(current_period_logs), key=_log_attempted_at, reverse=True)
    if not logs:
        return True

    if any(_log_status(log) in SUCCESS_STATUSES for log in logs):
        return False

    latest = logs[0]
    latest_status = _log_status(latest)
    if latest_status in TRANSIENT_RETRY_STATUSES:
        now_value = float(now_ts if now_ts is not None else time.time())
        return now_value - _log_attempted_at(latest) >= retry_after_seconds

    if latest_status in USER_ACTION_REQUIRED_STATUSES:
        return False

    # Unknown non-success statuses are treated as transient but still throttled.
    now_value = float(now_ts if now_ts is not None else time.time())
    return now_value - _log_attempted_at(latest) >= retry_after_seconds


def sanitize_raw_debug(value: Any) -> Any:
    """Remove obvious secret-bearing keys before persisting provider debug data."""
    secret_markers = ("cookie", "token", "authorization", "ltoken", "session")
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in secret_markers):
                sanitized[key_text] = "<redacted>"
            else:
                sanitized[key_text] = sanitize_raw_debug(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_raw_debug(child) for child in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def raw_debug_json(value: Any) -> str:
    try:
        return json.dumps(sanitize_raw_debug(value or {}), ensure_ascii=False, sort_keys=True)
    except Exception:
        return json.dumps({"debug_repr": str(value)}, ensure_ascii=False, sort_keys=True)


def execute_daily_checkin(descriptor: DailyCheckInDescriptor) -> DailyCheckInAttemptResult:
    """Run the provider POST flow for a single game and normalize the result."""
    attempted_at = time.time()
    if descriptor.provider == PROVIDER_HOYOLAB:
        return _execute_hoyolab_daily_checkin(descriptor, attempted_at=attempted_at)
    if descriptor.provider == PROVIDER_NIKKE_BLABLALINK:
        return _execute_nikke_daily_checkin(descriptor, attempted_at=attempted_at)
    return DailyCheckInAttemptResult(
        provider=descriptor.provider,
        game_id=descriptor.game_id,
        game_name=descriptor.game_name,
        status="unsupported",
        attempted_at=attempted_at,
        message="지원하지 않는 출석 provider입니다.",
        post_called=False,
        raw_debug={"provider": descriptor.provider},
    )


def probe_daily_checkin_status(descriptor: DailyCheckInDescriptor) -> DailyCheckInAttemptResult:
    """Read the provider's current daily check-in status without claiming."""
    attempted_at = time.time()
    if descriptor.provider == PROVIDER_HOYOLAB:
        return _probe_hoyolab_daily_checkin(descriptor, attempted_at=attempted_at)
    if descriptor.provider == PROVIDER_NIKKE_BLABLALINK:
        return _probe_nikke_daily_checkin(descriptor, attempted_at=attempted_at)
    return DailyCheckInAttemptResult(
        provider=descriptor.provider,
        game_id=descriptor.game_id,
        game_name=descriptor.game_name,
        status="unsupported",
        attempted_at=attempted_at,
        message="지원하지 않는 출석 provider입니다.",
        post_called=False,
        raw_debug={"provider": descriptor.provider},
    )


def _execute_hoyolab_daily_checkin(
    descriptor: DailyCheckInDescriptor,
    *,
    attempted_at: float,
) -> DailyCheckInAttemptResult:
    try:
        from src.services.hoyolab import get_hoyolab_service

        results = get_hoyolab_service().claim_daily_rewards([descriptor.game_id])
        result = results[0] if results else None
        if result is None:
            return DailyCheckInAttemptResult(
                provider=descriptor.provider,
                game_id=descriptor.game_id,
                game_name=descriptor.game_name,
                status="route_error",
                attempted_at=attempted_at,
                message="HoYoLab 출석 결과가 비어 있습니다.",
                post_called=False,
                raw_debug={"empty_results": True},
            )
        raw_debug = {
            "reward_name": getattr(result, "reward_name", ""),
            "reward_amount": getattr(result, "reward_amount", None),
        }
        status = str(getattr(result, "status", "") or "network_error")
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=getattr(result, "game_name", descriptor.game_name) or descriptor.game_name,
            status=status,
            attempted_at=getattr(result, "updated_at", None).timestamp()
            if getattr(result, "updated_at", None)
            else attempted_at,
            message=getattr(result, "message", "") or "",
            post_called=status not in {"auth_required", "unavailable", "unsupported"},
            raw_debug=raw_debug,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("HoYoLab daily check-in failed: %s", exc, exc_info=True)
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status="network_error",
            attempted_at=time.time(),
            message=str(exc) or type(exc).__name__,
            post_called=True,
            raw_debug={"exception": type(exc).__name__},
        )


def _probe_hoyolab_daily_checkin(
    descriptor: DailyCheckInDescriptor,
    *,
    attempted_at: float,
) -> DailyCheckInAttemptResult:
    try:
        from src.services.hoyolab import get_hoyolab_service

        results = get_hoyolab_service().get_daily_reward_status([descriptor.game_id])
        result = results[0] if results else None
        if result is None:
            return DailyCheckInAttemptResult(
                provider=descriptor.provider,
                game_id=descriptor.game_id,
                game_name=descriptor.game_name,
                status="route_error",
                attempted_at=attempted_at,
                message="HoYoLab 출석 상태 결과가 비어 있습니다.",
                post_called=False,
                raw_debug={"empty_results": True},
            )
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=getattr(result, "game_name", descriptor.game_name) or descriptor.game_name,
            status=str(getattr(result, "status", "") or "network_error"),
            attempted_at=getattr(result, "updated_at", None).timestamp()
            if getattr(result, "updated_at", None)
            else attempted_at,
            message=getattr(result, "message", "") or "",
            post_called=False,
            raw_debug={},
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("HoYoLab daily check-in status probe failed: %s", exc, exc_info=True)
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status="network_error",
            attempted_at=time.time(),
            message=str(exc) or type(exc).__name__,
            post_called=False,
            raw_debug={"exception": type(exc).__name__},
        )


def _execute_nikke_daily_checkin(
    descriptor: DailyCheckInDescriptor,
    *,
    attempted_at: float,
) -> DailyCheckInAttemptResult:
    try:
        from src.services.nikke import get_nikke_service

        status = get_nikke_service().claim_daily_checkin()
        raw_debug = getattr(status, "raw_debug", {}) or {}
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status=str(getattr(status, "status", "") or "network_error"),
            attempted_at=getattr(status, "updated_at", None).timestamp()
            if getattr(status, "updated_at", None)
            else attempted_at,
            message=getattr(status, "message", "") or "",
            post_called=bool(raw_debug.get("post_called")),
            raw_debug=raw_debug,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("NIKKE daily check-in failed: %s", exc, exc_info=True)
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status="network_error",
            attempted_at=time.time(),
            message=str(exc) or type(exc).__name__,
            post_called=False,
            raw_debug={"exception": type(exc).__name__},
        )


def _probe_nikke_daily_checkin(
    descriptor: DailyCheckInDescriptor,
    *,
    attempted_at: float,
) -> DailyCheckInAttemptResult:
    try:
        from src.services.nikke import get_nikke_service

        status = get_nikke_service().get_daily_checkin_status()
        raw_debug = getattr(status, "raw_debug", {}) or {}
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status=str(getattr(status, "status", "") or "network_error"),
            attempted_at=getattr(status, "updated_at", None).timestamp()
            if getattr(status, "updated_at", None)
            else attempted_at,
            message=getattr(status, "message", "") or "",
            post_called=False,
            raw_debug={**raw_debug, "post_called": False},
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("NIKKE daily check-in status probe failed: %s", exc, exc_info=True)
        return DailyCheckInAttemptResult(
            provider=descriptor.provider,
            game_id=descriptor.game_id,
            game_name=descriptor.game_name,
            status="network_error",
            attempted_at=time.time(),
            message=str(exc) or type(exc).__name__,
            post_called=False,
            raw_debug={"exception": type(exc).__name__},
        )
