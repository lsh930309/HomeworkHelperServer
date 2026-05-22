from __future__ import annotations

import datetime
from typing import Any

from src.utils.resource_tracking import (
    NIKKE_OUTPOST_FULL_CHARGE_SECONDS,
    clamp_percent,
    is_nikke_outpost_resource,
    predict_nikke_outpost_percent,
)

PROGRESS_SCHEMA_VERSION = 2
SERVER_TRACKED_SOURCE = "server_tracked"
TIMESTAMP_DERIVED_SOURCE = "timestamp_derived"
STAMINA_RECOVERY_SECONDS_PER_UNIT = 360


def _clamped_percentage(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return max(0.0, min((value / maximum) * 100.0, 100.0))


def _remaining_display(remaining_seconds: int) -> str:
    if remaining_seconds <= 0:
        return "0분"
    remaining_hours = remaining_seconds / 3600.0
    if remaining_hours >= 24:
        days = int(remaining_hours // 24)
        hours = int(remaining_hours % 24)
        return f"{days}일 {hours}시간" if hours else f"{days}일"
    if remaining_hours >= 1:
        return f"{int(remaining_hours)}시간"
    return f"{int(remaining_seconds / 60)}분"


def _progress_base(
    *,
    source: str,
    kind: str,
    percentage: float,
    display_text: str,
    status: str = "ok",
    projection: dict[str, Any] | None = None,
    remaining_seconds: int | None = None,
    ready_at: float | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "source": source,
        "kind": kind,
        "percentage": max(0.0, min(float(percentage), 100.0)),
        "display_text": display_text,
        "status": status,
    }
    if projection is not None:
        payload["projection"] = projection
    if remaining_seconds is not None:
        payload["remaining_seconds"] = remaining_seconds
    if ready_at is not None:
        payload["ready_at"] = ready_at
    for key, value in metadata.items():
        if value is not None:
            payload[key] = value
    return payload


def calculate_process_progress(process: Any, current_dt: datetime.datetime | None = None) -> dict[str, Any]:
    """Return a client-safe progress snapshot for a managed process."""
    current_dt = current_dt or datetime.datetime.now()
    current_timestamp = current_dt.timestamp()

    if getattr(process, "resource_tracking_enabled", False) and getattr(process, "resource_provider", None):
        percent = getattr(process, "resource_percent", None)
        status = getattr(process, "resource_status", None)
        label = getattr(process, "resource_label", None) or "리소스"
        provider = getattr(process, "resource_provider", None)
        resource_key = getattr(process, "resource_key", None)
        updated_at = getattr(process, "resource_updated_at", None)
        if percent is not None and status in (None, "ok"):
            if is_nikke_outpost_resource(provider, resource_key):
                percentage = predict_nikke_outpost_percent(
                    percent,
                    updated_at,
                    now=current_timestamp,
                )
            else:
                percentage = clamp_percent(percent)
            if percentage is None:
                return _progress_base(
                    source=SERVER_TRACKED_SOURCE,
                    kind="resource",
                    percentage=0.0,
                    display_text="계산 오류",
                    status="error",
                    provider=provider,
                    key=resource_key,
                    label=label,
                    updated_at=updated_at,
                )
            remaining_seconds = None
            ready_at = None
            projection: dict[str, Any] = {
                "strategy": "static_value",
                "unit": "percent",
                "base_value": clamp_percent(percent),
                "max_value": 100.0,
                "base_timestamp": updated_at,
            }
            if is_nikke_outpost_resource(provider, resource_key):
                remaining_seconds = int(max(0.0, (100.0 - percentage) * NIKKE_OUTPOST_FULL_CHARGE_SECONDS / 100.0))
                ready_at = current_timestamp + remaining_seconds
                projection.update(
                    {
                        "strategy": "linear_percent_fill",
                        "full_recovery_seconds": NIKKE_OUTPOST_FULL_CHARGE_SECONDS,
                        "remaining_seconds": remaining_seconds,
                        "ready_at": ready_at,
                    }
                )
            return _progress_base(
                source=SERVER_TRACKED_SOURCE,
                kind="resource",
                percentage=percentage,
                display_text=f"{percentage:.1f}%",
                status=status or "ok",
                projection=projection,
                remaining_seconds=remaining_seconds,
                ready_at=ready_at,
                provider=provider,
                key=resource_key,
                label=label,
                updated_at=updated_at,
            )
        return _progress_base(
            source=SERVER_TRACKED_SOURCE,
            kind="resource",
            percentage=0.0,
            display_text="동기화 필요",
            status=status or "unavailable",
            provider=provider,
            key=resource_key,
            label=label,
            updated_at=updated_at,
        )

    if getattr(process, "stamina_tracking_enabled", False) and getattr(process, "hoyolab_game_id", None):
        current = getattr(process, "stamina_current", None)
        maximum = getattr(process, "stamina_max", None)
        if current is not None and maximum:
            base_timestamp = getattr(process, "stamina_updated_at", None)
            try:
                base_timestamp_value = float(base_timestamp) if base_timestamp is not None else current_timestamp
            except (TypeError, ValueError):
                base_timestamp_value = current_timestamp
            elapsed_seconds = max(0.0, current_timestamp - base_timestamp_value)
            recovered = int(elapsed_seconds / STAMINA_RECOVERY_SECONDS_PER_UNIT)
            predicted = min(int(maximum), max(0, int(current) + recovered))
            remaining_seconds = max(0, (int(maximum) - predicted) * STAMINA_RECOVERY_SECONDS_PER_UNIT)
            ready_at = current_timestamp + remaining_seconds
            percentage = _clamped_percentage(float(predicted), float(maximum))
            return _progress_base(
                source=SERVER_TRACKED_SOURCE,
                kind="stamina",
                percentage=percentage,
                display_text=f"{predicted}/{maximum}",
                status="ok",
                projection={
                    "strategy": "linear_recovery",
                    "unit": "count",
                    "base_value": int(current),
                    "max_value": int(maximum),
                    "base_timestamp": base_timestamp_value,
                    "recovery_seconds_per_unit": STAMINA_RECOVERY_SECONDS_PER_UNIT,
                    "remaining_seconds": remaining_seconds,
                    "ready_at": ready_at,
                },
                remaining_seconds=remaining_seconds,
                ready_at=ready_at,
                stamina_current=predicted,
                stamina_max=int(maximum),
                hoyolab_game_id=getattr(process, "hoyolab_game_id", None),
                updated_at=base_timestamp_value,
            )
        return _progress_base(
            source=SERVER_TRACKED_SOURCE,
            kind="stamina",
            percentage=0.0,
            display_text="동기화 필요",
            status="unavailable",
            hoyolab_game_id=getattr(process, "hoyolab_game_id", None),
            updated_at=getattr(process, "stamina_updated_at", None),
        )

    last_played = getattr(process, "last_played_timestamp", None)
    cycle_hours = getattr(process, "user_cycle_hours", None)
    if not last_played or not cycle_hours:
        return _progress_base(
            source=TIMESTAMP_DERIVED_SOURCE,
            kind="none",
            percentage=0.0,
            display_text="기록 없음",
            status="unavailable",
        )

    try:
        elapsed_hours = (current_dt - datetime.datetime.fromtimestamp(float(last_played))).total_seconds() / 3600.0
        cycle = float(cycle_hours)
        percentage = max(0.0, min((elapsed_hours / cycle) * 100.0, 100.0)) if cycle > 0 else 0.0
        remaining_hours = max(cycle - elapsed_hours, 0.0)
        remaining_seconds = int(remaining_hours * 3600)
        ready_at = current_timestamp + remaining_seconds
        display = _remaining_display(remaining_seconds)
        cycle_seconds = int(cycle * 3600)
        return _progress_base(
            source=TIMESTAMP_DERIVED_SOURCE,
            kind="cycle",
            percentage=percentage,
            display_text=display,
            status="ok",
            projection={
                "strategy": "cycle_elapsed",
                "unit": "percent",
                "base_timestamp": float(last_played),
                "cycle_seconds": cycle_seconds,
                "remaining_seconds": remaining_seconds,
                "ready_at": ready_at,
            },
            remaining_seconds=remaining_seconds,
            ready_at=ready_at,
        )
    except Exception:
        return _progress_base(
            source=TIMESTAMP_DERIVED_SOURCE,
            kind="none",
            percentage=0.0,
            display_text="계산 오류",
            status="error",
        )
