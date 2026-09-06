"""Binding-neutral presentation API shared by Widgets and Qt Quick surfaces."""
from __future__ import annotations

import datetime
import logging
from typing import Any

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from src.gui.qt_runtime import require_object_thread

logger = logging.getLogger(__name__)


class HostUiFacade(QObject):
    processesChanged = Signal()
    themeChanged = Signal()
    visibilityRequested = Signal(bool)

    def __init__(self, main_window, parent: QObject | None = None):
        super().__init__(parent or main_window)
        self._main_window = main_window
        self._processes: list[dict[str, Any]] = []
        self._dark_theme = False
        self._presentation_window = None
        refresh_timer = getattr(main_window, "ui_refresh_timer", None)
        if refresh_timer is not None:
            refresh_timer.timeout.connect(self.refresh)
        main_window.request_table_refresh_signal.connect(self.refresh)
        self.refresh()

    @Property("QVariantList", notify=processesChanged)
    def processes(self) -> list[dict[str, Any]]:
        return list(self._processes)

    @Property(bool, notify=themeChanged)
    def darkTheme(self) -> bool:
        return self._dark_theme

    @Property(str, constant=True)
    def title(self) -> str:
        return "숙제 관리자"

    def set_presentation_window(self, window) -> None:
        self._presentation_window = window

    @Slot()
    def refresh(self) -> None:
        require_object_thread(self, "HostUiFacade.refresh")
        now = datetime.datetime.now()
        settings = self._main_window.data_manager.global_settings
        processes: list[dict[str, Any]] = []
        for process in sorted(
            self._main_window.data_manager.managed_processes,
            key=lambda item: ((item.name or "").casefold(), item.id or ""),
        ):
            try:
                state = self._main_window.scheduler.determine_process_visual_status(process, now, settings)
                percent, detail = self._main_window._calculate_progress_percentage(process, now)
            except Exception:
                logger.debug("QML process projection failed: %s", process.id, exc_info=True)
                state, percent, detail = "확인 필요", 0.0, ""
            processes.append(
                {
                    "id": str(process.id),
                    "name": str(process.name or "이름 없음"),
                    "state": str(state or ""),
                    "progress": max(0.0, min(100.0, float(percent or 0.0))),
                    "detail": str(detail or ""),
                }
            )
        if processes != self._processes:
            self._processes = processes
            self.processesChanged.emit()
        dark = bool(self._main_window._is_effective_dark_theme())
        if dark != self._dark_theme:
            self._dark_theme = dark
            self.themeChanged.emit()

    @Slot(str)
    def launchProcess(self, process_id: str) -> None:
        QTimer.singleShot(0, lambda: self._main_window.handle_launch_button_in_row(str(process_id)))

    @Slot()
    def addProcess(self) -> None:
        QTimer.singleShot(0, self._main_window.open_add_process_dialog)

    @Slot()
    def openSettings(self) -> None:
        QTimer.singleShot(0, self._main_window.open_global_settings_dialog)

    @Slot()
    def openRemoteSettings(self) -> None:
        QTimer.singleShot(0, self._main_window.open_remote_settings_dialog)

    @Slot()
    def openDashboard(self) -> None:
        QTimer.singleShot(0, self._main_window._open_dashboard)

    @Slot()
    def hideWindow(self) -> None:
        if self._presentation_window is not None:
            self._presentation_window.hide()

    @Slot()
    def activateAndShow(self) -> None:
        if self._presentation_window is None:
            return
        self._presentation_window.show()
        self._presentation_window.raise_()
        self._presentation_window.requestActivate()

    @Slot()
    def toggleVisibility(self) -> None:
        if self._presentation_window is None:
            return
        if self._presentation_window.isVisible():
            self._presentation_window.hide()
        else:
            self.activateAndShow()
