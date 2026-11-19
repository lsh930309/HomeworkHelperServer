from __future__ import annotations

import datetime
import math
from typing import Any

from src.utils.resource_tracking import (
    STAMINA_RECOVERY_SECONDS_PER_UNIT,
    clamp_percent,
    predict_nikke_outpost_percent,
    predict_stamina_value,
    resource_base_percentage,
    resource_definition,
    resource_gauge_presentation,
    resource_quantity_percent,
)

PROGRESS_SCHEMA_VERSION = 2
SERVER_TRACKED_SOURCE = "server_tracked"
TIMESTAMP_DERIVED_SOURCE = "timestamp_derived"


def _clamped_percentage(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return max(0.0, min((value / maximum) * 100.0, 100.0))


def _count_recovery_projection(
    current: int, maximum: int, base_timestamp: float, recovery_seconds_per_unit: int, *, now: float,
) -> tuple[int, dict[str, Any]]:
    predicted = predict_stamina_value(
        current, maximum, base_timestamp, now=now, recovery_seconds_per_unit=recovery_seconds_per_unit,
    )
    ready_at = base_timestamp + max(0, int(maximum) - int(current)) * recovery_seconds_per_unit
    return predicted, {
        "strategy": "linear_recovery",
        "unit": "count",
        "base_value": int(current),
        "max_value": int(maximum),
        "base_timestamp": base_timestamp,
        "recovery_seconds_per_unit": recovery_seconds_per_unit,
        "remaining_seconds": max(0, int(ready_at - now)),
        "ready_at": ready_at,
    }


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
    presentation = resource_gauge_presentation(
        percentage, display_text,
        metadata.get("resource_reserve_current"), metadata.get("resource_reserve_max"),
    )
    payload["display_text"] = presentation["display_text"]
    payload["gauge_text"] = f"{payload['percentage']:.1f}%" if kind == "cycle" else presentation["display_text"]
    if presentation["overlay_percentage"] is not None:
        payload["overlay_percentage"] = presentation["overlay_percentage"]
        if projection is not None and projection["strategy"] == "linear_recovery":
            # A full count with a visible reserve no longer grows between observations.
            projection = {
                "strategy": "static_value",
                "unit": "percent",
                "base_value": payload["percentage"],
                "max_value": 100.0,
                "base_timestamp": projection["base_timestamp"],
                "remaining_seconds": remaining_seconds,
                "ready_at": ready_at,
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
        resource_current = getattr(process, "resource_current", None)
        resource_max = getattr(process, "resource_max", None)
        definition = resource_definition(provider, resource_key)
        quantity_percent = resource_quantity_percent(resource_current, resource_max)
        percent = resource_base_percentage(definition, percent, resource_current, resource_max)
        if definition is not None and definition.label is not None:
            label = definition.label
        if percent is not None and status in (None, "ok"):
            count_recovery = definition.recovery_seconds_per_unit if definition else None
            percent_recovery = definition.full_recovery_seconds if definition else None
            projection: dict[str, Any] = {
                "strategy": "static_value",
                "unit": "percent",
                "base_value": clamp_percent(percent),
                "max_value": 100.0,
                "base_timestamp": updated_at,
            }
            percentage = projection["base_value"]
            if (
                count_recovery is not None and quantity_percent is not None
                and type(updated_at) in (int, float) and 0 < updated_at <= current_timestamp
            ):
                resource_current, projection = _count_recovery_projection(
                    resource_current, resource_max, updated_at, count_recovery, now=current_timestamp,
                )
                percentage = resource_quantity_percent(resource_current, resource_max)
            elif percent_recovery is not None:
                percentage = predict_nikke_outpost_percent(
                    percent, updated_at, now=current_timestamp, full_recovery_seconds=percent_recovery,
                )
                if percentage is not None:
                    remaining_seconds = int(max(0.0, (100.0 - percentage) * percent_recovery / 100.0))
                    projection.update(
                        strategy="linear_percent_fill",
                        full_recovery_seconds=percent_recovery,
                        remaining_seconds=remaining_seconds,
                        ready_at=current_timestamp + remaining_seconds,
                    )
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
            return _progress_base(
                source=SERVER_TRACKED_SOURCE,
                kind="resource",
                percentage=percentage,
                display_text=(f"{resource_current}/{resource_max}" if quantity_percent is not None else f"{percentage:.1f}%"),
                status=status or "ok",
                projection=projection,
                remaining_seconds=projection.get("remaining_seconds"),
                ready_at=projection.get("ready_at"),
                provider=provider,
                key=resource_key,
                label=label,
                updated_at=updated_at,
                resource_current=resource_current,
                resource_max=resource_max,
                resource_reserve_current=getattr(process, "resource_reserve_current", None),
                resource_reserve_max=getattr(process, "resource_reserve_max", None),
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
            if not math.isfinite(base_timestamp_value):
                base_timestamp_value = current_timestamp
            predicted, projection = _count_recovery_projection(
                current, maximum, base_timestamp_value, STAMINA_RECOVERY_SECONDS_PER_UNIT, now=current_timestamp,
            )
            percentage = _clamped_percentage(float(predicted), float(maximum))
            return _progress_base(
                source=SERVER_TRACKED_SOURCE,
                kind="stamina",
                percentage=percentage,
                display_text=f"{predicted}/{maximum}",
                status="ok",
                projection=projection,
                remaining_seconds=projection["remaining_seconds"],
                ready_at=projection["ready_at"],
                stamina_current=predicted,
                stamina_max=int(maximum),
                resource_current=predicted,
                resource_max=int(maximum),
                resource_reserve_current=getattr(process, "resource_reserve_current", None),
                resource_reserve_max=getattr(process, "resource_reserve_max", None),
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
