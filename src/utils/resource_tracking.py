"""Shared constants and helpers for external game resource tracking."""
from __future__ import annotations

import time
import math
from typing import Any

NIKKE_PROVIDER = "nikke_blablalink"
NIKKE_OUTPOST_RESOURCE_KEY = "nikke_outpost_storage"
NIKKE_OUTPOST_LABEL = "전초기지 방어 보상"
NIKKE_OUTPOST_FULL_CHARGE_SECONDS = 24 * 60 * 60
NIKKE_OUTPOST_CORRECTION_THRESHOLD_PERCENT = 0.5


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
