"""종료 세션별 follow-up과 NIKKE 자원 조회·저장을 직렬로 실행한다."""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot

from src.api.client import BackgroundApiTransport
from src.core import credential_health
from src.core.process_monitor import ProcessLifecycleEvent, ProcessMonitor
from src.core.provider_activity import provider_activity
from src.core.provider_health_persist import ProviderHealthPersistTask
from src.data.data_models import ManagedProcess
from src.gui.work_coordinator import retain_detached_qthreadpool
from src.utils.resource_tracking import (
    NIKKE_OUTPOST_FULL_CHARGE_SECONDS,
    NIKKE_OUTPOST_LABEL,
    clamp_percent,
    is_nikke_outpost_resource,
)

logger = logging.getLogger(__name__)


@dataclass
class _FollowupJob:
    """세션 ID가 없으면 1회 조회, 있으면 해당 종료 세션의 독립 follow-up이다."""

    process_id: str
    process_name: str
    session_id: Optional[int]
    target: tuple[str, ...]
    service: object
    exit_timestamp: float
    registered_at: float
    callback: Optional[Callable[[dict], None]] = None
    next_slot: int = 0
    timer: Optional[QTimer] = None
    in_flight: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)

    @property
    def key(self) -> tuple[str, Optional[int]]:
        return self.process_id, self.session_id


class _ObservationSignals(QObject):
    finished = Signal(object, object)


class _ObservationTask(QRunnable):
    """외부 조회와 두 저장을 하나의 제공자 큐 작업 안에서 완료한다."""

    def __init__(self, job, deadline, fetch, persist, is_current, signals):
        super().__init__()
        self._job = job
        self._deadline = deadline
        self._fetch = fetch
        self._persist = persist
        self._is_current = is_current
        self._signals = signals

    def run(self) -> None:
        result = {"process_id": self._job.process_id}
        try:
            if not self._is_current(self._job):
                result["cancelled"] = True
            elif time.monotonic() >= self._deadline:
                # GUI에서 예약했어도 큐 대기가 끝난 실제 요청 시작 시각을 확인한다.
                result["expired"] = True
            else:
                result.update(self._fetch(self._job))
                if not self._is_current(self._job):
                    result["cancelled"] = True
                elif result.get("observation_succeeded"):
                    # 이 요청은 기간 안에 시작했으므로 기간 뒤에 끝나도 저장한다.
                    result.update(self._persist(self._job, result, self._is_current))
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("자원 관측 실패: process_id=%s error=%s", self._job.process_id, exc)
        finally:
            self._signals.finished.emit(self._job, result)


class _ResourceFollowupCoordinator(QObject):
    """게임 실행 여부와 무관하게 종료별 조회 슬롯을 같은 제공자 큐에 배치한다."""

    RECONCILE_WINDOW_SEC = 180
    RECONCILE_INTERVAL_MS = 60_000
    resource_updated = Signal(str)

    def __init__(self, data_manager, process_monitor, notifier=None, parent=None):
        super().__init__(parent)
        self._data_manager = data_manager
        self._transport = BackgroundApiTransport(getattr(data_manager, "base_url", None))
        self._process_monitor = process_monitor
        self._notifier = notifier
        self._jobs: dict[tuple[str, Optional[int]], _FollowupJob] = {}
        self._shutting_down = False
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._health_pool = QThreadPool()
        self._health_pool.setMaxThreadCount(1)
        self._signals = _ObservationSignals()
        self._signals.finished.connect(self._on_observation_finished)

    def _get_service(self):
        raise NotImplementedError

    def _target(self, process: ManagedProcess) -> Optional[tuple[str, ...]]:
        raise NotImplementedError

    def _event_target(self, event: ProcessLifecycleEvent) -> Optional[tuple[str, ...]]:
        raise NotImplementedError

    def _fetch_observation(self, job: _FollowupJob) -> dict:
        raise NotImplementedError

    def _persist_observation(self, job: _FollowupJob, payload: dict, is_current) -> dict:
        raise NotImplementedError

    def _apply_process_row(self, process: ManagedProcess, row: dict) -> None:
        raise NotImplementedError

    def _record_observation_health(self, process: ManagedProcess, payload: dict) -> None:
        raise NotImplementedError

    def handle_process_started(self, event: ProcessLifecycleEvent) -> None:
        """새 시작 조회는 1회 수행하며 앞선 종료 작업을 취소하지 않는다."""
        self.request_refresh(event.process_id)

    def handle_process_stopped(self, event: ProcessLifecycleEvent) -> None:
        """종료 저장에 성공해 ID를 받은 세션만 follow-up 대상으로 등록한다."""
        if self._shutting_down or event.session_id is None:
            return
        process = self._data_manager.get_process_by_id(event.process_id)
        target = self._target(process) if process is not None else None
        if target is None or target != self._event_target(event) or (event.process_id, event.session_id) in self._jobs:
            return
        job = _FollowupJob(
            process_id=event.process_id,
            process_name=event.process_name,
            session_id=event.session_id,
            target=target,
            service=self._get_service(),
            exit_timestamp=event.timestamp,
            registered_at=time.monotonic(),
        )
        self._jobs[job.key] = job
        self._schedule_next(job)

    def request_refresh(self, process_id: str, callback: Optional[Callable[[dict], None]] = None) -> bool:
        """수동·시작 조회를 follow-up과 같은 큐에 1회 등록한다. 중복이면 False다."""
        if self._shutting_down or (process_id, None) in self._jobs:
            return False
        process = self._data_manager.get_process_by_id(process_id)
        target = self._target(process) if process is not None else None
        if target is None:
            return False
        job = _FollowupJob(
            process_id=process_id,
            process_name=process.name,
            session_id=None,
            target=target,
            service=self._get_service(),
            exit_timestamp=time.time(),
            registered_at=time.monotonic(),
            callback=callback,
        )
        self._jobs[job.key] = job
        self._schedule_next(job)
        return True

    def schedule_startup_refreshes(self) -> None:
        """앱 시작 시 실행 중이지 않은 등록 대상도 같은 직렬 조회 경계를 사용한다."""
        for process in self._data_manager.managed_processes:
            if process.id not in self._process_monitor.active_monitored_processes:
                self.request_refresh(process.id)

    def _job_is_current(self, job: _FollowupJob) -> bool:
        if self._shutting_down or job.cancelled.is_set() or self._jobs.get(job.key) is not job:
            return False
        process = self._data_manager.get_process_by_id(job.process_id)
        return (
            process is not None
            and self._target(process) == job.target
            # 설정 변경의 기존 reset_*_service 경계를 사용한다. 자동 쿠키 갱신은
            # 서비스 객체를 교체하지 않으므로 정상 follow-up을 취소하지 않는다.
            and self._get_service() is job.service
        )

    def cancel_changed_targets(self) -> None:
        """등록 삭제·추적 대상·계정 설정 변경만 중단하며 감시 경로는 비교하지 않는다."""
        for job in list(self._jobs.values()):
            if not self._job_is_current(job):
                self._finish_job(job, "tracking target or account changed")

    def _schedule_next(self, job: _FollowupJob) -> None:
        if not self._job_is_current(job):
            self._finish_job(job, "tracking target or account changed")
            return
        now = time.monotonic()
        if job.session_id is None:
            due = now
        else:
            interval = self.RECONCILE_INTERVAL_MS / 1000.0
            # 완료 시각에 60초를 더하지 않고 등록 시점의 0/60/120초를 기준으로 한다.
            # 큐 대기 중 지나간 슬롯을 모아서 실행하지 않는다.
            while job.next_slot and job.registered_at + job.next_slot * interval < now:
                job.next_slot += 1
            deadline = job.registered_at + self.RECONCILE_WINDOW_SEC
            if now >= deadline:
                self._finish_job(job, "follow-up window complete")
                return
            # 마지막 조회가 일찍 끝나도 종료 작업의 기간은 180초까지 유지한다.
            due = min(job.registered_at + job.next_slot * interval, deadline)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.timeout.connect(lambda current_job=job: self._start_attempt(current_job))
        timer.start(max(0, math.ceil((due - now) * 1000)))
        job.timer = timer

    def _start_attempt(self, job: _FollowupJob) -> None:
        if not self._job_is_current(job):
            self._finish_job(job, "tracking target or account changed")
            return
        if job.in_flight:
            return
        if job.timer is not None:
            job.timer.stop()
            job.timer.timeout.disconnect()
            job.timer.deleteLater()
            job.timer = None
        deadline = (
            job.registered_at + self.RECONCILE_WINDOW_SEC
            if job.session_id is not None else float("inf")
        )
        now = time.monotonic()
        if now >= deadline:
            self._finish_job(job, "follow-up window complete")
            return
        if job.session_id is not None:
            due = job.registered_at + job.next_slot * self.RECONCILE_INTERVAL_MS / 1000.0
            if now < due or due >= deadline:
                # 타이머가 예상보다 이르게 전달돼도 슬롯 앞당김·추가 조회를 하지 않는다.
                self._schedule_next(job)
                return
        job.in_flight = True
        job.next_slot += 1
        self._pool.start(_ObservationTask(
            job, deadline, self._fetch_observation, self._persist_observation,
            self._job_is_current, self._signals,
        ))

    @Slot(object, object)
    def _on_observation_finished(self, job: _FollowupJob, payload: dict) -> None:
        if self._jobs.get(job.key) is not job or self._shutting_down:
            return
        job.in_flight = False
        if not self._job_is_current(job) or payload.get("cancelled"):
            self._finish_job(job, "tracking target or account changed")
            return
        process = self._data_manager.get_process_by_id(job.process_id)
        if payload.get("fetched_at") is not None:
            self._record_observation_health(process, payload)
        row = payload.get("process_row")
        if isinstance(row, dict):
            self._apply_process_row(process, row)
            self.resource_updated.emit(job.process_id)
        for error_key in ("error", "process_error", "session_error"):
            if payload.get(error_key):
                logger.warning("자원 조회·저장 결과: process_id=%s session_id=%s %s=%s", job.process_id, job.session_id, error_key, payload[error_key])
        if job.session_id is None:
            callback = job.callback
            job.callback = None
            self._finish_job(job, "one-shot refresh complete")
            if callback is not None:
                callback(payload)
        elif payload.get("expired"):
            self._finish_job(job, "queued request expired before fetch")
        else:
            self._schedule_next(job)

    def _finish_job(self, job: _FollowupJob, reason: str) -> None:
        if self._jobs.get(job.key) is not job:
            return
        self._jobs.pop(job.key)
        job.cancelled.set()
        if job.timer is not None:
            job.timer.stop()
            job.timer.timeout.disconnect()
            job.timer.deleteLater()
            job.timer = None
        callback = job.callback
        job.callback = None
        if callback is not None and not self._shutting_down:
            callback({"process_id": job.process_id, "cancelled": True, "error": reason})
        logger.debug("follow-up 종료: process_id=%s session_id=%s reason=%s", job.process_id, job.session_id, reason)

    def shutdown(self, deadline_ms: int = 2000) -> bool:
        if not self._shutting_down:
            self._shutting_down = True
            for job in list(self._jobs.values()):
                self._finish_job(job, "shutdown")
            self._pool.clear()
            self._health_pool.clear()
            try:
                self._signals.finished.disconnect(self._on_observation_finished)
            except (TypeError, RuntimeError):
                pass
        deadline = time.monotonic() + max(0, int(deadline_ms)) / 1000.0
        primary = self._pool.waitForDone(max(0, int((deadline - time.monotonic()) * 1000)))
        health = self._health_pool.waitForDone(max(0, int((deadline - time.monotonic()) * 1000)))
        if not primary:
            retain_detached_qthreadpool(self._pool)
        if not health:
            retain_detached_qthreadpool(self._health_pool)
        return primary and health


def _persist_resource_observation(job, payload, transport, is_current) -> dict:
    """현재 자원 저장과 자기 종료 세션 보정은 각각의 결과를 기록한다."""
    snapshot = payload["snapshot"]
    fetched_at = payload["fetched_at"]
    percent = clamp_percent(snapshot.percent)
    result = {"process_row": None, "session_succeeded": False}
    try:
        result["process_row"] = transport.update_process_resource(
            job.process_id, percent, fetched_at, snapshot.status,
            snapshot.label or NIKKE_OUTPOST_LABEL,
        )
    except Exception as exc:
        result["process_error"] = str(exc)
    if job.session_id is not None and is_current(job):
        recovered = max(0.0, fetched_at - job.exit_timestamp) * 100.0 / NIKKE_OUTPOST_FULL_CHARGE_SECONDS
        corrected = clamp_percent(percent - recovered)
        try:
            transport.update_session_resource(job.session_id, corrected)
            result["corrected_exit_percent"] = corrected
            result["session_succeeded"] = True
        except Exception as exc:
            result["session_error"] = str(exc)
    return result


class NikkeResourceReconcileCoordinator(_ResourceFollowupCoordinator):
    """NIKKE 전초기지 관측은 종료별 세션 보정과 현재 자원 저장을 분리한다."""

    def _get_service(self):
        from src.services.nikke import get_nikke_service
        return get_nikke_service()

    def _target(self, process):
        if getattr(process, "resource_tracking_enabled", False) and is_nikke_outpost_resource(
            getattr(process, "resource_provider", None), getattr(process, "resource_key", None)
        ):
            return process.resource_provider, process.resource_key
        return None

    def _event_target(self, event):
        if event.is_nikke_outpost_resource_game():
            return event.resource_provider, event.resource_key
        return None

    def _fetch_observation(self, job):
        with provider_activity(job.target[0], job.target[1]):
            snapshot = job.service.get_outpost_storage()
        return {
            "snapshot": snapshot,
            "fetched_at": snapshot.updated_at.timestamp(),
            "provider_status": snapshot.status,
            "error": snapshot.message if snapshot.status != "ok" else None,
            "observation_succeeded": snapshot.status == "ok" and snapshot.percent is not None,
        }

    def _persist_observation(self, job, payload, is_current):
        return _persist_resource_observation(job, payload, self._transport, is_current)

    def _apply_process_row(self, process, row):
        for key in ("resource_percent", "resource_updated_at", "resource_status", "resource_label"):
            setattr(process, key, row[key])

    def _record_observation_health(self, process, payload):
        snapshot = payload.get("snapshot")
        if snapshot is not None:
            self._record_provider_health_from_snapshot(process, snapshot, payload["fetched_at"])

    def _record_provider_health_from_snapshot(self, process: ManagedProcess, snapshot, fetched_at: float) -> None:
        status = str(getattr(snapshot, "status", "") or "")
        message = str(getattr(snapshot, "message", "") or status)
        payload = credential_health.update_payload_for_reason(
            credential_health.PROVIDER_NIKKE_BLABLALINK,
            status, message=message, source="resource_tracking", process_id=process.id,
            game_id=getattr(process, "user_preset_id", None) or "nikke", detected_at=fetched_at,
        )
        if payload is None:
            return
        self._health_pool.start(ProviderHealthPersistTask(self._transport, payload, context="NIKKE resource_tracking"))
        if credential_health.is_alertable_health(payload["status"], payload["reason"]):
            self._send_provider_health_notification(process, payload)

    def _send_provider_health_notification(self, process: ManagedProcess, payload: dict[str, object]) -> None:
        if self._notifier is None:
            return
        try:
            self._notifier.send_notification(
                title=f"{process.name} 계정/토큰 확인 필요",
                message=str(payload.get("message") or payload.get("reason") or ""),
                task_id_to_highlight=process.id, button_text="확인", button_action="show",
            )
        except Exception as exc:
            logger.debug("[Resource] provider health 알림 전송 실패: %s", exc, exc_info=True)
