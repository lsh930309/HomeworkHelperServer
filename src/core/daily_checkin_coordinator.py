"""GUI-side scheduler bridge for daily check-in automation."""
from __future__ import annotations

import logging
import time
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from src.core import daily_checkin

logger = logging.getLogger(__name__)


class _DailyCheckInSignals(QObject):
    finished = pyqtSignal(str, object)


class _RunDueDailyCheckInsTask(QRunnable):
    def __init__(self, data_manager, trigger: str, signals: _DailyCheckInSignals):
        super().__init__()
        self._data_manager = data_manager
        self._trigger = trigger
        self._signals = signals

    def run(self) -> None:
        payload: dict[str, Any] = {"logs": [], "skipped": [], "attempted": 0}
        try:
            runner = getattr(self._data_manager, "run_due_daily_checkins", None)
            if callable(runner):
                payload = runner(trigger=self._trigger) or payload
            else:
                payload["error"] = "daily check-in API client is not available"
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.warning("자동 출석 due 실행 실패: %s", exc, exc_info=True)
            payload["error"] = str(exc)
        self._signals.finished.emit(self._trigger, payload)


class DailyCheckInCoordinator(QObject):
    """Runs due check-ins off the GUI thread and dispatches failure-only notices."""

    def __init__(self, data_manager, notifier, parent: QObject | None = None):
        super().__init__(parent)
        self._data_manager = data_manager
        self._notifier = notifier
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _DailyCheckInSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._in_flight = False
        self._shutting_down = False
        # Startup/wake have explicit trigger paths; keep the periodic timer from
        # racing the startup check and mislabeling the first catch-up run.
        self._last_periodic_at = time.time()
        self._notified_failures: set[tuple[str, str, float, str]] = set()

    def schedule_startup_check(self) -> None:
        self._start_due_run("startup")

    def handle_wake_recovery(self) -> None:
        self._start_due_run("wake")

    def maybe_run_periodic(self) -> None:
        if self._shutting_down:
            return
        now = time.time()
        if now - self._last_periodic_at < daily_checkin.PERIODIC_CHECK_INTERVAL_SECONDS:
            return
        self._last_periodic_at = now
        self._start_due_run("periodic")

    def shutdown(self) -> None:
        self._shutting_down = True
        self._pool.waitForDone()

    def _start_due_run(self, trigger: str) -> None:
        if self._shutting_down or self._in_flight:
            return
        self._in_flight = True
        task = _RunDueDailyCheckInsTask(self._data_manager, trigger, self._signals)
        self._pool.start(task)

    def _on_finished(self, trigger: str, payload: object) -> None:
        self._in_flight = False
        if not isinstance(payload, dict):
            return
        if payload.get("error"):
            logger.warning("자동 출석 due 실행 오류(trigger=%s): %s", trigger, payload.get("error"))
            return
        for log in payload.get("logs") or []:
            if isinstance(log, dict):
                self._notify_failure_if_needed(log)

    def _notify_failure_if_needed(self, log: dict[str, Any]) -> None:
        status = str(log.get("status") or "")
        if not daily_checkin.is_failure_status(status):
            return

        process_id = str(log.get("process_id") or "")
        game_id = str(log.get("game_id") or "")
        try:
            period_start = float(log.get("period_start") or 0.0)
        except (TypeError, ValueError):
            period_start = 0.0
        key = (process_id, game_id, period_start, status)
        if key in self._notified_failures:
            return
        self._notified_failures.add(key)

        title = f"{log.get('game_name') or log.get('process_name') or '게임'} 출석 실패"
        message = str(log.get("message") or status)
        try:
            self._notifier.send_notification(
                title=title,
                message=message,
                task_id_to_highlight=process_id or None,
                button_text="확인",
                button_action="show",
            )
        except Exception as exc:
            logger.debug("자동 출석 실패 알림 전송 실패: %s", exc, exc_info=True)
