"""Beholder: semantic DB mutation guard and incident helpers."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
import psutil

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from src.data import models

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

STATUS_PENDING = "pending"
STATUS_ALLOWED = "allowed"
STATUS_DENIED = "denied"
STATUS_QUARANTINED = "quarantined"
STATUS_RESOLVED = "resolved"

MAX_UNEVIDENCED_SESSION_SECONDS = 7 * 24 * 60 * 60
MAX_HEARTBEAT_GAP_SECONDS = 10 * 60
LEGACY_OPEN_SESSION_SECONDS = 24 * 60 * 60
MAX_LAUNCH_ARGS_LENGTH = 512
GLOBAL_SETTINGS_TABLE = "global_settings"
MANAGED_PROCESSES_TABLE = "managed_processes"
WEB_SHORTCUTS_TABLE = "web_shortcuts"
PROCESS_SESSIONS_TABLE = "process_sessions"

PROCESS_FIELDS = {column.name for column in models.Process.__table__.columns}
WEB_SHORTCUT_FIELDS = {column.name for column in models.WebShortcut.__table__.columns}
SESSION_FIELDS = {column.name for column in models.ProcessSession.__table__.columns}
PROCESS_RUNTIME_FIELDS = {
    "last_played_timestamp",
    "stamina_current",
    "stamina_max",
    "stamina_updated_at",
    "resource_percent",
    "resource_updated_at",
    "resource_status",
}
PROCESS_EDITOR_FIELDS = PROCESS_FIELDS - PROCESS_RUNTIME_FIELDS
WEB_SHORTCUT_RUNTIME_FIELDS = {"last_reset_timestamp"}
WEB_SHORTCUT_EDITOR_FIELDS = WEB_SHORTCUT_FIELDS - WEB_SHORTCUT_RUNTIME_FIELDS

RUNTIME_SETTINGS_FIELDS = {
    "theme", "always_on_top", "hide_on_game", "run_as_admin", "run_on_startup",
    "sidebar_enabled", "sidebar_mode", "sidebar_handle_auto_hide",
    "screenshot_enabled", "recording_enabled", "remote_server_mode_enabled",
}
SIDEBAR_SETTINGS_FIELDS = {
    "sidebar_enabled", "sidebar_mode", "sidebar_trigger_y_start", "sidebar_trigger_y_end",
    "sidebar_handle_auto_hide", "sidebar_auto_hide_ms", "sidebar_edge_width_px",
    "sidebar_height_ratio", "sidebar_opacity", "sidebar_clock_enabled",
    "sidebar_clock_format", "sidebar_playtime_enabled", "sidebar_playtime_prefix",
    "sidebar_volume_section_enabled", "screenshot_enabled", "screenshot_save_dir",
    "screenshot_gamepad_trigger", "screenshot_disable_gamebar", "screenshot_capture_mode",
    "screenshot_gamepad_button_index", "screenshot_trigger_vk", "recording_enabled",
    "obs_host", "obs_port", "obs_password", "obs_exe_path", "obs_auto_launch",
    "obs_launch_hidden", "obs_watch_output_dir", "obs_recording_output_dir",
    "recording_hold_threshold_ms",
}
GLOBAL_DIALOG_FIELDS = {
    "sleep_start_time_str", "sleep_end_time_str", "sleep_correction_advance_notify_hours",
    "cycle_deadline_advance_notify_hours", "run_on_startup", "always_on_top",
    "run_as_admin", "notify_on_mandatory_time", "notify_on_cycle_deadline",
    "notify_on_sleep_correction", "notify_on_daily_reset", "stamina_notify_enabled",
    "stamina_notify_threshold", "theme", "hide_on_game",
}
PERSONALIZED_SETTINGS_FIELDS = {
    "sidebar_mode", "sidebar_trigger_y_start", "sidebar_trigger_y_end",
    "sidebar_handle_auto_hide", "sidebar_auto_hide_ms", "sidebar_edge_width_px", "sidebar_height_ratio", "sidebar_opacity", "sidebar_clock_format",
    "sidebar_playtime_prefix", "screenshot_save_dir", "screenshot_capture_mode",
    "screenshot_gamepad_button_index", "screenshot_trigger_vk", "recording_enabled",
    "obs_host", "obs_port", "obs_password", "obs_exe_path", "obs_auto_launch",
    "obs_launch_hidden", "obs_watch_output_dir", "obs_recording_output_dir",
    "recording_hold_threshold_ms",
}

SETTINGS_RANGE_RULES: dict[str, tuple[float, float, str]] = {
    "sleep_correction_advance_notify_hours": (0, 5, "수면 보정 사전 알림 시간"),
    "cycle_deadline_advance_notify_hours": (0, 12, "주기 마감 사전 알림 시간"),
    "stamina_notify_threshold": (1, 100, "스태미나 알림 기준"),
    "sidebar_trigger_y_start": (0.0, 1.0, "사이드바 손잡이 감지 시작 위치"),
    "sidebar_trigger_y_end": (0.0, 1.0, "사이드바 손잡이 감지 종료 위치"),
    "sidebar_auto_hide_ms": (0, 60000, "사이드바 자동 숨김 시간"),
    "sidebar_edge_width_px": (1, 50, "사이드바 엣지 감지 폭"),
    "sidebar_height_ratio": (0.3, 1.0, "사이드바 높이 비율"),
    "sidebar_opacity": (0.1, 1.0, "사이드바 투명도"),
    "screenshot_gamepad_button_index": (-1, 32, "게임패드 버튼 번호"),
    "screenshot_trigger_vk": (0, 255, "스크린샷 트리거 키"),
    "obs_port": (1, 65535, "OBS 포트"),
    "recording_hold_threshold_ms": (100, 2000, "녹화 홀드 시간"),
}
SETTINGS_ENUM_RULES: dict[str, tuple[set[str], str]] = {
    "theme": ({"system", "light", "dark"}, "테마"),
    "sidebar_mode": ({"always", "game", "disabled"}, "사이드바 사용 방식"),
    "screenshot_capture_mode": ({"fullscreen", "game_window"}, "스크린샷 캡처 방식"),
}

FIELD_LABELS: dict[str, str] = {
    **{field: label for field, (_minimum, _maximum, label) in SETTINGS_RANGE_RULES.items()},
    **{field: label for field, (_allowed, label) in SETTINGS_ENUM_RULES.items()},
    "global_settings": "전체 설정",
    "managed_processes": "게임 항목",
    "web_shortcuts": "웹 바로가기",
    "process_sessions": "플레이 기록",
    "sleep_start_time_str": "수면 시작 시각",
    "sleep_end_time_str": "수면 종료 시각",
    "always_on_top": "항상 위",
    "run_as_admin": "관리자 권한 실행",
    "run_on_startup": "시작프로그램",
    "hide_on_game": "게임 실행 시 숨김",
    "notify_on_mandatory_time": "필수 시간 알림",
    "notify_on_cycle_deadline": "주기 마감 알림",
    "notify_on_sleep_correction": "수면 보정 알림",
    "notify_on_daily_reset": "일일 초기화 알림",
    "stamina_notify_enabled": "스태미나 알림",
    "sidebar_enabled": "사이드바 사용",
    "sidebar_mode": "사이드바 사용 방식",
    "sidebar_handle_auto_hide": "사이드바 손잡이 자동 숨김",
    "sidebar_clock_enabled": "사이드바 시계 표시",
    "sidebar_playtime_enabled": "사이드바 플레이타임 표시",
    "sidebar_volume_section_enabled": "사이드바 볼륨 영역",
    "screenshot_enabled": "스크린샷 사용",
    "screenshot_save_dir": "스크린샷 저장 폴더",
    "screenshot_gamepad_trigger": "게임패드 스크린샷 트리거",
    "screenshot_disable_gamebar": "Xbox Game Bar 비활성화",
    "recording_enabled": "녹화 사용",
    "remote_server_mode_enabled": "리모트 서버 모드",
    "obs_host": "OBS 호스트",
    "obs_password": "OBS 비밀번호",
    "obs_exe_path": "OBS 실행 파일",
    "obs_auto_launch": "OBS 자동 실행",
    "obs_launch_hidden": "OBS 숨김 실행",
    "obs_watch_output_dir": "OBS 출력 폴더 감시",
    "obs_recording_output_dir": "OBS 녹화 저장 폴더",
    "preferred_launch_type": "실행 방식",
    "launch_args_enabled": "직접 실행 인자 사용",
    "launch_args": "직접 실행 인자",
    "user_cycle_hours": "반복 주기",
    "default_volume": "기본 볼륨",
    "last_played_timestamp": "마지막 플레이 시각",
    "stamina_current": "현재 스태미나",
    "stamina_max": "최대 스태미나",
    "stamina_updated_at": "스태미나 갱신 시각",
    "last_reset_timestamp": "웹 바로가기 완료 시각",
}


def _schema_fields() -> set[str]:
    from src.data import schemas
    fields = getattr(schemas.GlobalSettingsSchema, "model_fields", None)
    if fields is not None:
        return set(fields)
    return set(getattr(schemas.GlobalSettingsSchema, "__fields__", {}))


def _schema_defaults() -> dict[str, Any]:
    from src.data import schemas
    schema = schemas.GlobalSettingsSchema()
    if hasattr(schema, "model_dump"):
        return schema.model_dump()
    return schema.dict()


def allowed_settings_fields_for_actor(actor: str | None) -> set[str]:
    actor = actor or "settings_full_update"
    all_fields = _schema_fields()
    if actor == "sidebar_settings_dialog":
        return set(SIDEBAR_SETTINGS_FIELDS)
    if actor == "global_settings_dialog":
        return set(GLOBAL_DIALOG_FIELDS)
    if actor == "remote_settings_dialog":
        return {"remote_server_mode_enabled"}
    if actor in {"settings_full_update", "settings_migration", "api_settings_put"}:
        return all_fields
    return set()


@dataclass(frozen=True)
class BeholderOperation:
    kind: str
    actor: str
    allowed_tables: set[str] = field(default_factory=set)
    allowed_columns: dict[str, set[str]] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    override_token: str | None = None


class BeholderBlocked(Exception):
    """Raised when Beholder blocks a potentially destructive mutation."""

    def __init__(self, incident: models.BeholderIncident):
        self.incident = incident
        super().__init__(incident.safe_recommendation or incident.suspected_cause or "Beholder blocked mutation")


def _actor_label(actor: str | None) -> str:
    return {
        "process_monitor": "게임 실행 감지기",
        "legacy_process_monitor": "기존 GUI 실행 감지기",
        "global_settings_dialog": "기존 GUI 전역 설정 창",
        "sidebar_settings_dialog": "기존 GUI 사이드바 설정 창",
        "remote_settings_dialog": "기존 GUI 원격 설정 창",
        "hoyolab_slow_followup": "HoYoLab 지연 반영 재확인",
        "runtime_stamina_tracker": "스태미나 런타임 보정",
    }.get(actor or "", actor or "알 수 없는 경로")


def _operation_label(kind: str | None) -> str:
    return {
        "hoyolab_session_stamina_rewrite": "게임 종료 후 HoYoLab 서버 반영 지연을 재확인해 직전 세션의 종료 스태미나를 보정",
        "process_stamina_refresh": "HoYoLab에서 현재 스태미나를 즉시 조회해 게임 카드의 잔여 스태미나를 갱신",
        "process_runtime_state_update": "게임 실행/종료 감지 결과에 따라 마지막 플레이 시각과 런타임 스태미나를 갱신",
        "runtime_start": "게임 시작 기록 생성",
        "runtime_stop": "게임 종료 기록 저장",
        "settings_update": "설정 저장",
    }.get(kind or "", kind or "데이터 변경")


def _compose_user_summary(incident: models.BeholderIncident) -> str:
    actor = _actor_label(getattr(incident, "actor", None))
    operation = _operation_label(getattr(incident, "operation_kind", None))
    target = getattr(incident, "target_summary", None) or "대상 데이터"
    current = getattr(incident, "current_state_summary", None) or "현재 상태 정보 없음"
    proposed = getattr(incident, "proposed_change_summary", None) or "변경 내용 정보 없음"
    cause = getattr(incident, "suspected_cause", None) or "안전 근거가 부족합니다."
    return (
        f"{actor}가 {target}에 대해 '{operation}' 작업을 수행하려 했습니다. "
        f"현재 상태는 {current}이며, 요청된 변경은 {proposed}입니다. "
        f"비홀더는 {cause} 때문에 사용자 확인이 필요하다고 판단했습니다."
    )


def incident_to_dict(incident: models.BeholderIncident) -> dict[str, Any]:
    user_title = getattr(incident, "user_title", None) or _default_user_title(incident)
    user_summary = getattr(incident, "user_summary", None) or _compose_user_summary(incident)
    user_impact = getattr(incident, "user_impact", None) or (incident.safe_recommendation or incident.proposed_change_summary)
    return {
        "id": incident.id,
        "severity": incident.severity,
        "status": incident.status,
        "operation_kind": incident.operation_kind,
        "actor": incident.actor,
        "target_summary": incident.target_summary,
        "suspected_cause": incident.suspected_cause,
        "current_state_summary": incident.current_state_summary,
        "proposed_change_summary": incident.proposed_change_summary,
        "risk_score": incident.risk_score,
        "risk_factors": incident.risk_factors or [],
        "risk_labels": [_user_friendly_risk_label(item) for item in (incident.risk_factors or [])],
        "safe_recommendation": incident.safe_recommendation,
        "user_title": user_title,
        "user_summary": user_summary,
        "user_impact": user_impact,
        "recommended_action": getattr(incident, "recommended_action", None),
        "available_actions": _enrich_actions(getattr(incident, "available_actions", None) or _default_actions(incident), getattr(incident, "recommended_action", None)),
        "resolution_metadata": getattr(incident, "resolution_metadata", None) or {},
        "created_at": incident.created_at,
        "resolved_at": incident.resolved_at,
        "has_override_token": bool(incident.override_token and not incident.override_used_at),
    }


def _default_user_title(incident: models.BeholderIncident) -> str:
    if incident.operation_kind.startswith("settings"):
        return "설정 변경이 안전하지 않아 저장하지 않았습니다"
    if incident.operation_kind.startswith("runtime_start"):
        return "이전 플레이 기록과 새 기록이 충돌할 수 있습니다"
    return "데이터 변경 확인이 필요합니다"


def _user_friendly_risk_label(factor: str) -> str:
    labels = {
        "unauthorized_table_write": "정상 화면 밖 데이터 변경",
        "unauthorized_column_write": "현재 화면에서 바꿀 수 없는 항목 포함",
        "bulk_settings_default_regression": "대량 설정 초기화 의심",
        "personalized_settings_default_regression": "개인화 설정 초기화 의심",
        "duplicate_open_session": "열린 플레이 기록 중복",
        "runtime_state_ambiguous": "앱 재시작 후 현재 실행 상태 판단 필요",
        "open_session_after_app_restart": "앱 재시작 후 닫히지 않은 기록",
        "duplicate_legacy_open_session": "이전 버전 열린 기록 충돌",
        "legacy_open_session_stale": "오래된 열린 기록만 남아 있음",
        "open_session_after_restart": "앱 재시작 후 닫히지 않은 기록",
        "game_not_running": "현재 게임 미실행",
        "last_heartbeat_available": "마지막 앱 생존 시각 확인됨",
        "pc_reboot_detected": "PC 재부팅 정황",
        "legacy_open_session_without_heartbeat": "종료 시각 복구 불가",
        "legacy_session_metadata_missing": "이전 버전 기록 정보 부족",
        "delete_process_with_open_sessions": "열린 기록이 있는 게임 삭제",
        "runtime_history_orphan_risk": "기록이 고아 데이터가 될 위험",
        "invalid_negative_stamina": "음수 스태미나 기록",
        "invalid_setting_value": "설정 값 범위 오류",
        "invalid_setting_relation": "설정 조합 오류",
        "invalid_process_value": "게임 항목 값 범위 오류",
        "invalid_stamina_range": "스태미나 현재/최대값 충돌",
        "invalid_timestamp": "비정상 타임스탬프",
        "negative_duration": "종료 시간이 시작 시간보다 빠름",
        "unknown_owner_long_session": "기록 소유자를 알 수 없는 장시간 세션",
        "extreme_duration_without_sufficient_evidence": "비정상적으로 긴 플레이 시간",
        "stale_heartbeat": "마지막 앱 생존 시각이 너무 오래됨",
        "actor_not_runtime_owner": "런타임 담당자가 아닌 요청",
    }
    if factor in labels:
        return labels[factor]
    if factor in FIELD_LABELS:
        return f"{FIELD_LABELS[factor]} 변경"
    if factor.startswith("invalid_current_status:"):
        status = factor.split(":", 1)[1]
        status_label = {
            "abandoned": "버려진 기록",
            "quarantined": "격리된 기록",
            "closed": "이미 닫힌 기록",
        }.get(status, f"알 수 없는 상태({status})")
        return f"{status_label}을 다시 종료하려는 요청"
    if ">" in factor:
        left, right = factor.split(">", 1)
        return f"{FIELD_LABELS.get(left, left)} 값이 {FIELD_LABELS.get(right, right)}보다 큼"
    return factor


def _action_outcome(action_id: str) -> str:
    return {
        "deny": "아무 데이터도 바꾸지 않고 현재 상태를 유지합니다.",
        "quarantine": "데이터는 바꾸지 않고 이 사건을 보류/격리 상태로 표시합니다.",
        "allow_once": "동일한 저장 요청을 한 번만 통과시킵니다. 의도한 변경일 때만 사용하세요.",
        "continue_existing_session": "새 기록을 만들지 않고 기존 열린 세션을 계속 사용합니다.",
        "close_previous_and_start_new": "이전 열린 세션을 지금 시각에 닫고 새 세션을 시작합니다.",
        "close_at_last_app_heartbeat": "마지막으로 앱이 살아있던 시각에 세션을 정상 종료로 기록합니다.",
        "abandon_open_sessions": "복구할 수 없는 열린 기록을 0초 abandoned 기록으로 정리합니다.",
        "abandon_legacy_and_start_new": "오래된 열린 기록을 abandoned로 정리하고 현재 실행을 새 기록으로 시작합니다.",
        "close_sessions_and_delete_process": "열린 세션을 안전하게 닫은 뒤 게임 항목을 삭제합니다.",
    }.get(action_id, "선택한 방식으로 사건을 처리합니다.")


def _enrich_actions(actions: list[dict[str, Any]], recommended_action: str | None = None) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for action in actions:
        item = dict(action)
        if recommended_action and item.get("id") == recommended_action:
            item["recommended"] = True
        item.setdefault("outcome", _action_outcome(str(item.get("id", ""))))
        if item.get("recommended") and not item.get("recommended_reason"):
            item["recommended_reason"] = "현재 증거 기준으로 데이터 왜곡 가능성이 가장 낮은 선택입니다."
        enriched.append(item)
    return enriched


def _default_actions(incident: models.BeholderIncident) -> list[dict[str, Any]]:
    actions = [
        {"id": "deny", "label": "차단 유지", "description": "이번 변경을 저장하지 않고 현재 DB를 유지합니다.", "recommended": True},
        {"id": "quarantine", "label": "나중에 검토", "description": "데이터는 바꾸지 않고 사건만 보류 상태로 표시합니다."},
        {"id": "allow_once", "label": "이번 한 번 허용", "description": "정말 의도한 변경일 때 동일 작업을 1회만 허용합니다.", "danger": True},
    ]
    return _enrich_actions(actions, getattr(incident, "recommended_action", None) or "deny")


def create_incident(
    db: Session,
    *,
    severity: str,
    operation: BeholderOperation,
    target_summary: str,
    suspected_cause: str,
    current_state_summary: str,
    proposed_change_summary: str,
    risk_score: int,
    risk_factors: list[str],
    safe_recommendation: str,
    user_title: str | None = None,
    user_summary: str | None = None,
    user_impact: str | None = None,
    recommended_action: str | None = None,
    available_actions: list[dict[str, Any]] | None = None,
    resolution_metadata: dict[str, Any] | None = None,
) -> models.BeholderIncident:
    metadata = dict(resolution_metadata or {})
    metadata.setdefault("override_scope", _override_scope(operation, target_summary=target_summary))
    incident = models.BeholderIncident(
        severity=severity,
        status=STATUS_PENDING,
        operation_kind=operation.kind,
        actor=operation.actor,
        target_summary=target_summary,
        suspected_cause=suspected_cause,
        current_state_summary=current_state_summary,
        proposed_change_summary=proposed_change_summary,
        risk_score=risk_score,
        risk_factors=risk_factors,
        safe_recommendation=safe_recommendation,
        user_title=user_title,
        user_summary=user_summary,
        user_impact=user_impact,
        recommended_action=recommended_action,
        available_actions=available_actions,
        resolution_metadata=metadata,
        created_at=time.time(),
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def issue_override_token(db: Session, incident: models.BeholderIncident) -> str:
    token = secrets.token_urlsafe(24)
    incident.status = STATUS_ALLOWED
    incident.override_token = token
    incident.resolved_at = time.time()
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return token


def consume_override_token(db: Session, token: str | None, operation: BeholderOperation | str) -> bool:
    if not token:
        return False
    incident = db.query(models.BeholderIncident).filter(
        models.BeholderIncident.override_token == token,
        models.BeholderIncident.status == STATUS_ALLOWED,
        models.BeholderIncident.override_used_at.is_(None),
    ).first()
    if not incident or not _scope_matches_operation(incident, operation):
        return False
    incident.override_used_at = time.time()
    incident.status = STATUS_RESOLVED
    db.add(incident)
    # SessionLocal disables autoflush, so make the one-shot consumption visible
    # to any later guard query in the same mutation/transaction.
    db.flush()
    return True


def _available_action_ids(incident: models.BeholderIncident) -> set[str]:
    """Incident가 현재 제공하는 action id 집합을 반환합니다."""
    actions = getattr(incident, "available_actions", None) or _default_actions(incident)
    return {str(action.get("id")) for action in actions if action.get("id")}


def active_incidents(db: Session) -> list[models.BeholderIncident]:
    return db.query(models.BeholderIncident).filter(
        models.BeholderIncident.status == STATUS_PENDING
    ).order_by(models.BeholderIncident.created_at.desc()).all()


def session_status_for(session: models.ProcessSession) -> str:
    if getattr(session, "session_status", None):
        return session.session_status
    if session.end_timestamp is not None:
        return "closed"
    return "open"


def _is_open_session(session: models.ProcessSession) -> bool:
    return session.end_timestamp is None and session_status_for(session) not in {"closed", "abandoned", "quarantined"}


def _is_legacy_open_session(session: models.ProcessSession) -> bool:
    return session.end_timestamp is None and not getattr(session, "session_status", None)


def _table_label(table: str) -> str:
    return {
        GLOBAL_SETTINGS_TABLE: "설정",
        MANAGED_PROCESSES_TABLE: "게임 항목",
        WEB_SHORTCUTS_TABLE: "웹 바로가기",
        PROCESS_SESSIONS_TABLE: "플레이 기록",
    }.get(table, table)


def _operation_context(operation: BeholderOperation) -> dict[str, Any]:
    return dict(operation.evidence.get("context") or {})


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _override_scope(operation: BeholderOperation, *, target_summary: str | None = None) -> dict[str, Any]:
    """Return the mutation fingerprint a one-shot override may retry."""
    return {
        "operation_kind": operation.kind,
        "actor": operation.actor,
        "target_summary": target_summary,
        "changed_fields": sorted(operation.evidence.get("changed_fields") or []),
        "context": _operation_context(operation),
        "proposed_values_hash": _canonical_hash(_override_proposed_values(operation)),
    }


def _override_proposed_values(operation: BeholderOperation) -> dict[str, Any]:
    proposed = dict(operation.evidence.get("proposed_values") or {})
    if operation.kind == "runtime_stop":
        for volatile in ("end_timestamp", "session_duration", "heartbeat_timestamp"):
            proposed.pop(volatile, None)
    return proposed


def _scope_matches_operation(incident: models.BeholderIncident, operation: BeholderOperation | str) -> bool:
    if isinstance(operation, str):
        return incident.operation_kind == operation
    if incident.operation_kind != operation.kind or incident.actor != operation.actor:
        return False
    scope = (getattr(incident, "resolution_metadata", None) or {}).get("override_scope") or {}
    if not scope:
        return False
    expected_target = scope.get("target_summary")
    if expected_target and expected_target != getattr(incident, "target_summary", None):
        return False
    expected_fields = scope.get("changed_fields") or []
    actual_fields = sorted(operation.evidence.get("changed_fields") or [])
    if expected_fields and expected_fields != actual_fields:
        return False
    actual_context = _operation_context(operation)
    for key, expected in (scope.get("context") or {}).items():
        if key not in actual_context or actual_context.get(key) != expected:
            return False
    expected_hash = scope.get("proposed_values_hash")
    actual_hash = _canonical_hash(_override_proposed_values(operation))
    if expected_hash and expected_hash != actual_hash:
        return False
    return True


def _latest_runtime_heartbeat(db: Session) -> models.AppRuntimeHeartbeat | None:
    try:
        return db.query(models.AppRuntimeHeartbeat).filter(models.AppRuntimeHeartbeat.id == 1).first()
    except OperationalError:
        db.rollback()
        return None


def _has_active_incident(db: Session, operation_kind: str, target_summary: str) -> bool:
    return db.query(models.BeholderIncident).filter(
        models.BeholderIncident.status == STATUS_PENDING,
        models.BeholderIncident.operation_kind == operation_kind,
        models.BeholderIncident.target_summary == target_summary,
    ).first() is not None


def _close_timestamp_from_heartbeat(db: Session, sessions: list[models.ProcessSession]) -> float | None:
    heartbeat = _latest_runtime_heartbeat(db)
    ts = getattr(heartbeat, "last_heartbeat_at", None) if heartbeat else None
    if ts is None:
        return None
    earliest_start = min(float(s.start_timestamp) for s in sessions)
    if float(ts) < earliest_start:
        return None
    return float(ts)


def _current_boot_id() -> str | None:
    try:
        return str(int(psutil.boot_time()))
    except Exception:
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_hhmm(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return False
    hour, minute = (int(part) for part in parts)
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _invalid_settings_values(
    current_settings: models.GlobalSettings,
    update_data: dict[str, Any],
    changed_fields: set[str],
) -> list[str]:
    invalid: list[str] = []

    def proposed(field: str) -> Any:
        if field in update_data:
            return update_data[field]
        return getattr(current_settings, field, None)

    for field, (minimum, maximum, _label) in SETTINGS_RANGE_RULES.items():
        if field not in changed_fields:
            continue
        value = update_data.get(field)
        if not _is_number(value) or float(value) < minimum or float(value) > maximum:
            invalid.append(field)
    for field, (allowed, _label) in SETTINGS_ENUM_RULES.items():
        if field in changed_fields and update_data.get(field) not in allowed:
            invalid.append(field)
    for field in ("sleep_start_time_str", "sleep_end_time_str"):
        if field in changed_fields and not _is_hhmm(update_data.get(field)):
            invalid.append(field)
    if changed_fields & {"sidebar_trigger_y_start", "sidebar_trigger_y_end"}:
        y_start = proposed("sidebar_trigger_y_start")
        y_end = proposed("sidebar_trigger_y_end")
        if _is_number(y_start) and _is_number(y_end) and float(y_start) > float(y_end):
            invalid.append("sidebar_trigger_y_start>sidebar_trigger_y_end")

    return invalid


def _invalid_process_values(
    current_process: models.Process | None,
    update_data: dict[str, Any],
    changed_fields: set[str],
) -> list[str]:
    invalid: list[str] = []

    def proposed(field: str) -> Any:
        if field in update_data:
            return update_data[field]
        return getattr(current_process, field, None) if current_process is not None else None

    if "preferred_launch_type" in changed_fields and update_data.get("preferred_launch_type") not in {"shortcut", "direct", "launcher"}:
        invalid.append("preferred_launch_type")
    if "launch_args" in changed_fields:
        value = str(update_data.get("launch_args") or "")
        if "\n" in value or "\r" in value or "\x00" in value or len(value) > MAX_LAUNCH_ARGS_LENGTH:
            invalid.append("launch_args")
    if "user_cycle_hours" in changed_fields:
        value = update_data.get("user_cycle_hours")
        if not _is_number(value) or float(value) <= 0 or float(value) > 8760:
            invalid.append("user_cycle_hours")
    if "default_volume" in changed_fields:
        value = update_data.get("default_volume")
        if value is not None and (not _is_number(value) or float(value) < 0 or float(value) > 100):
            invalid.append("default_volume")

    for field in ("last_played_timestamp", "stamina_updated_at"):
        if field in changed_fields:
            value = update_data.get(field)
            if value is not None and (not _is_number(value) or float(value) < 0):
                invalid.append(field)

    if "resource_updated_at" in changed_fields:
        value = update_data.get("resource_updated_at")
        if value is not None and (not _is_number(value) or float(value) < 0):
            invalid.append("resource_updated_at")

    if "resource_percent" in changed_fields:
        value = update_data.get("resource_percent")
        if value is not None and (not _is_number(value) or not (0 <= float(value) <= 100)):
            invalid.append("resource_percent")

    for field in ("stamina_current", "stamina_max"):
        if field in changed_fields:
            value = update_data.get(field)
            if value is not None and (not _is_number(value) or float(value) < 0):
                invalid.append(field)

    current = proposed("stamina_current")
    maximum = proposed("stamina_max")
    if {"stamina_current", "stamina_max"} & changed_fields and current is not None and maximum is not None:
        if _is_number(current) and _is_number(maximum) and float(current) > float(maximum):
            invalid.append("stamina_current>stamina_max")
    return invalid


def guard_table_write(db: Session, operation: BeholderOperation, table: str, columns: set[str] | None = None) -> None:
    if table not in operation.allowed_tables:
        if consume_override_token(db, operation.override_token, operation):
            return
        incident = create_incident(
            db,
            severity=SEVERITY_CRITICAL,
            operation=operation,
            target_summary=table,
            suspected_cause="허용된 데이터 경로가 아닌 곳에서 DB 변경을 시도했습니다.",
            current_state_summary="요청 actor가 해당 테이블 변경 권한을 제시하지 않았습니다.",
            proposed_change_summary=f"{table} 테이블 변경 시도",
            risk_score=90,
            risk_factors=["unauthorized_table_write", table],
            safe_recommendation="앱의 정상 설정/편집 화면에서 다시 시도하세요.",
            user_title="앱 데이터 변경 경로를 확인해야 합니다",
            user_summary="정상 화면에서 나온 요청인지 확인되지 않아 저장하지 않았습니다.",
            user_impact="이번 변경은 반영되지 않았고 기존 데이터는 유지됩니다.",
        )
        raise BeholderBlocked(incident)
    if columns:
        allowed = operation.allowed_columns.get(table)
        if allowed is not None and not columns <= allowed:
            disallowed = sorted(columns - allowed)
            if consume_override_token(db, operation.override_token, operation):
                return
            incident = create_incident(
                db,
                severity=SEVERITY_CRITICAL,
                operation=operation,
                target_summary=table,
                suspected_cause="한 화면에서 수정할 수 없는 설정 항목까지 함께 바뀌려 했습니다.",
                current_state_summary=f"허용 컬럼={sorted(allowed)}",
                proposed_change_summary=f"허용되지 않은 컬럼={disallowed}",
                risk_score=92,
                risk_factors=["unauthorized_column_write", *disallowed],
                safe_recommendation="변경을 차단했습니다. 앱의 정상 화면에서 필요한 항목만 다시 저장하세요.",
                user_title=f"{_table_label(table)} 변경 범위가 비정상적으로 넓습니다",
                user_summary=f"현재 요청에서 바꿀 수 없는 {_table_label(table)} 데이터까지 동시에 바뀌려고 했습니다.",
                user_impact="의도하지 않은 덮어쓰기나 데이터 증발을 막기 위해 저장하지 않았습니다.",
            )
            raise BeholderBlocked(incident)


def guard_process_update(
    db: Session,
    current_process: models.Process | None,
    update_data: dict[str, Any],
    operation: BeholderOperation,
    columns: set[str] | None = None,
) -> None:
    changed_fields = set(columns if columns is not None else (operation.evidence.get("changed_fields") or []))
    guard_table_write(db, operation, MANAGED_PROCESSES_TABLE, changed_fields)
    invalid = _invalid_process_values(current_process, update_data, changed_fields)
    if invalid:
        if consume_override_token(db, operation.override_token, operation):
            return
        risk_factors = ["invalid_process_value", *invalid]
        if "stamina_current>stamina_max" in invalid:
            risk_factors.append("invalid_stamina_range")
        incident = create_incident(
            db,
            severity=SEVERITY_CRITICAL,
            operation=operation,
            target_summary=f"process_id={getattr(current_process, 'id', None) or (operation.evidence.get('context') or {}).get('process_id', 'new')}",
            suspected_cause="게임 항목 또는 런타임 상태에 저장될 값이 정상 범위를 벗어났습니다.",
            current_state_summary=(
                f"현재 값: cycle={getattr(current_process, 'user_cycle_hours', None)}, "
                f"volume={getattr(current_process, 'default_volume', None)}, "
                f"stamina={getattr(current_process, 'stamina_current', None)}/{getattr(current_process, 'stamina_max', None)}"
            ),
            proposed_change_summary=f"비정상 후보={invalid}, 요청 값={{{', '.join(f'{k}: {update_data.get(k)!r}' for k in sorted(changed_fields & set(update_data)))}}}",
            risk_score=91,
            risk_factors=risk_factors,
            safe_recommendation="저장을 차단했습니다. 게임 편집/스태미나 갱신 값을 정상 범위로 다시 입력하세요.",
            user_title="게임 데이터 값이 안전하지 않습니다",
            user_summary="저장하려는 게임 설정이나 스태미나 값 중 정상 범위를 벗어난 항목이 있습니다.",
            user_impact="그대로 저장하면 진행률, 알림, 플레이 상태 표시가 잘못 계산될 수 있어 기존 데이터를 유지했습니다.",
            recommended_action="deny",
            available_actions=[
                {"id": "deny", "label": "차단 유지", "description": "비정상 값을 저장하지 않고 기존 게임 데이터를 유지합니다.", "recommended": True},
                {"id": "allow_once", "label": "이번 한 번 허용", "description": "외부 도구로 복구 중인 특수 상황이라면 한 번만 허용합니다.", "danger": True},
            ],
        )
        raise BeholderBlocked(incident)


def guard_process_delete(db: Session, process: models.Process, operation: BeholderOperation) -> None:
    guard_table_write(db, operation, MANAGED_PROCESSES_TABLE, {"id"})
    open_sessions = db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == process.id,
        models.ProcessSession.end_timestamp.is_(None),
    ).all()
    if not open_sessions:
        return
    if consume_override_token(db, operation.override_token, operation):
        return
    context = _operation_context(operation)
    context.update({
        "process_id": process.id,
        "process_name": process.name,
        "open_session_ids": [session.id for session in open_sessions],
        "actor": operation.actor,
    })
    incident = create_incident(
        db,
        severity=SEVERITY_WARNING,
        operation=operation,
        target_summary=f"process_id={process.id}",
        suspected_cause="실행 중으로 기록된 세션이 남아 있는 게임 항목을 삭제하려 했습니다.",
        current_state_summary=f"열린 세션 {len(open_sessions)}건이 존재합니다: {[session.id for session in open_sessions]}",
        proposed_change_summary="게임 항목 삭제 및 해당 항목으로 접근 가능한 기록 연결 상실 가능",
        risk_score=72,
        risk_factors=["delete_process_with_open_sessions", "runtime_history_orphan_risk"],
        safe_recommendation="먼저 열린 세션을 닫은 뒤 삭제하거나, 비홀더의 정리 후 삭제 액션을 선택하세요.",
        user_title="플레이 기록이 열린 게임을 삭제하려고 했습니다",
        user_summary="이 게임의 플레이 기록이 아직 종료되지 않았습니다. 그대로 삭제하면 기록 해석이 어려워질 수 있습니다.",
        user_impact="게임 항목 삭제는 보류되었고 기존 데이터는 유지됩니다.",
        recommended_action="close_sessions_and_delete_process",
        available_actions=[
            {"id": "close_sessions_and_delete_process", "label": "기록 닫고 게임 삭제", "description": "열린 기록을 현재 시각으로 종료한 뒤 게임 항목을 삭제합니다.", "recommended": True},
            {"id": "deny", "label": "차단 유지", "description": "삭제하지 않고 현재 상태를 유지합니다."},
            {"id": "allow_once", "label": "이번 한 번 허용", "description": "정말 의도한 삭제라면 한 번만 허용합니다.", "danger": True},
        ],
        resolution_metadata={"action_context": context},
    )
    raise BeholderBlocked(incident)


def guard_process_session_update(db: Session, session: models.ProcessSession, columns: set[str], operation: BeholderOperation) -> None:
    guard_table_write(db, operation, PROCESS_SESSIONS_TABLE, columns)
    if "stamina_at_end" in columns:
        proposed_values = operation.evidence.get("proposed_values") or {}
        value = proposed_values.get("stamina_at_end", getattr(session, "stamina_at_end", None))
        if value is not None and value < 0:
            if consume_override_token(db, operation.override_token, operation):
                return
            incident = create_incident(
                db,
                severity=SEVERITY_CRITICAL,
                operation=operation,
                target_summary=f"session_id={session.id}",
                suspected_cause="세션 스태미나 값이 음수로 저장되려 했습니다.",
                current_state_summary=f"현재 stamina_at_end={value}",
                proposed_change_summary="음수 스태미나 저장",
                risk_score=88,
                risk_factors=["invalid_negative_stamina"],
                safe_recommendation="저장을 차단했습니다. 정상 범위의 값을 다시 저장하세요.",
                user_title="플레이 기록 값이 비정상입니다",
                user_summary="저장하려는 스태미나 값이 음수라 기록을 망칠 수 있습니다.",
                user_impact="이번 변경은 반영되지 않았고 기존 기록은 유지됩니다.",
            )
            raise BeholderBlocked(incident)
    if "resource_percent_at_end" in columns:
        proposed_values = operation.evidence.get("proposed_values") or {}
        value = proposed_values.get("resource_percent_at_end", getattr(session, "resource_percent_at_end", None))
        try:
            percent = None if value is None else float(value)
        except (TypeError, ValueError):
            percent = None
        if value is not None and (percent is None or not math.isfinite(percent) or percent < 0.0 or percent > 100.0):
            if consume_override_token(db, operation.override_token, operation):
                return
            incident = create_incident(
                db,
                severity=SEVERITY_CRITICAL,
                operation=operation,
                target_summary=f"session_id={session.id}",
                suspected_cause="세션 리소스 백분율이 정상 범위를 벗어나 저장되려 했습니다.",
                current_state_summary=f"현재 resource_percent_at_end={value}",
                proposed_change_summary="비정상 리소스 백분율 저장",
                risk_score=88,
                risk_factors=["invalid_resource_percent"],
                safe_recommendation="저장을 차단했습니다. 0~100 범위의 값을 다시 저장하세요.",
                user_title="플레이 기록 리소스 값이 비정상입니다",
                user_summary="저장하려는 리소스 백분율이 0~100 범위를 벗어나 기록을 망칠 수 있습니다.",
                user_impact="이번 변경은 반영되지 않았고 기존 기록은 유지됩니다.",
            )
            raise BeholderBlocked(incident)

def guard_settings_update(db: Session, current_settings: models.GlobalSettings, update_data: dict[str, Any], operation: BeholderOperation) -> None:
    changed_fields = set(operation.evidence.get("changed_fields") or [])
    if not changed_fields:
        return
    guard_table_write(db, operation, GLOBAL_SETTINGS_TABLE, changed_fields)

    invalid_values = _invalid_settings_values(current_settings, update_data, changed_fields)
    if invalid_values:
        if consume_override_token(db, operation.override_token, operation):
            return
        relation_invalid = any(">" in item for item in invalid_values)
        incident = create_incident(
            db,
            severity=SEVERITY_CRITICAL,
            operation=operation,
            target_summary="global_settings",
            suspected_cause="설정 화면에서 저장할 수 없는 범위 또는 조합의 값이 들어왔습니다.",
            current_state_summary=f"현재 변경 대상: {sorted(changed_fields)}",
            proposed_change_summary=f"비정상 설정 값: {invalid_values}",
            risk_score=91,
            risk_factors=[
                "invalid_setting_value",
                *invalid_values,
                *(["invalid_setting_relation"] if relation_invalid else []),
            ],
            safe_recommendation="저장을 차단했습니다. 설정 창에서 허용 범위 안의 값으로 다시 저장하세요.",
            user_title="설정 값이 안전한 범위를 벗어났습니다",
            user_summary="저장하려는 설정 중 앱이 정상적으로 해석할 수 없는 값이 있습니다.",
            user_impact="그대로 저장하면 사이드바 위치, 알림 시각, 캡처/녹화 동작이 비정상적으로 계산될 수 있어 기존 설정을 유지했습니다.",
            recommended_action="deny",
            available_actions=[
                {"id": "deny", "label": "차단 유지", "description": "비정상 설정을 저장하지 않고 기존 설정을 유지합니다.", "recommended": True},
                {"id": "allow_once", "label": "이번 한 번 허용", "description": "백업 복구 등 의도한 특수 작업일 때만 한 번 허용합니다.", "danger": True},
            ],
        )
        raise BeholderBlocked(incident)

    defaults = _schema_defaults()
    defaulted = [field for field in changed_fields if field in defaults and update_data.get(field) == defaults[field]]
    if len(changed_fields) >= 8 and len(defaulted) >= max(6, int(len(changed_fields) * 0.6)):
        if consume_override_token(db, operation.override_token, operation):
            return
        incident = create_incident(
            db,
            severity=SEVERITY_CRITICAL,
            operation=operation,
            target_summary="global_settings",
            suspected_cause="많은 설정이 동시에 기본값으로 되돌아가려 했습니다.",
            current_state_summary=f"변경 대상 {len(changed_fields)}개: {sorted(changed_fields)}",
            proposed_change_summary=f"그중 기본값 회귀 {len(defaulted)}개: {sorted(defaulted)}",
            risk_score=96,
            risk_factors=["bulk_settings_default_regression", *sorted(defaulted)],
            safe_recommendation="저장을 차단했습니다. 설정 백업 또는 DB 백업에서 복구 가능성을 먼저 확인하세요.",
            user_title="설정 초기화로 보이는 변경을 막았습니다",
            user_summary="여러 설정이 한꺼번에 초기값으로 돌아가려고 했습니다.",
            user_impact="저장했다면 사이드바/스크린샷/녹화 같은 개인 설정이 사라질 수 있었습니다.",
            recommended_action="deny",
            available_actions=[
                {"id": "deny", "label": "차단 유지", "description": "현재 저장된 설정을 유지합니다.", "recommended": True},
                {"id": "quarantine", "label": "나중에 검토", "description": "사건만 보류 상태로 표시합니다."},
                {"id": "allow_once", "label": "이번 한 번 허용", "description": "정말 의도한 초기화라면 1회만 허용합니다.", "danger": True},
            ],
        )
        raise BeholderBlocked(incident)

    personalized_defaulted = []
    for field in sorted(changed_fields & PERSONALIZED_SETTINGS_FIELDS):
        if field not in defaults:
            continue
        current = getattr(current_settings, field, None)
        proposed = update_data.get(field)
        default = defaults[field]
        if current != default and proposed == default:
            personalized_defaulted.append(field)
    if personalized_defaulted:
        if consume_override_token(db, operation.override_token, operation):
            return
        incident = create_incident(
            db,
            severity=SEVERITY_CRITICAL,
            operation=operation,
            target_summary="global_settings",
            suspected_cause="개인화 설정 일부가 기본값으로 되돌아가려 했습니다.",
            current_state_summary=f"보존해야 할 개인화 설정: {personalized_defaulted}",
            proposed_change_summary=f"기본값 회귀 필드: {personalized_defaulted}",
            risk_score=90,
            risk_factors=["personalized_settings_default_regression", *personalized_defaulted],
            safe_recommendation="저장을 차단했습니다. 의도한 초기화라면 Beholder에서 이번 한 번 허용을 선택하세요.",
            user_title="개인 설정이 초기화될 수 있어 저장하지 않았습니다",
            user_summary="사이드바/스크린샷/OBS 같은 개인화 설정 일부가 기본값으로 돌아가려고 했습니다.",
            user_impact="저장했다면 직접 지정한 경로, 캡처 방식, 사이드바 표시 방식 등이 사라질 수 있었습니다.",
            recommended_action="deny",
            available_actions=[
                {"id": "deny", "label": "차단 유지", "description": "현재 저장된 설정을 유지합니다.", "recommended": True},
                {"id": "allow_once", "label": "이번 한 번 허용", "description": "정말 의도한 초기화라면 한 번만 허용합니다.", "danger": True},
            ],
        )
        raise BeholderBlocked(incident)


def guard_session_start(db: Session, session_data: Any, operation: BeholderOperation) -> None:
    guard_table_write(db, operation, PROCESS_SESSIONS_TABLE, {"process_id", "process_name", "start_timestamp"})
    if operation.actor not in {"process_monitor", "legacy_process_monitor"}:
        incident = create_incident(
            db,
            severity=SEVERITY_CRITICAL,
            operation=operation,
            target_summary=f"process_id={session_data.process_id}",
            suspected_cause="런타임 실행 감지기가 아닌 경로에서 플레이 세션을 시작하려 했습니다.",
            current_state_summary=f"actor={operation.actor}",
            proposed_change_summary="새 open session 생성",
            risk_score=86,
            risk_factors=["actor_not_runtime_owner"],
            safe_recommendation="앱의 정상 실행 감지 경로에서 게임을 시작한 뒤 다시 시도하세요.",
            user_title="플레이 기록 시작 경로가 안전하지 않습니다",
            user_summary="게임 실행 감지기가 아닌 요청이 플레이 기록을 만들려고 했습니다.",
            user_impact="잘못된 기록 생성을 막기 위해 새 플레이 기록은 저장하지 않았습니다.",
            recommended_action="deny",
            available_actions=[
                {"id": "deny", "label": "차단 유지", "description": "새 플레이 기록을 만들지 않습니다.", "recommended": True},
            ],
        )
        raise BeholderBlocked(incident)
    active = db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == session_data.process_id,
        models.ProcessSession.end_timestamp.is_(None),
    ).all()
    live_open = [s for s in active if _is_open_session(s)]
    if live_open:
        if consume_override_token(db, operation.override_token, operation):
            return
        now = time.time()
        legacy_open = [s for s in live_open if _is_legacy_open_session(s)]
        old_legacy = [s for s in legacy_open if now - float(s.start_timestamp) > LEGACY_OPEN_SESSION_SECONDS]
        context = dict(_operation_context(operation))
        current_process_running = bool(context.get("current_process_running", True))
        close_at = _close_timestamp_from_heartbeat(db, live_open)
        recommended_action = "continue_existing_session"
        available_actions = [
            {"id": "continue_existing_session", "label": "이전 세션 이어가기", "description": "직전 기록을 현재 실행 중인 게임 기록으로 계속 사용합니다.", "recommended": True},
            {"id": "close_previous_and_start_new", "label": "이전 세션 닫고 새로 시작", "description": "이전 기록을 지금 시점에 종료하고 새 기록을 만듭니다."},
            {"id": "deny", "label": "차단 유지", "description": "새 세션을 만들지 않습니다."},
            {"id": "allow_once", "label": "이번 한 번 허용", "description": "중복 세션 생성을 한 번만 허용합니다.", "danger": True},
        ]
        user_summary = "앱이 재시작되면서 같은 게임의 새 플레이 기록을 만들려 했지만, 직전 기록이 아직 종료되지 않았습니다."
        safe_recommendation = "기존 세션을 이어가거나, 기존 세션을 닫고 새 세션을 시작할지 선택하세요."
        risk_factors = ["duplicate_open_session", "runtime_state_ambiguous"]
        if not current_process_running and close_at is not None:
            recommended_action = "close_at_last_app_heartbeat"
            available_actions = [
                {"id": "close_at_last_app_heartbeat", "label": "마지막 앱 실행 시각에 종료", "description": "마지막으로 앱이 살아있던 시각에 게임도 종료된 것으로 기록합니다.", "recommended": True},
                {"id": "abandon_open_sessions", "label": "복구 불가 기록 버리기", "description": "열린 기록을 0초 abandoned 기록으로 정리합니다."},
                {"id": "deny", "label": "차단 유지", "description": "아무 기록도 바꾸지 않습니다."},
            ]
            user_summary = "현재 게임은 실행 중이 아니며, 앱의 마지막 생존 시각 이후 기록이 닫히지 않았습니다."
            safe_recommendation = "마지막 앱 생존 시각에 플레이가 끝난 것으로 닫는 것이 가장 안전합니다."
            risk_factors = ["open_session_after_app_restart", "game_not_running", "last_heartbeat_available"]
        elif old_legacy and len(old_legacy) == len(live_open):
            recommended_action = "abandon_legacy_and_start_new"
            available_actions = [
                {"id": "abandon_legacy_and_start_new", "label": "복구 불가 기록 버리고 새로 시작", "description": "오래된 열린 기록은 abandoned로 정리하고 현재 실행 기록을 새로 만듭니다.", "recommended": True},
                {"id": "continue_existing_session", "label": "가장 최근 기록 이어가기", "description": "오래된 기록 중 가장 최근 기록을 현재 세션으로 사용합니다."},
                {"id": "deny", "label": "차단 유지", "description": "새 세션을 만들지 않습니다."},
            ]
            user_summary = "오래전에 닫히지 않은 기록만 남아 있어 현재 실행과 이어 붙이면 플레이 시간이 왜곡될 수 있습니다."
            safe_recommendation = "복구 불가능한 오래된 열린 기록을 버리고 현재 실행을 새 기록으로 시작하세요."
            risk_factors = ["duplicate_legacy_open_session", "legacy_open_session_stale"]
        context = {
            **context,
            "process_id": session_data.process_id,
            "process_name": session_data.process_name,
            "requested_start_timestamp": session_data.start_timestamp,
            "requested_user_preset_id": getattr(session_data, "user_preset_id", None),
            "actor": operation.actor,
            "open_session_ids": [s.id for s in live_open],
            "close_timestamp": close_at,
        }
        incident = create_incident(
            db,
            severity=SEVERITY_WARNING,
            operation=operation,
            target_summary=f"process_id={session_data.process_id}",
            suspected_cause="이미 열린 세션이 있는 상태에서 새 세션을 만들려는 시도입니다.",
            current_state_summary=f"열린 세션 {len(live_open)}건이 존재합니다: {[s.id for s in live_open]}",
            proposed_change_summary="동일 게임에 새 open session 1건 추가",
            risk_score=65,
            risk_factors=risk_factors,
            safe_recommendation=safe_recommendation,
            user_title="이전 플레이 기록이 아직 열려 있습니다",
            user_summary=user_summary,
            user_impact="그대로 새 기록을 만들면 플레이 시간이 둘로 갈라지거나 중복 집계될 수 있습니다.",
            recommended_action=recommended_action,
            available_actions=available_actions,
            resolution_metadata={"action_context": context},
        )
        raise BeholderBlocked(incident)


def guard_session_end(db: Session, session: models.ProcessSession, end_timestamp: float, operation: BeholderOperation) -> None:
    guard_table_write(db, operation, PROCESS_SESSIONS_TABLE, set(operation.evidence.get("changed_fields") or ["end_timestamp"]))

    start = float(session.start_timestamp)
    duration = float(end_timestamp) - start
    status = session_status_for(session)
    owner = getattr(session, "session_owner", None) or "unknown"
    heartbeat = getattr(session, "heartbeat_timestamp", None)
    heartbeat_gap = None if heartbeat is None else max(0.0, float(end_timestamp) - float(heartbeat))

    risk_factors: list[str] = []
    risk_score = 0

    if duration < 0:
        risk_factors.append("negative_duration")
        risk_score += 100
    if status in {"abandoned", "quarantined", "closed"}:
        risk_factors.append(f"invalid_current_status:{status}")
        risk_score += 90
    if owner == "unknown" and duration > 24 * 60 * 60:
        risk_factors.append("unknown_owner_long_session")
        risk_score += 35
    if duration > MAX_UNEVIDENCED_SESSION_SECONDS:
        risk_factors.append("extreme_duration_without_sufficient_evidence")
        risk_score += 70
    if heartbeat_gap is not None and heartbeat_gap > MAX_HEARTBEAT_GAP_SECONDS and duration > 24 * 60 * 60:
        risk_factors.append("stale_heartbeat")
        risk_score += 35
    if operation.actor not in {"process_monitor", "legacy_process_monitor"}:
        risk_factors.append("actor_not_runtime_owner")
        risk_score += 80

    if risk_score >= 80:
        if consume_override_token(db, operation.override_token, operation):
            return
        incident = create_incident(
            db,
            severity=SEVERITY_CRITICAL,
            operation=operation,
            target_summary=f"session_id={session.id}, process_id={session.process_id}",
            suspected_cause="세션 종료 기록이 현재 실행 근거와 맞지 않거나 DB 상태를 급격히 바꿀 수 있습니다.",
            current_state_summary=(
                f"현재 상태={status}, owner={owner}, start={start:.0f}, "
                f"heartbeat={heartbeat or '없음'}"
            ),
            proposed_change_summary=(
                f"end_timestamp={end_timestamp:.0f}, session_duration={duration:.0f}초 "
                f"({duration / 3600:.1f}시간)로 저장 시도"
            ),
            risk_score=min(100, risk_score),
            risk_factors=risk_factors,
            safe_recommendation="이번 변경은 저장하지 않았습니다. 백업/세션 상태를 확인한 뒤 수동으로 결정하세요.",
            user_title="플레이 기록 종료 시간이 안전하지 않습니다",
            user_summary="현재 기록 상태와 종료 요청이 맞지 않아 플레이 시간이 크게 왜곡될 수 있습니다.",
            user_impact="저장하면 과도하게 긴 기록이나 음수 기록이 생길 수 있어 차단했습니다.",
        )
        raise BeholderBlocked(incident)


def create_open_session_recovery_incidents(db: Session, *, running_process_ids: set[str]) -> list[models.BeholderIncident]:
    """Create user-actionable incidents for open sessions after app restart.

    This is intentionally non-mutating except for incident creation: the user's
    chosen Beholder action performs any session close/abandon/merge.
    """

    open_sessions = db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.is_(None)).all()
    grouped: dict[str, list[models.ProcessSession]] = {}
    for session in open_sessions:
        if not _is_open_session(session):
            continue
        grouped.setdefault(session.process_id, []).append(session)

    incidents: list[models.BeholderIncident] = []
    for process_id, sessions in grouped.items():
        if process_id in running_process_ids:
            continue
        target = f"process_id={process_id}"
        if _has_active_incident(db, "runtime_recovery", target):
            continue
        sessions = sorted(sessions, key=lambda item: float(item.start_timestamp), reverse=True)
        close_at = _close_timestamp_from_heartbeat(db, sessions)
        heartbeat = _latest_runtime_heartbeat(db)
        boot_changed = bool(heartbeat and heartbeat.boot_id and _current_boot_id() and heartbeat.boot_id != _current_boot_id())
        context = {
            "process_id": process_id,
            "process_name": sessions[0].process_name,
            "open_session_ids": [s.id for s in sessions],
            "actor": "runtime_recovery",
            "close_timestamp": close_at,
            "previous_boot_id": getattr(heartbeat, "boot_id", None) if heartbeat else None,
            "current_boot_id": _current_boot_id(),
        }
        legacy = [s for s in sessions if _is_legacy_open_session(s)]
        if close_at is not None:
            recommended_action = "close_at_last_app_heartbeat"
            actions = [
                {"id": "close_at_last_app_heartbeat", "label": "마지막 앱 실행 시각에 종료", "description": "마지막으로 앱이 살아있던 시각에 게임도 종료된 것으로 기록합니다.", "recommended": True},
                {"id": "abandon_open_sessions", "label": "복구 불가 기록 버리기", "description": "열린 기록을 0초 abandoned 기록으로 정리합니다."},
                {"id": "decide_later", "label": "나중에 결정", "description": "이번에는 기록을 바꾸지 않고 안내를 다음 실행까지 보류합니다."},
            ]
            summary = "현재 게임은 실행 중이 아니며, 앱이 꺼질 때 닫히지 않은 플레이 기록이 남아 있습니다."
            recommendation = "마지막 앱 생존 시각에 플레이가 끝난 것으로 닫는 것이 가장 안전합니다."
            risk_factors = ["open_session_after_restart", "game_not_running", "last_heartbeat_available"]
            if boot_changed:
                risk_factors.append("pc_reboot_detected")
        else:
            recommended_action = "abandon_open_sessions"
            actions = [
                {"id": "abandon_open_sessions", "label": "복구 불가 기록 버리기", "description": "마지막 앱 생존 시각을 알 수 없는 열린 기록을 abandoned로 정리합니다.", "recommended": True},
                {"id": "decide_later", "label": "나중에 결정", "description": "이번에는 기록을 바꾸지 않고 안내를 다음 실행까지 보류합니다."},
            ]
            summary = "마지막 앱 생존 시각을 알 수 없는 오래된 열린 플레이 기록이 남아 있습니다."
            recommendation = "정확한 종료 시각을 복구할 수 없으므로 기록을 abandoned로 정리하는 것이 안전합니다."
            risk_factors = ["legacy_open_session_without_heartbeat"]
            if legacy:
                risk_factors.append("legacy_session_metadata_missing")

        incident = create_incident(
            db,
            severity=SEVERITY_WARNING,
            operation=BeholderOperation(kind="runtime_recovery", actor="runtime_recovery"),
            target_summary=target,
            suspected_cause="앱 재시작 후 현재 실행 중이 아닌 게임에 열린 세션이 남아 있습니다.",
            current_state_summary=f"열린 세션 {len(sessions)}건: {[s.id for s in sessions]}",
            proposed_change_summary="사용자 선택에 따라 열린 세션을 닫거나 복구 불가 기록으로 정리",
            risk_score=70,
            risk_factors=risk_factors,
            safe_recommendation=recommendation,
            user_title="닫히지 않은 플레이 기록을 정리해야 합니다",
            user_summary=summary,
            user_impact="정리하지 않으면 다음 실행 때 플레이 시간이 중복되거나 충돌 안내가 반복될 수 있습니다.",
            recommended_action=recommended_action,
            available_actions=actions,
            resolution_metadata={"action_context": context},
        )
        incidents.append(incident)
    return incidents


def mark_incident(
    db: Session,
    incident_id: int,
    status: str,
    resolution_metadata: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> models.BeholderIncident | None:
    incident = db.query(models.BeholderIncident).filter(models.BeholderIncident.id == incident_id).first()
    if not incident:
        return None
    incident.status = status
    incident.resolved_at = time.time()
    if resolution_metadata:
        current = getattr(incident, "resolution_metadata", None) or {}
        current.update(resolution_metadata)
        incident.resolution_metadata = current
    db.add(incident)
    if commit:
        db.commit()
        db.refresh(incident)
    return incident


def resolve_incident_action(db: Session, incident: models.BeholderIncident, action: str) -> dict[str, Any]:
    if incident.status != STATUS_PENDING:
        raise ValueError("이미 처리된 Beholder 안내입니다. 최신 상태를 새로고침해 주세요.")
    if action not in _available_action_ids(incident):
        raise ValueError("이 Beholder 안내에서 제공하지 않은 결정입니다. 최신 안내를 새로고침해 주세요.")
    if action == "allow_once":
        token = issue_override_token(db, incident)
        return {"incident": incident_to_dict(incident), "override_token": token}
    if action == "deny":
        return {"incident": incident_to_dict(mark_incident(db, incident.id, STATUS_DENIED))}
    if action == "quarantine":
        return {"incident": incident_to_dict(mark_incident(db, incident.id, STATUS_QUARANTINED))}
    if action == "decide_later":
        return {"incident": incident_to_dict(incident), "action": "decide_later"}
    if action == "continue_existing_session":
        return _continue_existing_session(db, incident)
    if action == "close_previous_and_start_new":
        return _close_previous_and_start_new(db, incident)
    if action == "close_sessions_and_delete_process":
        return _close_sessions_and_delete_process(db, incident)
    if action == "close_at_last_app_heartbeat":
        return _close_at_last_app_heartbeat(db, incident)
    if action == "abandon_open_sessions":
        return _abandon_open_sessions(db, incident)
    if action == "abandon_legacy_and_start_new":
        return _abandon_legacy_and_start_new(db, incident)
    raise ValueError("지원하지 않는 Beholder 결정입니다.")


def _context_for(incident: models.BeholderIncident) -> dict[str, Any]:
    meta = getattr(incident, "resolution_metadata", None) or {}
    return dict(meta.get("action_context") or {})


def _open_sessions_for_context(db: Session, context: dict[str, Any]) -> list[models.ProcessSession]:
    ids = context.get("open_session_ids") or []
    process_id = context.get("process_id")
    if not ids and not process_id:
        return []
    query = db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.is_(None))
    if ids:
        query = query.filter(models.ProcessSession.id.in_(ids))
    elif process_id:
        query = query.filter(models.ProcessSession.process_id == process_id)
    return query.order_by(models.ProcessSession.start_timestamp.desc()).all()


def _snapshot_sessions_or_raise(
    sessions: list[models.ProcessSession],
    *,
    reason: str,
) -> list[str]:
    if not sessions:
        return []
    from src.data.crud import backup_model_snapshot
    paths: list[str] = []
    for session in sessions:
        snapshot_path = backup_model_snapshot(session, table=PROCESS_SESSIONS_TABLE, reason=reason)
        if not snapshot_path:
            raise ValueError("플레이 기록 변경 전 백업을 만들지 못했습니다. 데이터 보존을 위해 복구 작업을 중단했습니다.")
        paths.append(snapshot_path)
    return paths


def _continue_existing_session(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    open_sessions = _open_sessions_for_context(db, context)
    if not open_sessions:
        raise ValueError("이어갈 수 있는 열린 세션을 찾지 못했습니다.")
    session = open_sessions[0]
    continued_snapshot_paths = _snapshot_sessions_or_raise([session], reason="beholder_continue_existing_session")
    now = time.time()
    session.session_status = "open"
    session.session_owner = context.get("actor") or incident.actor
    session.heartbeat_timestamp = now
    session.lease_token = secrets.token_urlsafe(16)
    flags = session.guard_flags or {}
    if not isinstance(flags, dict):
        flags = {"legacy_guard_flags": flags}
    flags.update({"continued_after_restart": True, "continued_incident_id": incident.id, "continued_at": now})
    session.guard_flags = flags
    other_sessions = open_sessions[1:]
    abandoned_ids = _abandon_sessions(
        db,
        other_sessions,
        reason="beholder_continue_existing_cleanup",
        incident_id=incident.id,
    ) if other_sessions else []
    updated = mark_incident(
        db,
        incident.id,
        STATUS_RESOLVED,
        {
            "selected_action": "continue_existing_session",
            "continued_session_id": session.id,
            "abandoned_session_ids": abandoned_ids,
            "continued_snapshot_paths": continued_snapshot_paths,
        },
        commit=False,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"incident": incident_to_dict(updated), "session_id": session.id, "abandoned_session_ids": abandoned_ids, "action": "continue_existing_session"}


def _close_previous_and_start_new(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    now = time.time()
    split_at = float(context.get("requested_start_timestamp") or now)
    open_sessions = _open_sessions_for_context(db, context)
    snapshot_paths = _snapshot_sessions_or_raise(open_sessions, reason="beholder_close_previous_and_start_new")
    for session in open_sessions:
        end_ts = max(float(session.start_timestamp), split_at)
        session.end_timestamp = end_ts
        session.session_duration = max(0.0, end_ts - float(session.start_timestamp))
        session.session_status = "closed"
        session.close_reason = "beholder_close_previous_and_start_new"
        session.heartbeat_timestamp = end_ts
        db.add(session)
    new_session = models.ProcessSession(
        process_id=context.get("process_id"),
        process_name=context.get("process_name") or context.get("process_id") or "Unknown",
        start_timestamp=split_at,
        user_preset_id=context.get("requested_user_preset_id"),
        session_owner=context.get("actor") or incident.actor,
        session_status="open",
        heartbeat_timestamp=now,
        lease_token=secrets.token_urlsafe(16),
        guard_flags={"created_by_beholder_resolution": True, "incident_id": incident.id},
    )
    db.add(new_session)
    db.flush()
    updated = mark_incident(
        db,
        incident.id,
        STATUS_RESOLVED,
        {
            "selected_action": "close_previous_and_start_new",
            "new_session_id": new_session.id,
            "session_snapshot_paths": snapshot_paths,
        },
        commit=False,
    )
    db.commit()
    db.refresh(new_session)
    return {"incident": incident_to_dict(updated), "session_id": new_session.id, "action": "close_previous_and_start_new"}


def _close_at_last_app_heartbeat(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    open_sessions = _open_sessions_for_context(db, context)
    close_ts = context.get("close_timestamp") or _close_timestamp_from_heartbeat(db, open_sessions)
    if close_ts is None:
        raise ValueError("마지막 앱 생존 시각을 찾지 못했습니다.")
    snapshot_paths = _snapshot_sessions_or_raise(open_sessions, reason="beholder_close_at_last_app_heartbeat")
    closed_ids: list[int] = []
    for session in open_sessions:
        end_ts = max(float(session.start_timestamp), float(close_ts))
        session.end_timestamp = end_ts
        session.session_duration = max(0.0, end_ts - float(session.start_timestamp))
        session.session_status = "closed"
        session.close_reason = "beholder_power_loss_close_at_last_heartbeat"
        session.heartbeat_timestamp = end_ts
        db.add(session)
        closed_ids.append(session.id)
    updated = mark_incident(
        db,
        incident.id,
        STATUS_RESOLVED,
        {
            "selected_action": "close_at_last_app_heartbeat",
            "closed_session_ids": closed_ids,
            "close_timestamp": close_ts,
            "session_snapshot_paths": snapshot_paths,
        },
        commit=False,
    )
    db.commit()
    return {"incident": incident_to_dict(updated), "closed_session_ids": closed_ids, "action": "close_at_last_app_heartbeat"}


def _abandon_sessions(db: Session, sessions: list[models.ProcessSession], *, reason: str, incident_id: int) -> list[int]:
    abandoned_ids: list[int] = []
    _snapshot_sessions_or_raise(sessions, reason=reason)
    now = time.time()
    for session in sessions:
        end_ts = float(session.start_timestamp)
        session.end_timestamp = end_ts
        session.session_duration = 0.0
        session.session_status = "abandoned"
        session.close_reason = reason
        session.heartbeat_timestamp = now
        flags = session.guard_flags or {}
        if not isinstance(flags, dict):
            flags = {"legacy_guard_flags": flags}
        flags.update({"abandoned_by_beholder": True, "abandoned_incident_id": incident_id, "abandoned_at": now})
        session.guard_flags = flags
        db.add(session)
        abandoned_ids.append(session.id)
    return abandoned_ids


def _abandon_open_sessions(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    open_sessions = _open_sessions_for_context(db, _context_for(incident))
    if not open_sessions:
        raise ValueError("정리할 열린 세션을 찾지 못했습니다.")
    abandoned_ids = _abandon_sessions(
        db,
        open_sessions,
        reason="beholder_abandoned_legacy_open_session",
        incident_id=incident.id,
    )
    updated = mark_incident(db, incident.id, STATUS_RESOLVED, {"selected_action": "abandon_open_sessions", "abandoned_session_ids": abandoned_ids}, commit=False)
    db.commit()
    return {"incident": incident_to_dict(updated), "abandoned_session_ids": abandoned_ids, "action": "abandon_open_sessions"}


def _abandon_legacy_and_start_new(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    open_sessions = _open_sessions_for_context(db, context)
    abandoned_ids = _abandon_sessions(
        db,
        open_sessions,
        reason="beholder_abandoned_legacy_before_new_session",
        incident_id=incident.id,
    )
    now = time.time()
    new_session = models.ProcessSession(
        process_id=context.get("process_id"),
        process_name=context.get("process_name") or context.get("process_id") or "Unknown",
        start_timestamp=context.get("requested_start_timestamp") or now,
        user_preset_id=context.get("requested_user_preset_id"),
        session_owner=context.get("actor") or incident.actor,
        session_status="open",
        heartbeat_timestamp=now,
        lease_token=secrets.token_urlsafe(16),
        guard_flags={"created_by_beholder_resolution": True, "incident_id": incident.id, "abandoned_session_ids": abandoned_ids},
    )
    db.add(new_session)
    db.flush()
    updated = mark_incident(
        db,
        incident.id,
        STATUS_RESOLVED,
        {"selected_action": "abandon_legacy_and_start_new", "new_session_id": new_session.id, "abandoned_session_ids": abandoned_ids},
        commit=False,
    )
    db.commit()
    db.refresh(new_session)
    return {
        "incident": incident_to_dict(updated),
        "session_id": new_session.id,
        "abandoned_session_ids": abandoned_ids,
        "action": "abandon_legacy_and_start_new",
    }


def _close_sessions_and_delete_process(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    process_id = context.get("process_id")
    if not process_id:
        raise ValueError("삭제할 게임 항목 정보를 찾지 못했습니다.")
    now = time.time()
    open_sessions = _open_sessions_for_context(db, context)
    from src.data.crud import backup_model_snapshot
    session_snapshot_paths: list[str] = []
    for session in open_sessions:
        snapshot_path = backup_model_snapshot(session, table=PROCESS_SESSIONS_TABLE, reason="beholder_close_sessions_and_delete_process")
        if not snapshot_path:
            raise ValueError("삭제 전 플레이 기록 백업을 만들지 못했습니다. 데이터 보존을 위해 삭제를 중단했습니다.")
        session_snapshot_paths.append(snapshot_path)
    for session in open_sessions:
        session.end_timestamp = now
        session.session_duration = max(0.0, now - float(session.start_timestamp))
        session.session_status = "closed"
        session.close_reason = "beholder_close_before_process_delete"
        session.heartbeat_timestamp = now
        db.add(session)
    process = db.query(models.Process).filter(models.Process.id == process_id).first()
    if process is None:
        raise ValueError("삭제할 게임 항목을 찾지 못했습니다.")
    process_snapshot_path = backup_model_snapshot(process, table=MANAGED_PROCESSES_TABLE, reason="beholder_close_sessions_and_delete_process")
    if not process_snapshot_path:
        raise ValueError("삭제 전 게임 항목 백업을 만들지 못했습니다. 데이터 보존을 위해 삭제를 중단했습니다.")
    db.delete(process)
    updated = mark_incident(
        db,
        incident.id,
        STATUS_RESOLVED,
        {
            "selected_action": "close_sessions_and_delete_process",
            "deleted_process_id": process_id,
            "closed_session_ids": [session.id for session in open_sessions],
            "session_snapshot_paths": session_snapshot_paths,
            "process_snapshot_path": process_snapshot_path,
        },
        commit=False,
    )
    db.commit()
    return {
        "incident": incident_to_dict(updated),
        "process_id": process_id,
        "closed_session_ids": [session.id for session in open_sessions],
        "action": "close_sessions_and_delete_process",
    }
