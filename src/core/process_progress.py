from __future__ import annotations

import datetime
from typing import Any


def calculate_process_progress(process: Any, current_dt: datetime.datetime | None = None) -> dict[str, Any]:
    """Return a client-safe progress snapshot for a managed process."""
    current_dt = current_dt or datetime.datetime.now()
    if getattr(process, "stamina_tracking_enabled", False) and getattr(process, "hoyolab_game_id", None):
        current = getattr(process, "stamina_current", None)
        maximum = getattr(process, "stamina_max", None)
        if current is not None and maximum:
            percentage = max(0.0, min((float(current) / float(maximum)) * 100.0, 100.0))
            return {
                "kind": "stamina",
                "percentage": percentage,
                "display_text": f"{current}/{maximum}",
                "stamina_current": current,
                "stamina_max": maximum,
                "hoyolab_game_id": getattr(process, "hoyolab_game_id", None),
            }

    last_played = getattr(process, "last_played_timestamp", None)
    cycle_hours = getattr(process, "user_cycle_hours", None)
    if not last_played or not cycle_hours:
        return {"kind": "none", "percentage": 0.0, "display_text": "기록 없음"}

    try:
        elapsed_hours = (current_dt - datetime.datetime.fromtimestamp(float(last_played))).total_seconds() / 3600.0
        cycle = float(cycle_hours)
        percentage = max(0.0, min((elapsed_hours / cycle) * 100.0, 100.0)) if cycle > 0 else 0.0
        remaining_hours = max(cycle - elapsed_hours, 0.0)
        remaining_seconds = int(remaining_hours * 3600)
        ready_at = (current_dt + datetime.timedelta(seconds=remaining_seconds)).timestamp()
        if remaining_hours >= 24:
            days = int(remaining_hours // 24)
            hours = int(remaining_hours % 24)
            display = f"{days}일 {hours}시간" if hours else f"{days}일"
        elif remaining_hours >= 1:
            display = f"{int(remaining_hours)}시간"
        else:
            display = f"{int(remaining_hours * 60)}분"
        return {
            "kind": "cycle",
            "percentage": percentage,
            "display_text": display,
            "remaining_seconds": remaining_seconds,
            "ready_at": ready_at,
        }
    except Exception:
        return {"kind": "none", "percentage": 0.0, "display_text": "계산 오류"}
