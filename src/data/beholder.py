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
        "created_at": incident.created_at,
        "resolved_at": incident.resolved_at,
        "has_override_token": bool(incident.override_token and not incident.override_used_at),
    }


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


def guard_session_start(db: Session, session_data: Any, operation: BeholderOperation) -> None:
    if consume_override_token(db, operation.override_token, operation.kind):
        return
    active = db.query(models.ProcessSession).filter(
        models.ProcessSession.process_id == session_data.process_id,
        models.ProcessSession.end_timestamp.is_(None),
    ).all()
    live_open = [s for s in active if session_status_for(s) == "open"]
    if live_open:
        incident = create_incident(
            db,
            severity=SEVERITY_WARNING,
            operation=operation,
            target_summary=f"process_id={session_data.process_id}",
            suspected_cause="이미 열린 세션이 있는 상태에서 새 세션을 만들려는 시도입니다.",
            current_state_summary=f"열린 세션 {len(live_open)}건이 존재합니다.",
            proposed_change_summary="동일 게임에 새 open session 1건 추가",
            risk_score=65,
            risk_factors=["duplicate_open_session", "runtime_state_ambiguous"],
            safe_recommendation="기존 open session 상태를 먼저 확인한 뒤 다시 시도하세요.",
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
        )
        raise BeholderBlocked(incident)


def mark_incident(db: Session, incident_id: int, status: str) -> models.BeholderIncident | None:
    incident = db.query(models.BeholderIncident).filter(models.BeholderIncident.id == incident_id).first()
    if not incident:
        return None
    incident.status = status
    incident.resolved_at = time.time()
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident
