"""One-shot-safe repair helpers for play session data.

This module intentionally keeps repair rules conservative and explicit.  The
2026-05 new GUI preview bug could close legacy PyQt-owned open sessions during
an otherwise passive state refresh, producing completed sessions that span many
days or months.  Those rows must be reverted to open-session form so existing
analytics and PyQt state stop seeing impossible play time.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from sqlalchemy.orm import Session

from src.data import models

SECONDS_PER_DAY = 86_400
DEFAULT_MAX_REASONABLE_SESSION_SECONDS = 7 * SECONDS_PER_DAY
# The faulty preview GUI was introduced on dev-new-gui shortly before
# 2026-05-08.  Rows ending before this are not touched automatically.
DEFAULT_INCIDENT_NOT_BEFORE_TS = 1_778_079_600.0  # 2026-05-07T00:00:00+09:00
LAST_PLAYED_MATCH_TOLERANCE_SECONDS = 10 * 60


@dataclasses.dataclass(frozen=True)
class SessionRepairReport:
    repaired_session_ids: list[int]
    affected_process_ids: list[str]
    restored_last_played: dict[str, float | None]

    @property
    def repaired_sessions(self) -> int:
        return len(self.repaired_session_ids)

    @property
    def updated_processes(self) -> int:
        return len(self.restored_last_played)


def _duration(session: models.ProcessSession) -> float | None:
    if session.start_timestamp is None or session.end_timestamp is None:
        return None
    return float(session.end_timestamp) - float(session.start_timestamp)


def _is_suspicious_preview_bug_session(
    session: models.ProcessSession,
    *,
    max_reasonable_seconds: float,
    incident_not_before_ts: float,
) -> bool:
    duration = _duration(session)
    if duration is None:
        return False
    if duration <= max_reasonable_seconds:
        return False
    if session.end_timestamp is None or float(session.end_timestamp) < incident_not_before_ts:
        return False
    stored_duration = session.session_duration
    if stored_duration is not None and float(stored_duration) <= max_reasonable_seconds:
        return False
    return True


def _latest_valid_completed_end(
    db: Session,
    process_id: str,
    *,
    exclude_session_ids: Iterable[int],
    max_reasonable_seconds: float,
) -> float | None:
    excluded = set(exclude_session_ids)
    candidates = (
        db.query(models.ProcessSession)
        .filter(
            models.ProcessSession.process_id == process_id,
            models.ProcessSession.end_timestamp.isnot(None),
            models.ProcessSession.end_timestamp > models.ProcessSession.start_timestamp,
        )
        .order_by(models.ProcessSession.end_timestamp.desc())
        .all()
    )
    for session in candidates:
        if session.id in excluded:
            continue
        duration = _duration(session)
        if duration is not None and 0 < duration <= max_reasonable_seconds:
            return float(session.end_timestamp)
    return None


def repair_preview_session_pollution(
    db: Session,
    *,
    max_reasonable_seconds: float = DEFAULT_MAX_REASONABLE_SESSION_SECONDS,
    incident_not_before_ts: float = DEFAULT_INCIDENT_NOT_BEFORE_TS,
) -> SessionRepairReport:
    """Repair sessions polluted by the new GUI preview state-sync bug.

    Repaired rows are changed back to open sessions by clearing
    ``end_timestamp`` and ``session_duration``.  For affected processes whose
    ``last_played_timestamp`` appears to have been set by the same buggy close,
    the value is restored to the latest remaining valid completed session end,
    or ``NULL`` when there is no valid completed session.

    The function is idempotent: once a row is repaired it no longer matches the
    suspicious completed-session predicate.
    """
    suspicious = [
        session
        for session in db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.isnot(None)).all()
        if _is_suspicious_preview_bug_session(
            session,
            max_reasonable_seconds=max_reasonable_seconds,
            incident_not_before_ts=incident_not_before_ts,
        )
    ]
    if not suspicious:
        return SessionRepairReport([], [], {})

    repaired_ids = [int(session.id) for session in suspicious]
    affected_process_ids = sorted({session.process_id for session in suspicious if session.process_id})
    suspicious_end_by_process: dict[str, list[float]] = {}
    for session in suspicious:
        suspicious_end_by_process.setdefault(session.process_id, []).append(float(session.end_timestamp))
        session.end_timestamp = None
        session.session_duration = None
        db.add(session)

    restored_last_played: dict[str, float | None] = {}
    for process_id in affected_process_ids:
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        if process is None or process.last_played_timestamp is None:
            continue
        current_last = float(process.last_played_timestamp)
        if not any(
            abs(current_last - suspicious_end) <= LAST_PLAYED_MATCH_TOLERANCE_SECONDS
            for suspicious_end in suspicious_end_by_process.get(process_id, [])
        ):
            continue
        restored = _latest_valid_completed_end(
            db,
            process_id,
            exclude_session_ids=repaired_ids,
            max_reasonable_seconds=max_reasonable_seconds,
        )
        process.last_played_timestamp = restored
        db.add(process)
        restored_last_played[process_id] = restored

    db.commit()
    return SessionRepairReport(repaired_ids, affected_process_ids, restored_last_played)
