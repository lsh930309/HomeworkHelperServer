"""Shared provider credential health helpers.

The same HoYoLab/BlablaLink cookies are used by resource tracking and daily
check-in automation.  This module keeps their observed validity in a small,
provider-scoped vocabulary so GUI labels, API persistence, and notification
paths do not have to infer state from free-form messages.
"""
from __future__ import annotations

from typing import Any

PROVIDER_HOYOLAB = "hoyolab"
PROVIDER_NIKKE_BLABLALINK = "nikke_blablalink"

HEALTH_UNKNOWN = "unknown"
HEALTH_OK = "ok"
HEALTH_WARNING = "warning"
HEALTH_AUTH_PROBLEM = "auth_problem"

OK_REASONS = {"ok", "success", "already_done", "ready"}
AUTH_PROBLEM_REASONS = {
    "auth_required",
    "auth_expired",
    "game_login_required",
    "challenge_required",
    "role_not_found",
}
WARNING_REASONS = {"route_error", "unavailable", "unsupported"}
TRANSIENT_REASONS = {"network_error"}

PROVIDER_LABELS = {
    PROVIDER_HOYOLAB: "HoYoLab",
    PROVIDER_NIKKE_BLABLALINK: "BlablaLink",
}


def provider_label(provider: str | None) -> str:
    return PROVIDER_LABELS.get(str(provider or ""), str(provider or "provider"))


def classify_reason(reason: Any) -> str | None:
    text = str(reason or "").strip()
    if not text:
        return None
    if text in OK_REASONS:
        return HEALTH_OK
    if text in AUTH_PROBLEM_REASONS:
        return HEALTH_AUTH_PROBLEM
    if text in WARNING_REASONS:
        return HEALTH_WARNING
    if text in TRANSIENT_REASONS:
        return None
    return HEALTH_WARNING


def update_payload_for_reason(
    provider: str,
    reason: Any,
    *,
    message: str = "",
    source: str,
    process_id: str | None = None,
    game_id: str | None = None,
    detected_at: float | None = None,
) -> dict[str, Any] | None:
    """Build a normalized provider-health update or return None for transients."""
    status = classify_reason(reason)
    if status is None:
        return None
    reason_text = str(reason or "").strip() or status
    return {
        "provider": provider,
        "status": status,
        "reason": reason_text,
        "message": str(message or reason_text),
        "source": source,
        "process_id": process_id,
        "game_id": game_id,
        "detected_at": detected_at,
    }


def is_alertable_health(status: Any, reason: Any = None) -> bool:
    return str(status or "") == HEALTH_AUTH_PROBLEM or str(reason or "") in AUTH_PROBLEM_REASONS


def user_message(provider: str, status: str, reason: str | None = None, message: str | None = None) -> str:
    label = provider_label(provider)
    detail = str(message or reason or "").strip()
    if status == HEALTH_OK:
        return f"{label} 인증이 정상으로 확인되었습니다." + (f" ({detail})" if detail and detail != "ok" else "")
    if status == HEALTH_AUTH_PROBLEM:
        if provider == PROVIDER_NIKKE_BLABLALINK:
            base = "BlablaLink/ShiftyPad에 다시 로그인한 뒤 쿠키를 다시 추출하세요."
        else:
            base = "HoYoLab에 다시 로그인한 뒤 쿠키를 다시 추출하세요."
        return f"{label} 쿠키/토큰 유효성 문제가 감지되었습니다. {base}" + (f" ({detail})" if detail else "")
    if status == HEALTH_WARNING:
        return f"{label} 연동 상태 확인이 필요합니다." + (f" ({detail})" if detail else "")
    return f"{label} 쿠키가 저장되어 있습니다. 유효성은 검사/자동 동기화 결과로 확인됩니다."
