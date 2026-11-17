"""Shared constants and helpers for external game resource tracking."""
from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

NIKKE_PROVIDER = "nikke_blablalink"
NIKKE_OUTPOST_RESOURCE_KEY = "nikke_outpost_storage"
NIKKE_OUTPOST_LABEL = "전초기지 방어 보상"
NIKKE_OUTPOST_FULL_CHARGE_SECONDS = 24 * 60 * 60
STAMINA_RECOVERY_SECONDS_PER_UNIT = 360
WUWA_PROVIDER = "wuwa"
WUWA_WAVEPLATE_RESOURCE_KEY = "waveplate"
WUWA_WAVEPLATE_LABEL = "웨이브플레이트"


@dataclass
class GameResourceSnapshot:
    provider: str
    resource_key: str
    label: str
    percent: float | None
    status: str
    updated_at: datetime
    message: str = ""
    raw_debug: dict[str, Any] = field(default_factory=dict)
    current: int | None = None
    maximum: int | None = None
    reserve_current: int | None = None
    reserve_max: int | None = None


def wuwa_role_key(role_id: str) -> str:
    return f"waveplate@Asia@{role_id}"


def wuwa_role_id(resource_key: Any) -> str | None:
    if not isinstance(resource_key, str) or not resource_key.startswith("waveplate@Asia@"):
        return None
    role_id = resource_key.removeprefix("waveplate@Asia@")
    return role_id if role_id.isascii() and role_id.isdigit() and role_id.startswith("7") else None


def is_wuwa_waveplate_resource(provider: Any, resource_key: Any) -> bool:
    return provider == WUWA_PROVIDER and resource_key == WUWA_WAVEPLATE_RESOURCE_KEY


def resource_quantity_percent(current: Any, maximum: Any) -> float | None:
    if type(current) is not int or type(maximum) is not int or maximum <= 0 or current < 0:
        return None
    return 100.0 if current >= maximum else current / maximum * 100.0


def resource_gauge_presentation(
    percentage: Any,
    display_text: str,
    reserve_current: Any = None,
    reserve_max: Any = None,
) -> dict[str, Any]:
    """일반 게이지가 가득 찼고 유효한 초과량이 있을 때만 같은 캡슐에 덧그린다."""
    normal = clamp_percent(percentage)
    reserve = resource_quantity_percent(reserve_current, reserve_max)
    show_reserve = bool(
        normal is not None and normal >= 100.0 and reserve is not None
        and reserve_current > 0 and reserve_current <= reserve_max
    )
    return {
        "display_text": f"{reserve_current}/{reserve_max}" if show_reserve else display_text,
        "overlay_percentage": reserve if show_reserve else None,
    }


def predict_stamina_value(
    stored_current: int | None,
    maximum: int | None,
    updated_at: float | None,
    *,
    now: float,
) -> int | None:
    """Return the recovered count at an explicit observation/display time."""
    if stored_current is None or maximum is None:
        return None
    elapsed = max(0.0, float(now) - float(updated_at)) if updated_at is not None else 0.0
    recovered = int(elapsed / STAMINA_RECOVERY_SECONDS_PER_UNIT)
    return min(int(maximum), max(0, int(stored_current) + recovered))


def is_nikke_outpost_resource(provider: Any, resource_key: Any) -> bool:
    """Return whether a resource identity is NIKKE outpost defense reward."""
    return provider == NIKKE_PROVIDER and resource_key == NIKKE_OUTPOST_RESOURCE_KEY


def clamp_percent(value: Any) -> float | None:
    """Normalize a percent-like value to the inclusive 0.0~100.0 range."""
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(percent):
        return None
    return max(0.0, min(percent, 100.0))


def predict_nikke_outpost_percent(
    stored_percent: Any,
    updated_at: Any,
    *,
    now: float | None = None,
) -> float | None:
    """Predict NIKKE outpost defense reward fullness from a stored API snapshot.

    ShiftyPad exposes the value only as a normalized percent-like fullness. The
    game fills from 0% to 100% over 24 hours, so local UI can keep advancing the
    stored value until the next server refresh.
    """
    base = clamp_percent(stored_percent)
    if base is None:
        return None
    try:
        updated_at_value = float(updated_at)
    except (TypeError, ValueError):
        return base
    current_time = time.time() if now is None else float(now)
    elapsed_seconds = max(0.0, current_time - updated_at_value)
    predicted = base + (elapsed_seconds * 100.0 / NIKKE_OUTPOST_FULL_CHARGE_SECONDS)
    return max(0.0, min(predicted, 100.0))
