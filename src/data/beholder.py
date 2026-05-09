"""Beholder: semantic DB mutation guard and incident helpers."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

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
GLOBAL_SETTINGS_TABLE = "global_settings"
MANAGED_PROCESSES_TABLE = "managed_processes"
WEB_SHORTCUTS_TABLE = "web_shortcuts"
PROCESS_SESSIONS_TABLE = "process_sessions"

PROCESS_FIELDS = {column.name for column in models.Process.__table__.columns}
WEB_SHORTCUT_FIELDS = {column.name for column in models.WebShortcut.__table__.columns}
SESSION_FIELDS = {column.name for column in models.ProcessSession.__table__.columns}

RUNTIME_SETTINGS_FIELDS = {
    "theme", "always_on_top", "hide_on_game", "run_as_admin", "run_on_startup",
    "sidebar_enabled", "screenshot_enabled", "recording_enabled",
}
SIDEBAR_SETTINGS_FIELDS = {
    "sidebar_enabled", "sidebar_auto_hide_ms", "sidebar_edge_width_px",
    "sidebar_trigger_y_start", "sidebar_trigger_y_end", "sidebar_effect",
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
NEW_GUI_SETTINGS_FIELDS = RUNTIME_SETTINGS_FIELDS | SIDEBAR_SETTINGS_FIELDS | GLOBAL_DIALOG_FIELDS


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
    if actor in {"new_gui_settings", "main_gui_settings"}:
        return set(NEW_GUI_SETTINGS_FIELDS)
    if actor == "sidebar_settings_dialog":
        return set(SIDEBAR_SETTINGS_FIELDS)
    if actor == "global_settings_dialog":
        return set(GLOBAL_DIALOG_FIELDS)
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


def incident_to_dict(incident: models.BeholderIncident) -> dict[str, Any]:
    user_title = getattr(incident, "user_title", None) or _default_user_title(incident)
    user_summary = getattr(incident, "user_summary", None) or incident.suspected_cause
    user_impact = getattr(incident, "user_impact", None) or incident.proposed_change_summary
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
        "safe_recommendation": incident.safe_recommendation,
        "user_title": user_title,
        "user_summary": user_summary,
        "user_impact": user_impact,
        "recommended_action": getattr(incident, "recommended_action", None),
        "available_actions": getattr(incident, "available_actions", None) or _default_actions(incident),
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


def _default_actions(incident: models.BeholderIncident) -> list[dict[str, Any]]:
    actions = [
        {"id": "deny", "label": "차단 유지", "description": "이번 변경을 저장하지 않고 현재 DB를 유지합니다."},
        {"id": "quarantine", "label": "격리", "description": "나중에 검토할 수 있도록 문제 상태로 표시합니다."},
        {"id": "allow_once", "label": "이번 한 번 허용", "description": "동일 작업을 1회만 다시 허용합니다.", "danger": True},
    ]
    return actions


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
        resolution_metadata=resolution_metadata or {},
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


def consume_override_token(db: Session, token: str | None, operation_kind: str) -> bool:
    if not token:
        return False
    incident = db.query(models.BeholderIncident).filter(
        models.BeholderIncident.override_token == token,
        models.BeholderIncident.status == STATUS_ALLOWED,
        models.BeholderIncident.operation_kind == operation_kind,
        models.BeholderIncident.override_used_at.is_(None),
    ).first()
    if not incident:
        return False
    incident.override_used_at = time.time()
    incident.status = STATUS_RESOLVED
    db.add(incident)
    db.commit()
    return True


def active_incidents(db: Session) -> list[models.BeholderIncident]:
    return db.query(models.BeholderIncident).filter(
        models.BeholderIncident.status == STATUS_PENDING
    ).order_by(models.BeholderIncident.created_at.desc()).all()


def session_status_for(session: models.ProcessSession) -> str:
    if getattr(session, "session_status", None):
        return session.session_status
    if session.end_timestamp is not None:
        return "closed"
    return "legacy_unknown"


def _table_label(table: str) -> str:
    return {
        GLOBAL_SETTINGS_TABLE: "설정",
        MANAGED_PROCESSES_TABLE: "게임 항목",
        WEB_SHORTCUTS_TABLE: "웹 바로가기",
        PROCESS_SESSIONS_TABLE: "플레이 기록",
    }.get(table, table)


def _operation_context(operation: BeholderOperation) -> dict[str, Any]:
    return dict(operation.evidence.get("context") or {})


def guard_table_write(db: Session, operation: BeholderOperation, table: str, columns: set[str] | None = None) -> None:
    if consume_override_token(db, operation.override_token, operation.kind):
        return
    if table not in operation.allowed_tables:
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



def guard_process_delete(db: Session, process: models.Process, operation: BeholderOperation) -> None:
    if consume_override_token(db, operation.override_token, operation.kind):
        return
    guard_table_write(db, operation, MANAGED_PROCESSES_TABLE, {"id"})
    open_sessions = db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == process.id,
        models.ProcessSession.end_timestamp.is_(None),
    ).all()
    if not open_sessions:
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

def guard_settings_update(db: Session, current_settings: models.GlobalSettings, update_data: dict[str, Any], operation: BeholderOperation) -> None:
    if consume_override_token(db, operation.override_token, operation.kind):
        return
    changed_fields = set(operation.evidence.get("changed_fields") or [])
    if not changed_fields:
        return
    guard_table_write(db, operation, GLOBAL_SETTINGS_TABLE, changed_fields)

    defaults = _schema_defaults()
    defaulted = [field for field in changed_fields if field in defaults and update_data.get(field) == defaults[field]]
    if len(changed_fields) >= 8 and len(defaulted) >= max(6, int(len(changed_fields) * 0.6)):
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


def guard_session_start(db: Session, session_data: Any, operation: BeholderOperation) -> None:
    if consume_override_token(db, operation.override_token, operation.kind):
        return
    active = db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == session_data.process_id,
        models.ProcessSession.end_timestamp.is_(None),
    ).all()
    live_open = [s for s in active if session_status_for(s) == "open"]
    if live_open:
        context = {
            "process_id": session_data.process_id,
            "process_name": session_data.process_name,
            "requested_start_timestamp": session_data.start_timestamp,
            "requested_user_preset_id": getattr(session_data, "user_preset_id", None),
            "actor": operation.actor,
            "open_session_ids": [s.id for s in live_open],
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
            risk_factors=["duplicate_open_session", "runtime_state_ambiguous"],
            safe_recommendation="기존 세션을 이어가거나, 기존 세션을 닫고 새 세션을 시작할지 선택하세요.",
            user_title="이전 플레이 기록이 아직 열려 있습니다",
            user_summary="앱이 재시작되면서 같은 게임의 새 플레이 기록을 만들려 했지만, 직전 기록이 아직 종료되지 않았습니다.",
            user_impact="그대로 새 기록을 만들면 플레이 시간이 둘로 갈라지거나 중복 집계될 수 있습니다.",
            recommended_action="continue_existing_session",
            available_actions=[
                {"id": "continue_existing_session", "label": "이전 세션 이어가기", "description": "직전 기록을 현재 실행 중인 게임 기록으로 계속 사용합니다.", "recommended": True},
                {"id": "close_previous_and_start_new", "label": "이전 세션 닫고 새로 시작", "description": "이전 기록을 지금 시점에 종료하고 새 기록을 만듭니다."},
                {"id": "deny", "label": "차단 유지", "description": "새 세션을 만들지 않습니다."},
                {"id": "allow_once", "label": "이번 한 번 허용", "description": "중복 세션 생성을 한 번만 허용합니다.", "danger": True},
            ],
            resolution_metadata={"action_context": context},
        )
        raise BeholderBlocked(incident)


def guard_session_end(db: Session, session: models.ProcessSession, end_timestamp: float, operation: BeholderOperation) -> None:
    if consume_override_token(db, operation.override_token, operation.kind):
        return

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
    if operation.actor not in {"process_monitor", "legacy_process_monitor", "new_gui_runtime"}:
        risk_factors.append("actor_not_runtime_owner")
        risk_score += 50

    if risk_score >= 80:
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


def mark_incident(db: Session, incident_id: int, status: str, resolution_metadata: dict[str, Any] | None = None) -> models.BeholderIncident | None:
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
    db.commit()
    db.refresh(incident)
    return incident


def resolve_incident_action(db: Session, incident: models.BeholderIncident, action: str) -> dict[str, Any]:
    if action == "allow_once":
        token = issue_override_token(db, incident)
        return {"incident": incident_to_dict(incident), "override_token": token}
    if action == "deny":
        return {"incident": incident_to_dict(mark_incident(db, incident.id, STATUS_DENIED))}
    if action == "quarantine":
        return {"incident": incident_to_dict(mark_incident(db, incident.id, STATUS_QUARANTINED))}
    if action == "continue_existing_session":
        return _continue_existing_session(db, incident)
    if action == "close_previous_and_start_new":
        return _close_previous_and_start_new(db, incident)
    if action == "close_sessions_and_delete_process":
        return _close_sessions_and_delete_process(db, incident)
    raise ValueError("지원하지 않는 Beholder 결정입니다.")


def _context_for(incident: models.BeholderIncident) -> dict[str, Any]:
    meta = getattr(incident, "resolution_metadata", None) or {}
    return dict(meta.get("action_context") or {})


def _open_sessions_for_context(db: Session, context: dict[str, Any]) -> list[models.ProcessSession]:
    ids = context.get("open_session_ids") or []
    query = db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.is_(None))
    if ids:
        query = query.filter(models.ProcessSession.id.in_(ids))
    elif context.get("process_id"):
        query = query.filter(models.ProcessSession.process_id == context["process_id"])
    return query.order_by(models.ProcessSession.start_timestamp.desc()).all()


def _continue_existing_session(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    open_sessions = _open_sessions_for_context(db, context)
    if not open_sessions:
        raise ValueError("이어갈 수 있는 열린 세션을 찾지 못했습니다.")
    session = open_sessions[0]
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
    updated = mark_incident(db, incident.id, STATUS_RESOLVED, {"selected_action": "continue_existing_session", "continued_session_id": session.id})
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"incident": incident_to_dict(updated), "session_id": session.id, "action": "continue_existing_session"}


def _close_previous_and_start_new(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    now = time.time()
    open_sessions = _open_sessions_for_context(db, context)
    for session in open_sessions:
        session.end_timestamp = now
        session.session_duration = max(0.0, now - float(session.start_timestamp))
        session.session_status = "closed"
        session.close_reason = "beholder_close_previous_and_start_new"
        session.heartbeat_timestamp = now
        db.add(session)
    new_session = models.ProcessSession(
        process_id=context.get("process_id"),
        process_name=context.get("process_name") or context.get("process_id") or "Unknown",
        start_timestamp=context.get("requested_start_timestamp") or now,
        user_preset_id=context.get("requested_user_preset_id"),
        session_owner=context.get("actor") or incident.actor,
        session_status="open",
        heartbeat_timestamp=now,
        lease_token=secrets.token_urlsafe(16),
        guard_flags={"created_by_beholder_resolution": True, "incident_id": incident.id},
    )
    db.add(new_session)
    db.flush()
    updated = mark_incident(db, incident.id, STATUS_RESOLVED, {"selected_action": "close_previous_and_start_new", "new_session_id": new_session.id})
    db.commit()
    db.refresh(new_session)
    return {"incident": incident_to_dict(updated), "session_id": new_session.id, "action": "close_previous_and_start_new"}


def _close_sessions_and_delete_process(db: Session, incident: models.BeholderIncident) -> dict[str, Any]:
    context = _context_for(incident)
    process_id = context.get("process_id")
    if not process_id:
        raise ValueError("삭제할 게임 항목 정보를 찾지 못했습니다.")
    now = time.time()
    open_sessions = _open_sessions_for_context(db, context)
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
    db.delete(process)
    updated = mark_incident(
        db,
        incident.id,
        STATUS_RESOLVED,
        {
            "selected_action": "close_sessions_and_delete_process",
            "deleted_process_id": process_id,
            "closed_session_ids": [session.id for session in open_sessions],
        },
    )
    db.commit()
    return {
        "incident": incident_to_dict(updated),
        "process_id": process_id,
        "closed_session_ids": [session.id for session in open_sessions],
        "action": "close_sessions_and_delete_process",
    }
