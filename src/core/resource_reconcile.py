"""현재 자원 조회와 종료 세션별 후속 관측을 제공자 큐에 예약한다."""
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
from src.core.process_monitor import ProcessLifecycleEvent
from src.core.provider_health_persist import ProviderHealthPersistTask
from src.data.data_models import ManagedProcess
from src.gui.work_coordinator import retain_detached_qthreadpool
from src.utils.resource_tracking import is_nikke_outpost_resource, is_wuwa_waveplate_resource

logger = logging.getLogger(__name__)


@dataclass
class _FollowupJob:
    """세션 ID가 없으면 1회 조회, 있으면 해당 종료 세션의 독립 follow-up이다."""

    process_id: str
    process_name: str
    session_id: Optional[int]
    target: tuple[str, ...]
    service: object
    exit_monotonic: float
    callback: Optional[Callable[[dict], None]] = None
    periodic: bool = False
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
    """실제 큐 실행 직전에 유효성을 확인하고 API 관측 작업을 요청한다."""

    def __init__(self, job, deadline, fetch, is_current, should_skip_periodic, signals):
        super().__init__()
        self._job = job
        self._deadline = deadline
        self._fetch = fetch
        self._is_current = is_current
        self._should_skip_periodic = should_skip_periodic
        self._signals = signals

    def run(self) -> None:
        result = {"process_id": self._job.process_id}
        try:
            if not self._is_current(self._job):
                result["cancelled"] = True
            elif time.monotonic() >= self._deadline:
                # GUI에서 예약했어도 큐 대기가 끝난 실제 요청 시작 시각을 확인한다.
                result["expired"] = True
            elif self._job.periodic and self._should_skip_periodic(self._job.process_id):
                result["skipped"] = True
            else:
                result.update(self._fetch(self._job))
                if not self._is_current(self._job):
                    result["cancelled"] = True
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("자원 관측 실패: process_id=%s error=%s", self._job.process_id, exc)
        finally:
            self._signals.finished.emit(self._job, result)


class _ResourceFollowupCoordinator(QObject):
    """게임 실행 여부와 무관하게 종료별 조회 슬롯을 같은 제공자 큐에 배치한다."""

    RECONCILE_WINDOW_SEC = 600
    RECONCILE_INTERVAL_MS = 60_000
    resource_updated = Signal(str)

    def __init__(self, data_manager, process_monitor, notifier=None, parent=None):
        super().__init__(parent)
        self._data_manager = data_manager
        self._transport = BackgroundApiTransport(getattr(data_manager, "base_url", None))
        self._process_monitor = process_monitor
        self._notifier = notifier
        self._jobs: dict[tuple[str, Optional[int]], _FollowupJob] = {}
        # 종료 저장이 대기/실패해도 실제 종료 직후부터 주기 조회를 제외한다.
        # 세션 ID·보정 권한은 소유하지 않는 일시적인 종료 시각 투영이다.
        self._recent_exit_times: dict[str, float] = {}
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
        # 제공자 조회 시작 시각과 세션 보정 권한은 canonical API가 소유한다.
        return self._transport.observe_process_resource(job.process_id, job.session_id)

    def _apply_process_row(self, process: ManagedProcess, row: dict) -> None:
        raise NotImplementedError

    def _record_observation_health(self, process: ManagedProcess, payload: dict) -> None:
        raise NotImplementedError

    def handle_process_started(self, event: ProcessLifecycleEvent) -> None:
        """새 시작 조회는 1회 수행하며 앞선 종료 작업을 취소하지 않는다."""
        self.request_refresh(event.process_id)

    def mark_process_stopped(self, event: ProcessLifecycleEvent) -> None:
        """종료 감지 즉시 주기 제외를 시작한다. 종료 저장 성공과는 무관하다."""
        if self._shutting_down or self._event_target(event) is None:
            return
        origin = time.monotonic() - max(0.0, time.time() - event.timestamp)
        previous = self._recent_exit_times.get(event.process_id, float("-inf"))
        self._recent_exit_times[event.process_id] = max(previous, origin)
        self.expire_exit_windows()

    def expire_exit_windows(self) -> None:
        """기존 1초 스케줄러에서 만료되거나 삭제된 게임의 임시 제외값을 지운다."""
        now = time.monotonic()
        for process_id, origin in list(self._recent_exit_times.items()):
            if now >= origin + self.RECONCILE_WINDOW_SEC or self._data_manager.get_process_by_id(process_id) is None:
                self._recent_exit_times.pop(process_id, None)

    def _should_skip_periodic(self, process_id: str) -> bool:
        origin = self._recent_exit_times.get(process_id)
        return origin is not None and time.monotonic() < origin + self.RECONCILE_WINDOW_SEC

    def handle_process_stopped(self, event: ProcessLifecycleEvent) -> None:
        """종료 저장에 성공해 ID를 받은 세션만 follow-up 대상으로 등록한다."""
        self.mark_process_stopped(event)
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
            exit_monotonic=time.monotonic() - max(0.0, time.time() - event.timestamp),
        )
        self._jobs[job.key] = job
        self._schedule_next(job)

    def request_refresh(
        self, process_id: str, callback: Optional[Callable[[dict], None]] = None, *, periodic: bool = False,
    ) -> bool:
        """현재 자원을 1회 조회한다. 수동·시작 조회는 대기 중인 주기 조회보다 우선한다."""
        if self._shutting_down:
            return False
        existing = self._jobs.get((process_id, None))
        if existing is not None:
            if periodic or not existing.periodic:
                return False
            self._finish_job(existing, "manual or start refresh supersedes periodic refresh")
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
            exit_monotonic=time.monotonic(),
            callback=callback,
            periodic=periodic,
        )
        self._jobs[job.key] = job
        self._schedule_next(job)
        return True

    def request_periodic_refreshes(self) -> None:
        """정기 회차의 대상별 현재 자원을 조회하며 종료 추적 중인 게임은 생략한다."""
        if self._shutting_down:
            return
        for process in self._data_manager.managed_processes:
            if not self._should_skip_periodic(process.id):
                self.request_refresh(process.id, periodic=True)

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
        self.expire_exit_windows()

    def _schedule_next(self, job: _FollowupJob) -> None:
        if not self._job_is_current(job):
            self._finish_job(job, "tracking target or account changed")
            return
        now = time.monotonic()
        if job.session_id is None:
            due = now
        else:
            interval = self.RECONCILE_INTERVAL_MS / 1000.0
            deadline = job.exit_monotonic + self.RECONCILE_WINDOW_SEC
            if now >= deadline:
                self._finish_job(job, "follow-up window complete")
                return
            # 늦게 등록됐어도 최초 한 번은 즉시 실행하고, 이후에는 실제 종료의
            # 0/60/.../540초 슬롯을 유지한다. 놓친 슬롯을 모아서 실행하지 않는다.
            if job.next_slot == 0:
                due = now
            else:
                while job.exit_monotonic + job.next_slot * interval < now:
                    job.next_slot += 1
                due = min(job.exit_monotonic + job.next_slot * interval, deadline)
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
            job.exit_monotonic + self.RECONCILE_WINDOW_SEC
            if job.session_id is not None else float("inf")
        )
        now = time.monotonic()
        if now >= deadline:
            self._finish_job(job, "follow-up window complete")
            return
        if job.session_id is not None and job.next_slot:
            due = job.exit_monotonic + job.next_slot * self.RECONCILE_INTERVAL_MS / 1000.0
            if now < due or due >= deadline:
                # 타이머가 예상보다 이르게 전달돼도 슬롯 앞당김·추가 조회를 하지 않는다.
                self._schedule_next(job)
                return
        job.in_flight = True
        interval = self.RECONCILE_INTERVAL_MS / 1000.0
        job.next_slot = max(job.next_slot + 1, math.floor((now - job.exit_monotonic) / interval) + 1)
        self._pool.start(_ObservationTask(
            job, deadline, self._fetch_observation, self._job_is_current,
            self._should_skip_periodic, self._signals,
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
            self._recent_exit_times.clear()
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

    def _apply_process_row(self, process, row):
        for key in ("resource_percent", "resource_updated_at", "resource_status", "resource_label"):
            setattr(process, key, row[key])

    def _record_observation_health(self, process, payload):
        status = payload.get("provider_status")
        if status:
            self._record_provider_health_from_status(
                process, status, payload.get("error") or str(status), payload["fetched_at"],
            )

    def _record_provider_health_from_status(self, process: ManagedProcess, status: str, message: str, fetched_at: float) -> None:
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


class WuwaResourceReconcileCoordinator(NikkeResourceReconcileCoordinator):
    """명조도 같은 시작·주기·종료 후 추적 큐와 저장 API를 사용한다."""

    def _get_service(self):
        from src.services.wuwa import get_wuwa_service
        return get_wuwa_service()

    def _target(self, process):
        if getattr(process, "resource_tracking_enabled", False) and is_wuwa_waveplate_resource(
            getattr(process, "resource_provider", None), getattr(process, "resource_key", None),
        ):
            return process.resource_provider, process.resource_key
        return None

    def _event_target(self, event):
        if getattr(event, "resource_tracking_enabled", False) and is_wuwa_waveplate_resource(
            getattr(event, "resource_provider", None), getattr(event, "resource_key", None),
        ):
            return event.resource_provider, event.resource_key
        return None

    def _apply_process_row(self, process, row):
        super()._apply_process_row(process, row)
        for key in ("resource_current", "resource_max", "resource_reserve_current", "resource_reserve_max"):
            setattr(process, key, row[key])

    def _record_provider_health_from_status(self, process, status, message, fetched_at):
        payload = credential_health.update_payload_for_reason(
            credential_health.PROVIDER_WUWA, status, message=message, source="resource_tracking",
            process_id=process.id, game_id="wuthering_waves", detected_at=fetched_at,
        )
        if payload is None:
            return
        self._health_pool.start(ProviderHealthPersistTask(self._transport, payload, context="명조 resource_tracking"))
        if credential_health.is_alertable_health(payload["status"], payload["reason"]):
            self._send_provider_health_notification(process, payload)
