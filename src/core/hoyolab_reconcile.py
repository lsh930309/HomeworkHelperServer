"""HoYoLab 스태미나 종료 후 재동기화 코디네이터."""

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal, pyqtSlot

from src.core.process_monitor import ProcessLifecycleEvent, ProcessMonitor
from src.data.data_models import ManagedProcess

logger = logging.getLogger(__name__)


@dataclass
class _ReconcileJob:
    process_id: str
    process_name: str
    session_id: Optional[int]
    game_id: str
    exit_timestamp: float
    lifecycle_token: int
    allow_session_correction: bool = True
    finish_on_success: bool = False
    timer: Optional[QTimer] = None
    in_flight: bool = False
    request_seq: int = 0
    attempts_started: int = 0
    observed_signature: Optional[tuple[int, int]] = None
    stable_hits: int = 0
    applied_session_stamina: Optional[int] = None


class _StaminaFetchSignals(QObject):
    finished = pyqtSignal(str, int, int, object)


class _StaminaPersistSignals(QObject):
    finished = pyqtSignal(str, int, int, object)


class _StaminaFetchTask(QRunnable):
    def __init__(
        self,
        process_id: str,
        lifecycle_token: int,
        request_seq: int,
        game_id: str,
        signals: _StaminaFetchSignals,
    ):
        """백그라운드 fetch 결과를 현재 reconcile job에 다시 매칭할 식별자를 저장합니다."""
        super().__init__()
        self._process_id = process_id
        self._lifecycle_token = lifecycle_token
        self._request_seq = request_seq
        self._game_id = game_id
        self._signals = signals

    def run(self) -> None:
        """워커 스레드에서 HoYoLab 스태미나를 조회하고 결과를 메인 스레드로 전달합니다."""
        payload = {"stamina": None, "fetched_at": time.time()}
        try:
            from src.services.hoyolab import get_hoyolab_service

            service = get_hoyolab_service()
            if service and service.is_available() and service.is_configured():
                stamina = service.get_stamina(self._game_id)
                payload["stamina"] = stamina
                if stamina is not None:
                    payload["fetched_at"] = stamina.updated_at.timestamp()
            else:
                payload["error"] = "service unavailable or not configured"
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            payload["error"] = str(exc)
            logger.warning(
                "[HoYoLab] 재동기화 fetch 실패: process_id=%s, error=%s",
                self._process_id,
                exc,
            )

        self._signals.finished.emit(
            self._process_id,
            self._lifecycle_token,
            self._request_seq,
            payload,
        )


class _StaminaPersistTask(QRunnable):
    def __init__(
        self,
        process_id: str,
        process_name: str,
        session_id: Optional[int],
        lifecycle_token: int,
        request_seq: int,
        fetched_current: int,
        fetched_max: int,
        fetched_at: float,
        exit_timestamp: float,
        allow_session_correction: bool,
        applied_session_stamina: Optional[int],
        data_manager,
        should_abort: Callable[[], bool],
        signals: _StaminaPersistSignals,
    ):
        super().__init__()
        self._process_id = process_id
        self._process_name = process_name
        self._session_id = session_id
        self._lifecycle_token = lifecycle_token
        self._request_seq = request_seq
        self._fetched_current = fetched_current
        self._fetched_max = fetched_max
        self._fetched_at = fetched_at
        self._exit_timestamp = exit_timestamp
        self._allow_session_correction = allow_session_correction
        self._applied_session_stamina = applied_session_stamina
        self._data_manager = data_manager
        self._should_abort = should_abort
        self._signals = signals

    def run(self) -> None:
        result = {
            "signature": (self._fetched_current, self._fetched_max),
            "fetched_at": self._fetched_at,
            "corrected_exit_current": self._applied_session_stamina,
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
                updated_process.stamina_current != self._fetched_current
                or updated_process.stamina_max != self._fetched_max
                or updated_process.stamina_updated_at != self._fetched_at
            )
            updated_process.stamina_current = self._fetched_current
            updated_process.stamina_max = self._fetched_max
            updated_process.stamina_updated_at = self._fetched_at
            process_persist_succeeded = True

            if process_changed:
                if self._should_abort():
                    result["aborted"] = True
                    return
                process_persist_succeeded = self._data_manager.update_process(updated_process)
                if process_persist_succeeded:
                    logger.info(
                        "[HoYoLab] 재동기화 반영: '%s' %s/%s",
                        self._process_name,
                        self._fetched_current,
                        self._fetched_max,
                    )
                else:
                    logger.warning(
                        "[HoYoLab] 재동기화 저장 실패: '%s' %s/%s",
                        self._process_name,
                        self._fetched_current,
                        self._fetched_max,
                    )
                    result["error"] = "process persistence failed"

            session_persist_succeeded = True
            if self._allow_session_correction and self._session_id is not None:
                recovered = int(
                    max(0.0, self._fetched_at - self._exit_timestamp)
                    / HoYoStaminaReconcileCoordinator.RECOVERY_RATE_SEC
                )
                corrected_exit_current = max(
                    0,
                    min(self._fetched_current - recovered, self._fetched_max),
                )
                result["corrected_exit_current"] = corrected_exit_current

                if corrected_exit_current != self._applied_session_stamina:
                    if self._should_abort():
                        result["aborted"] = True
                        return
                    session_persist_succeeded = self._data_manager.update_session_stamina(
                        self._session_id,
                        corrected_exit_current,
                    )
                    if session_persist_succeeded:
                        logger.info(
                            "[HoYoLab] 세션 보정 반영: '%s' session=%s stamina=%s",
                            self._process_name,
                            self._session_id,
                            corrected_exit_current,
                        )
                    else:
                        logger.warning(
                            "[HoYoLab] 세션 보정 저장 실패: '%s' session=%s stamina=%s",
                            self._process_name,
                            self._session_id,
                            corrected_exit_current,
                        )
                        result["error"] = "session persistence failed"

            result["persist_succeeded"] = (
                process_persist_succeeded and session_persist_succeeded
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning(
                "[HoYoLab] 재동기화 persistence 실패: process_id=%s, error=%s",
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


class HoYoStaminaReconcileCoordinator(QObject):
    """게임 종료 후 짧은 시간 동안 HoYoLab 스태미나를 재동기화합니다."""

    RECONCILE_WINDOW_SEC = 180
    RECONCILE_INTERVAL_MS = 60_000
    REQUIRED_STABLE_HITS = 2
    RECOVERY_RATE_SEC = 360

    def __init__(self, data_manager, process_monitor: ProcessMonitor, parent: Optional[QObject] = None):
        """프로세스 lifecycle과 서버 재조회 결과를 연결할 상태와 워커를 준비합니다."""
        super().__init__(parent)
        self._data_manager = data_manager
        self._process_monitor = process_monitor
        self._lifecycle_tokens: dict[str, int] = {}
        self._jobs: dict[str, _ReconcileJob] = {}
        self._shutting_down = False

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _StaminaFetchSignals(self)
        self._signals.finished.connect(self._on_fetch_finished)
        self._persist_signals = _StaminaPersistSignals(self)
        self._persist_signals.finished.connect(self._on_persist_finished)

    def handle_process_started(self, event: ProcessLifecycleEvent) -> None:
        """프로세스 재시작 시 이전 종료 재동기화 작업을 무효화합니다."""
        self._advance_lifecycle_token(event.process_id)
        self._finish_job(event.process_id, "process restarted")

    def handle_process_stopped(self, event: ProcessLifecycleEvent) -> None:
        """프로세스 종료 후 follow-up 재동기화 작업을 예약합니다."""
        self._advance_lifecycle_token(event.process_id)
        self._finish_job(event.process_id, "new stop event")

        if not event.is_hoyoverse_game():
            return

        token = self._current_lifecycle_token(event.process_id)
        observed_signature = None
        stable_hits = 0
        if event.stamina_at_end is not None and event.stamina_max is not None:
            observed_signature = (event.stamina_at_end, event.stamina_max)
            stable_hits = 1

        job = _ReconcileJob(
            process_id=event.process_id,
            process_name=event.process_name,
            session_id=event.session_id,
            game_id=event.hoyolab_game_id or "",
            exit_timestamp=event.timestamp,
            lifecycle_token=token,
            observed_signature=observed_signature,
            stable_hits=stable_hits,
            applied_session_stamina=event.stamina_at_end,
        )
        self._jobs[event.process_id] = job

        initial_delay_ms = 0 if event.stamina_at_end is None else self.RECONCILE_INTERVAL_MS
        self._schedule_attempt(event.process_id, initial_delay_ms)

    def schedule_startup_refreshes(self) -> None:
        """앱 시작 직후 idle 상태의 HoYoLab 데이터를 1회 최신화합니다."""
        if self._shutting_down:
            return

        now = time.time()
        for process in self._data_manager.managed_processes:
            if not process.is_hoyoverse_game():
                continue
            if process.id in self._process_monitor.active_monitored_processes:
                continue

            self._advance_lifecycle_token(process.id)
            self._finish_job(process.id, "startup refresh rescheduled")

            job = _ReconcileJob(
                process_id=process.id,
                process_name=process.name,
                session_id=None,
                game_id=process.hoyolab_game_id or "",
                exit_timestamp=now,
                lifecycle_token=self._current_lifecycle_token(process.id),
                allow_session_correction=False,
                finish_on_success=True,
            )
            self._jobs[process.id] = job
            self._schedule_attempt(process.id, 0)

    def shutdown(self) -> None:
        """앱 종료 시 예약된 재동기화 작업을 중단합니다."""
        self._shutting_down = True
        for process_id in list(self._jobs):
            self._finish_job(process_id, "shutdown")
        self._pool.waitForDone()

    def _advance_lifecycle_token(self, process_id: str) -> int:
        """같은 프로세스의 이전 시작/종료 시퀀스를 무효화할 새 토큰을 발급합니다."""
        next_token = self._lifecycle_tokens.get(process_id, 0) + 1
        self._lifecycle_tokens[process_id] = next_token
        return next_token

    def _current_lifecycle_token(self, process_id: str) -> int:
        """현재 프로세스에 대해 가장 최근에 발급된 lifecycle 토큰을 반환합니다."""
        return self._lifecycle_tokens.get(process_id, 0)

    def _schedule_attempt(self, process_id: str, delay_ms: int) -> None:
        """기존 예약을 교체하고 지정한 지연 뒤에 다음 재조회 시도를 예약합니다."""
        job = self._jobs.get(process_id)
        if job is None or self._shutting_down:
            return

        if job.timer is not None:
            job.timer.stop()
            job.timer.deleteLater()

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda pid=process_id, token=job.lifecycle_token: self._start_attempt(pid, token))
        timer.start(delay_ms)
        job.timer = timer

    def _start_attempt(self, process_id: str, lifecycle_token: int) -> None:
        """현재 job/token이 여전히 유효할 때만 백그라운드 fetch를 시작합니다."""
        job = self._jobs.get(process_id)
        if (
            job is None
            or self._shutting_down
            or lifecycle_token != job.lifecycle_token
            or job.in_flight
        ):
            return

        job.in_flight = True
        job.request_seq += 1
        job.attempts_started += 1
        if job.timer is not None:
            job.timer.deleteLater()
            job.timer = None

        self._pool.start(
            _StaminaFetchTask(
                process_id=job.process_id,
                lifecycle_token=job.lifecycle_token,
                request_seq=job.request_seq,
                game_id=job.game_id,
                signals=self._signals,
            )
        )

    @pyqtSlot(str, int, int, object)
    def _on_fetch_finished(
        self,
        process_id: str,
        lifecycle_token: int,
        request_seq: int,
        payload: object,
    ) -> None:
        """유효한 응답만 반영하고, 안정화 여부에 따라 다음 시도 또는 종료를 결정합니다."""
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
        stamina = data.get("stamina")
        fetched_at = float(data.get("fetched_at", time.time()))

        process = self._data_manager.get_process_by_id(process_id)
        if (
            process is None
            or not process.is_hoyoverse_game()
            or process.hoyolab_game_id != job.game_id
        ):
            self._finish_job(process_id, "process metadata changed")
            return

        if stamina is not None:
            self._pool.start(
                _StaminaPersistTask(
                    process_id=job.process_id,
                    process_name=job.process_name,
                    session_id=job.session_id,
                    lifecycle_token=job.lifecycle_token,
                    request_seq=job.request_seq,
                    fetched_current=stamina.current,
                    fetched_max=stamina.max,
                    fetched_at=fetched_at,
                    exit_timestamp=job.exit_timestamp,
                    allow_session_correction=job.allow_session_correction,
                    applied_session_stamina=job.applied_session_stamina,
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

        job.in_flight = False
        if job.finish_on_success:
            self._finish_job(process_id, "startup refresh failed")
            return

        if fetched_at - job.exit_timestamp >= self.RECONCILE_WINDOW_SEC:
            self._finish_job(process_id, "reconcile window elapsed")
            return

        self._schedule_attempt(process_id, self.RECONCILE_INTERVAL_MS)

    @pyqtSlot(str, int, int, object)
    def _on_persist_finished(
        self,
        process_id: str,
        lifecycle_token: int,
        request_seq: int,
        payload: object,
    ) -> None:
        """백그라운드 저장 완료 후 job 상태를 정리하고 다음 시도를 결정합니다."""
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
            or not process.is_hoyoverse_game()
            or process.hoyolab_game_id != job.game_id
        ):
            self._finish_job(process_id, "process metadata changed")
            return

        if data.get("error"):
            logger.warning(
                "[HoYoLab] 재동기화 저장 후처리 실패: process_id=%s, error=%s",
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
            fetched_at = float(data.get("fetched_at", time.time()))
            if fetched_at - job.exit_timestamp >= self.RECONCILE_WINDOW_SEC:
                self._finish_job(process_id, "reconcile window elapsed")
                return
            self._schedule_attempt(process_id, self.RECONCILE_INTERVAL_MS)
            return

        corrected_exit_current = data.get("corrected_exit_current")
        if corrected_exit_current is not None:
            job.applied_session_stamina = corrected_exit_current

        if job.finish_on_success:
            self._finish_job(process_id, "startup refresh completed")
            return

        signature = data.get("signature")
        if isinstance(signature, tuple) and len(signature) == 2:
            if job.observed_signature == signature:
                job.stable_hits += 1
            else:
                job.observed_signature = signature
                job.stable_hits = 1

            if job.stable_hits >= self.REQUIRED_STABLE_HITS:
                self._finish_job(process_id, "stamina stabilized")
                return

        fetched_at = float(data.get("fetched_at", time.time()))
        if fetched_at - job.exit_timestamp >= self.RECONCILE_WINDOW_SEC:
            self._finish_job(process_id, "reconcile window elapsed")
            return

        self._schedule_attempt(process_id, self.RECONCILE_INTERVAL_MS)

    def _should_abort_persistence(self, process_id: str, lifecycle_token: int, request_seq: int) -> bool:
        """저장 작업이 더 이상 현재 job에 유효하지 않은지 확인합니다."""
        job = self._jobs.get(process_id)
        return (
            self._shutting_down
            or job is None
            or job.lifecycle_token != lifecycle_token
            or job.request_seq != request_seq
            or process_id in self._process_monitor.active_monitored_processes
        )

    def _finish_job(self, process_id: str, reason: str) -> None:
        """프로세스의 active reconcile job과 연결된 타이머를 정리하고 종료합니다."""
        job = self._jobs.pop(process_id, None)
        if job is None:
            return

        if job.timer is not None:
            job.timer.stop()
            job.timer.deleteLater()

        logger.debug(
            "[HoYoLab] reconcile 종료: process_id=%s, reason=%s, attempts=%s",
            process_id,
            reason,
            job.attempts_started,
        )
