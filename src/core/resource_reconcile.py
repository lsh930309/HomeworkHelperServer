"""External resource 종료 후 재동기화 코디네이터."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal, pyqtSlot

from src.core.process_monitor import ProcessLifecycleEvent, ProcessMonitor
from src.core import credential_health
from src.core.provider_health_persist import ProviderHealthPersistTask
from src.data.data_models import ManagedProcess
from src.utils.resource_tracking import (
    NIKKE_OUTPOST_FULL_CHARGE_SECONDS,
    NIKKE_OUTPOST_LABEL,
    clamp_percent,
    is_nikke_outpost_resource,
)

logger = logging.getLogger(__name__)


@dataclass
class _ResourceReconcileJob:
    process_id: str
    process_name: str
    session_id: Optional[int]
    provider: str
    resource_key: str
    exit_timestamp: float
    lifecycle_token: int
    allow_session_correction: bool = True
    finish_on_success: bool = False
    timer: Optional[QTimer] = None
    in_flight: bool = False
    request_seq: int = 0
    attempts_started: int = 0
    baseline_signature: Optional[tuple[float]] = None
    observed_signature: Optional[tuple[float]] = None
    saw_non_baseline_signature: bool = False
    stable_hits: int = 0
    applied_session_percent: Optional[float] = None


class _ResourceFetchSignals(QObject):
    finished = pyqtSignal(str, int, int, object)


class _ResourcePersistSignals(QObject):
    finished = pyqtSignal(str, int, int, object)


class _ResourceFetchTask(QRunnable):
    def __init__(
        self,
        process_id: str,
        lifecycle_token: int,
        request_seq: int,
        provider: str,
        resource_key: str,
        signals: _ResourceFetchSignals,
    ):
        super().__init__()
        self._process_id = process_id
        self._lifecycle_token = lifecycle_token
        self._request_seq = request_seq
        self._provider = provider
        self._resource_key = resource_key
        self._signals = signals

    def run(self) -> None:
        payload = {"snapshot": None, "fetched_at": time.time()}
        try:
            if is_nikke_outpost_resource(self._provider, self._resource_key):
                from src.services.nikke import get_nikke_service

                snapshot = get_nikke_service().get_outpost_storage()
                payload["snapshot"] = snapshot
                payload["fetched_at"] = snapshot.updated_at.timestamp()
            else:
                payload["error"] = "unsupported resource"
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            payload["error"] = str(exc)
            logger.warning(
                "[Resource] 재동기화 fetch 실패: process_id=%s, error=%s",
                self._process_id,
                exc,
            )

        self._signals.finished.emit(
            self._process_id,
            self._lifecycle_token,
            self._request_seq,
            payload,
        )


class _ResourcePersistTask(QRunnable):
    def __init__(
        self,
        process_id: str,
        process_name: str,
        session_id: Optional[int],
        lifecycle_token: int,
        request_seq: int,
        fetched_percent: float,
        fetched_label: str,
        fetched_status: str,
        fetched_at: float,
        exit_timestamp: float,
        allow_session_correction: bool,
        applied_session_percent: Optional[float],
        data_manager,
        should_abort: Callable[[], bool],
        signals: _ResourcePersistSignals,
    ):
        super().__init__()
        self._process_id = process_id
        self._process_name = process_name
        self._session_id = session_id
        self._lifecycle_token = lifecycle_token
        self._request_seq = request_seq
        self._fetched_percent = fetched_percent
        self._fetched_label = fetched_label
        self._fetched_status = fetched_status
        self._fetched_at = fetched_at
        self._exit_timestamp = exit_timestamp
        self._allow_session_correction = allow_session_correction
        self._applied_session_percent = applied_session_percent
        self._data_manager = data_manager
        self._should_abort = should_abort
        self._signals = signals

    def run(self) -> None:
        signature = (round(float(self._fetched_percent), 1),)
        result = {
            "signature": signature,
            "fetched_at": self._fetched_at,
            "corrected_exit_percent": self._applied_session_percent,
            "aborted": False,
            "persist_succeeded": False,
        }
        try:
            if self._should_abort():
                result["aborted"] = True
                return

            live_process = self._data_manager.get_process_by_id(self._process_id)
            if live_process is None:
                result["error"] = "process missing during persistence"
                return

            updated_process = ManagedProcess.from_dict(live_process.to_dict())
            process_changed = (
                updated_process.resource_percent != self._fetched_percent
                or updated_process.resource_updated_at != self._fetched_at
                or updated_process.resource_status != self._fetched_status
                or updated_process.resource_label != self._fetched_label
            )
            updated_process.resource_percent = self._fetched_percent
            updated_process.resource_updated_at = self._fetched_at
            updated_process.resource_status = self._fetched_status
            updated_process.resource_label = self._fetched_label
            process_persist_succeeded = True

            if process_changed:
                if self._should_abort():
                    result["aborted"] = True
                    return
                if hasattr(self._data_manager, "update_process_resource"):
                    process_persist_succeeded = self._data_manager.update_process_resource(
                        self._process_id,
                        self._fetched_percent,
                        self._fetched_at,
                        self._fetched_status,
                        self._fetched_label,
                    )
                else:
                    process_persist_succeeded = self._data_manager.update_process_runtime_state(updated_process)
                if process_persist_succeeded:
                    logger.info(
                        "[Resource] 재동기화 반영: '%s' %s %.1f%%",
                        self._process_name,
                        self._fetched_label,
                        self._fetched_percent,
                    )
                else:
                    logger.warning(
                        "[Resource] 재동기화 저장 실패: '%s' %.1f%%",
                        self._process_name,
                        self._fetched_percent,
                    )
                    result["error"] = "process persistence failed"

            session_persist_succeeded = True
            if self._allow_session_correction and self._session_id is not None:
                recovered = (
                    max(0.0, self._fetched_at - self._exit_timestamp)
                    * 100.0
                    / NIKKE_OUTPOST_FULL_CHARGE_SECONDS
                )
                corrected_exit_percent = clamp_percent(self._fetched_percent - recovered)
                result["corrected_exit_percent"] = corrected_exit_percent

                if corrected_exit_percent is not None and corrected_exit_percent != self._applied_session_percent:
                    if self._should_abort():
                        result["aborted"] = True
                        return
                    if hasattr(self._data_manager, "update_session_resource"):
                        session_persist_succeeded = self._data_manager.update_session_resource(
                            self._session_id,
                            corrected_exit_percent,
                        )
                    else:
                        session_persist_succeeded = False
                    if session_persist_succeeded:
                        logger.info(
                            "[Resource] 세션 보정 반영: '%s' session=%s percent=%.1f%%",
                            self._process_name,
                            self._session_id,
                            corrected_exit_percent,
                        )
                    else:
                        logger.warning(
                            "[Resource] 세션 보정 저장 실패: '%s' session=%s percent=%s",
                            self._process_name,
                            self._session_id,
                            corrected_exit_percent,
                        )
                        result["error"] = "session persistence failed"

            result["persist_succeeded"] = process_persist_succeeded and session_persist_succeeded
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning(
                "[Resource] 재동기화 persistence 실패: process_id=%s, error=%s",
                self._process_id,
                exc,
            )
        finally:
            self._signals.finished.emit(
                self._process_id,
                self._lifecycle_token,
                self._request_seq,
                result,
            )


class NikkeResourceReconcileCoordinator(QObject):
    """NIKKE 전초기지 방어 보상을 종료 후 짧은 시간 동안 재동기화합니다."""

    RECONCILE_WINDOW_SEC = 180
    RECONCILE_INTERVAL_MS = 60_000
    REQUIRED_STABLE_HITS = 2

    def __init__(self, data_manager, process_monitor: ProcessMonitor, notifier=None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._data_manager = data_manager
        self._process_monitor = process_monitor
        self._notifier = notifier
        self._lifecycle_tokens: dict[str, int] = {}
        self._jobs: dict[str, _ResourceReconcileJob] = {}
        self._shutting_down = False

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._health_pool = QThreadPool(self)
        self._health_pool.setMaxThreadCount(1)
        self._signals = _ResourceFetchSignals(self)
        self._signals.finished.connect(self._on_fetch_finished)
        self._persist_signals = _ResourcePersistSignals(self)
        self._persist_signals.finished.connect(self._on_persist_finished)

    def handle_process_started(self, event: ProcessLifecycleEvent) -> None:
        self._advance_lifecycle_token(event.process_id)
        self._finish_job(event.process_id, "process restarted")

    def handle_process_stopped(self, event: ProcessLifecycleEvent) -> None:
        self._advance_lifecycle_token(event.process_id)
        self._finish_job(event.process_id, "new stop event")

        if not event.is_nikke_outpost_resource_game():
            return

        token = self._current_lifecycle_token(event.process_id)
        process = self._data_manager.get_process_by_id(event.process_id)
        baseline_percent = event.resource_percent_at_end
        if baseline_percent is None and process is not None:
            baseline_percent = getattr(process, "resource_percent", None)

        baseline_signature = None
        if baseline_percent is not None:
            normalized = clamp_percent(baseline_percent)
            if normalized is not None:
                baseline_signature = (round(normalized, 1),)

        job = _ResourceReconcileJob(
            process_id=event.process_id,
            process_name=event.process_name,
            session_id=event.session_id,
            provider=event.resource_provider or "",
            resource_key=event.resource_key or "",
            exit_timestamp=event.timestamp,
            lifecycle_token=token,
            baseline_signature=baseline_signature,
            observed_signature=baseline_signature,
            applied_session_percent=event.resource_percent_at_end,
        )
        self._jobs[event.process_id] = job

        initial_delay_ms = 0 if event.resource_percent_at_end is None else self.RECONCILE_INTERVAL_MS
        self._schedule_attempt(event.process_id, initial_delay_ms)

    def schedule_startup_refreshes(self) -> None:
        if self._shutting_down:
            return

        now = time.time()
        for process in self._data_manager.managed_processes:
            if not getattr(process, "resource_tracking_enabled", False) or not is_nikke_outpost_resource(
                getattr(process, "resource_provider", None),
                getattr(process, "resource_key", None),
            ):
                continue
            if process.id in self._process_monitor.active_monitored_processes:
                continue

            self._advance_lifecycle_token(process.id)
            self._finish_job(process.id, "startup refresh rescheduled")

            job = _ResourceReconcileJob(
                process_id=process.id,
                process_name=process.name,
                session_id=None,
                provider=process.resource_provider or "",
                resource_key=process.resource_key or "",
                exit_timestamp=now,
                lifecycle_token=self._current_lifecycle_token(process.id),
                allow_session_correction=False,
                finish_on_success=True,
            )
            self._jobs[process.id] = job
            self._schedule_attempt(process.id, 0)

    def shutdown(self) -> None:
        self._shutting_down = True
        for process_id in list(self._jobs):
            self._finish_job(process_id, "shutdown")
        self._pool.waitForDone()
        self._health_pool.waitForDone()

    def _advance_lifecycle_token(self, process_id: str) -> int:
        next_token = self._lifecycle_tokens.get(process_id, 0) + 1
        self._lifecycle_tokens[process_id] = next_token
        return next_token

    def _current_lifecycle_token(self, process_id: str) -> int:
        return self._lifecycle_tokens.get(process_id, 0)

    def _reconcile_window_elapsed(self, exit_timestamp: float) -> bool:
        return time.time() - exit_timestamp >= self.RECONCILE_WINDOW_SEC

    def _schedule_attempt(self, process_id: str, delay_ms: int) -> None:
        job = self._jobs.get(process_id)
        if job is None or self._shutting_down:
            return

        if self._reconcile_window_elapsed(job.exit_timestamp):
            self._finish_job(process_id, "reconcile window elapsed before scheduling")
            return

        if job.timer is not None:
            job.timer.stop()
            job.timer.deleteLater()

        remaining_ms = max(
            0,
            int((self.RECONCILE_WINDOW_SEC - max(0.0, time.time() - job.exit_timestamp)) * 1000),
        )
        effective_delay_ms = max(0, min(delay_ms, remaining_ms))

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda pid=process_id, token=job.lifecycle_token: self._start_attempt(pid, token))
        timer.start(effective_delay_ms)
        job.timer = timer

    def _start_attempt(self, process_id: str, lifecycle_token: int) -> None:
        job = self._jobs.get(process_id)
        if (
            job is None
            or self._shutting_down
            or lifecycle_token != job.lifecycle_token
            or job.in_flight
        ):
            return

        if self._reconcile_window_elapsed(job.exit_timestamp):
            self._finish_job(process_id, "reconcile window elapsed before fetch")
            return

        job.in_flight = True
        job.request_seq += 1
        job.attempts_started += 1
        if job.timer is not None:
            job.timer.deleteLater()
            job.timer = None

        self._pool.start(
            _ResourceFetchTask(
                process_id=job.process_id,
                lifecycle_token=job.lifecycle_token,
                request_seq=job.request_seq,
                provider=job.provider,
                resource_key=job.resource_key,
                signals=self._signals,
            )
        )

    @pyqtSlot(str, int, int, object)
    def _on_fetch_finished(self, process_id: str, lifecycle_token: int, request_seq: int, payload: object) -> None:
        job = self._jobs.get(process_id)
        if (
            self._shutting_down
            or job is None
            or job.lifecycle_token != lifecycle_token
            or job.request_seq != request_seq
        ):
            return

        if process_id in self._process_monitor.active_monitored_processes:
            self._finish_job(process_id, "process running again")
            return

        data = payload if isinstance(payload, dict) else {}
        snapshot = data.get("snapshot")
        fetched_at_value = data.get("fetched_at")
        if not isinstance(fetched_at_value, (int, float)):
            fetched_at_value = time.time()
        fetched_at = float(fetched_at_value)
        process = self._data_manager.get_process_by_id(process_id)
        if (
            process is None
            or not getattr(process, "resource_tracking_enabled", False)
            or not is_nikke_outpost_resource(getattr(process, "resource_provider", None), getattr(process, "resource_key", None))
        ):
            self._finish_job(process_id, "process metadata changed")
            return

        percent = getattr(snapshot, "percent", None)
        status = getattr(snapshot, "status", None)
        if snapshot is not None and status == "ok" and percent is not None:
            self._record_provider_health_from_snapshot(process, snapshot, fetched_at)
            normalized_percent = clamp_percent(percent)
            if normalized_percent is not None:
                self._pool.start(
                    _ResourcePersistTask(
                        process_id=job.process_id,
                        process_name=job.process_name,
                        session_id=job.session_id,
                        lifecycle_token=job.lifecycle_token,
                        request_seq=job.request_seq,
                        fetched_percent=normalized_percent,
                        fetched_label=getattr(snapshot, "label", None) or NIKKE_OUTPOST_LABEL,
                        fetched_status=status,
                        fetched_at=fetched_at,
                        exit_timestamp=job.exit_timestamp,
                        allow_session_correction=job.allow_session_correction,
                        applied_session_percent=job.applied_session_percent,
                        data_manager=self._data_manager,
                        should_abort=lambda pid=job.process_id, token=job.lifecycle_token, seq=job.request_seq: self._should_abort_persistence(
                            pid,
                            token,
                            seq,
                        ),
                        signals=self._persist_signals,
                    )
                )
                return

        if snapshot is not None and status:
            self._record_provider_health_from_snapshot(process, snapshot, fetched_at)
            if status in {"auth_required", "auth_expired", "role_not_found"}:
                self._finish_job(process_id, f"provider health {status}")
                return

        job.in_flight = False
        if job.finish_on_success:
            self._finish_job(process_id, "startup refresh failed")
            return

        if self._reconcile_window_elapsed(job.exit_timestamp):
            self._finish_job(process_id, "reconcile window elapsed")
            return

        self._schedule_attempt(process_id, self.RECONCILE_INTERVAL_MS)

    def _record_provider_health_from_snapshot(self, process: ManagedProcess, snapshot, fetched_at: float) -> None:
        status = str(getattr(snapshot, "status", "") or "")
        message = str(getattr(snapshot, "message", "") or status)
        payload = credential_health.update_payload_for_reason(
            credential_health.PROVIDER_NIKKE_BLABLALINK,
            status,
            message=message,
            source="resource_tracking",
            process_id=process.id,
            game_id=getattr(process, "user_preset_id", None) or "nikke",
            detected_at=fetched_at,
        )
        if payload is None:
            return

        self._health_pool.start(
            ProviderHealthPersistTask(
                self._data_manager,
                payload,
                context="NIKKE resource_tracking",
            )
        )

        if credential_health.is_alertable_health(payload["status"], payload["reason"]):
            self._send_provider_health_notification(process, payload)

    def _send_provider_health_notification(self, process: ManagedProcess, payload: dict[str, object]) -> None:
        if self._notifier is None:
            return
        try:
            self._notifier.send_notification(
                title=f"{process.name} 계정/토큰 확인 필요",
                message=str(payload.get("message") or payload.get("reason") or ""),
                task_id_to_highlight=process.id,
                button_text="확인",
                button_action="show",
            )
        except Exception as exc:
            logger.debug("[Resource] provider health 알림 전송 실패: %s", exc, exc_info=True)

    @pyqtSlot(str, int, int, object)
    def _on_persist_finished(self, process_id: str, lifecycle_token: int, request_seq: int, payload: object) -> None:
        job = self._jobs.get(process_id)
        if (
            self._shutting_down
            or job is None
            or job.lifecycle_token != lifecycle_token
            or job.request_seq != request_seq
        ):
            return

        job.in_flight = False

        if process_id in self._process_monitor.active_monitored_processes:
            self._finish_job(process_id, "process running again")
            return

        data = payload if isinstance(payload, dict) else {}
        process = self._data_manager.get_process_by_id(process_id)
        if (
            process is None
            or not getattr(process, "resource_tracking_enabled", False)
            or not is_nikke_outpost_resource(getattr(process, "resource_provider", None), getattr(process, "resource_key", None))
        ):
            self._finish_job(process_id, "process metadata changed")
            return

        if data.get("error"):
            logger.warning(
                "[Resource] 재동기화 저장 후처리 실패: process_id=%s, error=%s",
                process_id,
                data["error"],
            )
            if job.finish_on_success:
                self._finish_job(process_id, "startup refresh failed")
                return

        if not data.get("persist_succeeded", False):
            if job.finish_on_success:
                self._finish_job(process_id, "startup refresh failed")
                return
            if self._reconcile_window_elapsed(job.exit_timestamp):
                self._finish_job(process_id, "reconcile window elapsed")
                return
            self._schedule_attempt(process_id, self.RECONCILE_INTERVAL_MS)
            return

        corrected_exit_percent = data.get("corrected_exit_percent")
        if corrected_exit_percent is not None:
            job.applied_session_percent = corrected_exit_percent

        if job.finish_on_success:
            self._finish_job(process_id, "startup refresh completed")
            return

        signature = data.get("signature")
        if isinstance(signature, tuple) and len(signature) == 1:
            if job.observed_signature == signature:
                job.stable_hits += 1
            else:
                job.observed_signature = signature
                job.stable_hits = 1

            if job.baseline_signature is not None and not job.saw_non_baseline_signature:
                if signature != job.baseline_signature:
                    job.saw_non_baseline_signature = True
                else:
                    job.stable_hits = 0

            allow_stabilized_finish = job.baseline_signature is None or job.saw_non_baseline_signature
            if allow_stabilized_finish and job.stable_hits >= self.REQUIRED_STABLE_HITS:
                self._finish_job(process_id, "resource stabilized")
                return

        if self._reconcile_window_elapsed(job.exit_timestamp):
            self._finish_job(process_id, "reconcile window elapsed")
            return

        self._schedule_attempt(process_id, self.RECONCILE_INTERVAL_MS)

    def _should_abort_persistence(self, process_id: str, lifecycle_token: int, request_seq: int) -> bool:
        job = self._jobs.get(process_id)
        return (
            self._shutting_down
            or job is None
            or job.lifecycle_token != lifecycle_token
            or job.request_seq != request_seq
            or process_id in self._process_monitor.active_monitored_processes
        )

    def _finish_job(self, process_id: str, reason: str) -> None:
        job = self._jobs.pop(process_id, None)
        if job is None:
            return

        if job.timer is not None:
            job.timer.stop()
            job.timer.deleteLater()

        logger.debug(
            "[Resource] reconcile 종료: process_id=%s, reason=%s, attempts=%s",
            process_id,
            reason,
            job.attempts_started,
        )
