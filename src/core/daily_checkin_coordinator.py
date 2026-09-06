"""GUI-side scheduler bridge for daily check-in automation."""
from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from src.api.client import BackgroundApiTransport
from src.core import daily_checkin
from src.core import credential_health
from src.gui.work_coordinator import retain_detached_qthreadpool
from src.core.provider_activity import provider_activity

logger = logging.getLogger(__name__)


class _DailyCheckInSignals(QObject):
    finished = Signal(str, object)


class _RunDueDailyCheckInsTask(QRunnable):
    def __init__(self, transport: BackgroundApiTransport, trigger: str, signals: _DailyCheckInSignals):
        super().__init__()
        self._transport = transport
        self._trigger = trigger
        self._signals = signals

    def run(self) -> None:
        payload: dict[str, Any] = {"logs": [], "skipped": [], "attempted": 0}
        try:
            with provider_activity("daily_checkin", self._trigger):
                payload = self._transport.run_due_daily_checkins(trigger=self._trigger) or payload
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
        self._transport = BackgroundApiTransport(getattr(data_manager, "base_url", None))
        self._notifier = notifier
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._signals = _DailyCheckInSignals()
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

    def shutdown(self, deadline_ms: int = 2000) -> bool:
        self._shutting_down = True
        try:
            self._signals.finished.disconnect(self._on_finished)
        except (TypeError, RuntimeError):
            pass
        drained = self._pool.waitForDone(max(0, int(deadline_ms)))
        if not drained:
            retain_detached_qthreadpool(self._pool)
        return drained

    def _start_due_run(self, trigger: str) -> None:
        if self._shutting_down or self._in_flight:
            return
        self._in_flight = True
        task = _RunDueDailyCheckInsTask(self._transport, trigger, self._signals)
        self._pool.start(task)

    @Slot(str, object)
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

        if credential_health.is_alertable_health(None, status):
            self._send_failure_notification(log, credential_issue=True)
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
        self._send_failure_notification(log, credential_issue=False)

    def _send_failure_notification(self, log: dict[str, Any], *, credential_issue: bool) -> None:
        game_label = log.get("game_name") or log.get("process_name") or "게임"
        title = f"{game_label} 계정/토큰 확인 필요" if credential_issue else f"{game_label} 출석 실패"
        message = str(log.get("message") or log.get("status") or "")
        try:
            self._notifier.send_notification(
                title=title,
                message=message,
                task_id_to_highlight=str(log.get("process_id") or "") or None,
                button_text="확인",
                button_action="show",
            )
        except Exception as exc:
            logger.debug("자동 출석 실패 알림 전송 실패: %s", exc, exc_info=True)
