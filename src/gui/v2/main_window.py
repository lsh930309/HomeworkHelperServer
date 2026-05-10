"""Prototype-inspired PyQt v2 main window.

The class deliberately subclasses the v1 ``MainWindow`` so every runtime feature
(process monitor, scheduler, HoYoLab reconciliation, screenshots, recording,
Beholder, tray, sidebar, AppData contract) remains one-to-one.  v2 only changes
the presentation and build-selected entry behavior.
"""

from __future__ import annotations

import functools
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.instance_manager import SingleInstanceApplication
from src.api.client import ApiClient
from src.core.scheduler import PROC_STATE_COMPLETED, PROC_STATE_INCOMPLETE, PROC_STATE_RUNNING
from src.gui.main_window import MainWindow
from src.gui.v2.settings_dialog import SettingsDialogV2
from src.gui.v2.theme import build_v2_qss, palette_for_theme, progress_chunk_color


class V2StatusBanner(QFrame):
    """Compact status banner with progressive disclosure for long messages."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._message_serial = 0
        self.setObjectName("V2MessageBanner")
        self.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("V2BannerSummary")
        self.summary_label.setWordWrap(False)
        self.detail_button = QToolButton()
        self.detail_button.setText("자세히")
        self.detail_button.setCheckable(True)
        self.detail_button.setVisible(False)
        self.detail_button.toggled.connect(self._set_detail_visible)
        top.addWidget(self.summary_label, 1)
        top.addWidget(self.detail_button)
        layout.addLayout(top)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("V2BannerDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(False)
        layout.addWidget(self.detail_label)

    def show_message(self, message: str, timeout_ms: int = 5000) -> None:
        if not message:
            return
        self._message_serial += 1
        message_serial = self._message_serial
        summary = message.replace("\n", " ").strip()
        detail = message.strip()
        needs_detail = len(summary) > 86 or "\n" in message
        if len(summary) > 86:
            summary = summary[:83].rstrip() + "..."
        self.summary_label.setText(summary)
        self.detail_label.setText(detail)
        self.detail_button.setVisible(needs_detail)
        self.detail_button.setChecked(False)
        self.detail_label.setVisible(False)
        self.setVisible(True)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, functools.partial(self._hide_if_current, message_serial))

    def _set_detail_visible(self, visible: bool) -> None:
        self.detail_label.setVisible(visible)

    def _hide_if_current(self, message_serial: int) -> None:
        if message_serial == self._message_serial:
            self.hide()


class V2MainWindow(MainWindow):
    """v2 GUI using v1 as the functional substrate."""

    V2_WIDTH = 640

    def __init__(
        self,
        data_manager: ApiClient,
        instance_manager: Optional[SingleInstanceApplication] = None,
    ):
        self._v2_status_banner: V2StatusBanner | None = None
        super().__init__(data_manager, instance_manager=instance_manager)
        self._install_v2_shell()
        self._apply_v2_visual_system()
        self.populate_process_list()
        self._load_and_display_web_buttons()
        self._adjust_window_height_for_table_rows()

    def _install_v2_shell(self) -> None:
        self.setObjectName("HomeworkHelperV2")
        self.setWindowTitle("숙제 관리자 v2")
        # Report decision: preserve the OS title bar for robust move/resize,
        # taskbar, accessibility, and DPI behavior.
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.FramelessWindowHint)
        self.setMinimumWidth(self.V2_WIDTH)
        self.setFixedWidth(self.V2_WIDTH)

        central = self.centralWidget()
        if central:
            central.setObjectName("V2Central")
            layout = central.layout()
            if isinstance(layout, QVBoxLayout):
                layout.setContentsMargins(12, 10, 12, 10)
                layout.setSpacing(10)

                self._v2_shell_frame = QFrame(central)
                self._v2_shell_frame.setObjectName("V2ShellFrame")
                self._v2_shell_layout = QVBoxLayout(self._v2_shell_frame)
                self._v2_shell_layout.setContentsMargins(12, 12, 12, 12)
                self._v2_shell_layout.setSpacing(10)

                while layout.count():
                    item = layout.takeAt(0)
                    if item is None:
                        continue
                    if item.layout():
                        self._v2_shell_layout.addLayout(item.layout())
                    elif item.widget():
                        self._v2_shell_layout.addWidget(item.widget())

                layout.addWidget(self._v2_shell_frame)

        self._upgrade_topbar()
        self._v2_status_banner = V2StatusBanner(self)
        if hasattr(self, "_v2_shell_layout"):
            self._v2_shell_layout.insertWidget(1, self._v2_status_banner)
        status = self.statusBar()
        if status:
            status.messageChanged.connect(self._on_statusbar_message_changed)

    def _upgrade_topbar(self) -> None:
        if not hasattr(self, "top_button_area_layout"):
            return

        brand_box = QFrame(self)
        brand_box.setObjectName("V2Topbar")
        brand_layout = QHBoxLayout(brand_box)
        brand_layout.setContentsMargins(10, 7, 10, 7)
        brand_layout.setSpacing(8)

        title_group = QVBoxLayout()
        title_group.setContentsMargins(0, 0, 0, 0)
        title_group.setSpacing(0)
        brand = QLabel("HOMEWORK HELPER")
        brand.setObjectName("V2Brand")
        title = QLabel("숙제 관리자 v2")
        title.setObjectName("V2Title")
        subtitle = QLabel("prototype 감성 · PyQt 안정성 · v1 기능 1:1 유지")
        subtitle.setObjectName("V2Subtitle")
        title_group.addWidget(brand)
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        brand_layout.addLayout(title_group, 1)

        settings_button = QToolButton()
        settings_button.setObjectName("V2IconButton")
        settings_button.setText("⚙")
        settings_button.setToolTip("v2 통합 설정 열기")
        settings_button.clicked.connect(self.open_global_settings_dialog)
        brand_layout.addWidget(settings_button)

        target_layout = self.top_button_area_layout
        target_layout.insertWidget(0, brand_box, 1)

        self.add_game_button.setText("+ 게임")
        self.add_game_button.setObjectName("V2PrimaryButton")
        self.add_web_shortcut_button.setText("+ 웹")
        self.add_web_shortcut_button.setObjectName("V2IconButton")
        self.dashboard_button.setObjectName("V2IconButton")
        self.github_button.setObjectName("V2IconButton")
        if hasattr(self, "_volume_btn"):
            self._volume_btn.setObjectName("V2IconButton")

    def _apply_v2_visual_system(self) -> None:
        theme = getattr(self.data_manager.global_settings, "theme", "system")
        self.setStyleSheet(build_v2_qss(theme))
        p = palette_for_theme(theme)
        self.COLOR_INCOMPLETE = QColor(p.danger)
        self.COLOR_COMPLETED = QColor(p.good)
        self.COLOR_RUNNING = QColor(p.warn)
        self.COLOR_WEB_BTN_RED = QColor(p.danger)
        self.COLOR_WEB_BTN_GREEN = QColor(p.good)
        if hasattr(self, "process_table"):
            self.process_table.setObjectName("V2ProcessTable")
            self.process_table.setAlternatingRowColors(False)
            self.process_table.setShowGrid(False)
            self.process_table.setWordWrap(False)
            self.process_table.verticalHeader().setVisible(False)
            self.process_table.horizontalHeader().setVisible(True)
            self.process_table.setColumnWidth(self.COL_ICON, 34)
            self.process_table.setColumnWidth(self.COL_LAUNCH_BTN, 58)
            self._apply_v2_status_visibility()

    def _apply_v2_status_visibility(self) -> None:
        """Keep v1 status data but make v2 default to visual status signals."""

        if not hasattr(self, "process_table"):
            return
        self.process_table.setColumnHidden(self.COL_STATUS, True)

    def _open_settings_hub(self, initial_tab: str | int = 0):
        latest_settings = self.data_manager.global_settings
        previous_run_as_admin = latest_settings.run_as_admin
        dlg = SettingsDialogV2(latest_settings, self, initial_tab=initial_tab)
        if dlg.exec():
            updated = self.data_manager.global_settings
            if previous_run_as_admin != updated.run_as_admin:
                self._handle_v2_admin_transition(updated.run_as_admin)

    def open_global_settings_dialog(self):
        """Open the v2 single-popup settings hub."""

        self._open_settings_hub(0)

    def open_sidebar_settings_dialog(self) -> None:
        """Route v1's sidebar settings entry to the v2 settings hub."""

        self._open_settings_hub("사이드바")

    def open_hoyolab_settings_dialog(self):
        """Route v1's HoYoLab settings entry to the v2 settings hub."""

        self._open_settings_hub("HoYoLab")

    def _handle_v2_admin_transition(self, wants_admin: bool) -> None:
        from src.utils.admin import is_admin, restart_as_normal, run_as_admin

        if wants_admin and not is_admin():
            if run_as_admin():
                try:
                    import homework_helper
                    homework_helper._restart_in_progress = True
                except Exception:
                    pass
                QApplication.quit()
            else:
                updated = self.data_manager.global_settings
                updated.run_as_admin = False
                self.data_manager.save_global_settings(updated, actor="main_gui_settings")
                QMessageBox.warning(self, "관리자 권한 전환 실패", "관리자 권한으로 재시작하지 못해 설정을 롤백했습니다.")
        elif not wants_admin and is_admin():
            if restart_as_normal():
                try:
                    import homework_helper
                    homework_helper._restart_in_progress = True
                except Exception:
                    pass
                QApplication.quit()
            else:
                QMessageBox.information(self, "권한 전환 안내", "일반 권한으로 재시작하지 못했습니다. 앱을 수동으로 재시작해 주세요.")

    def populate_process_list(self):
        super().populate_process_list()
        self._decorate_v2_process_rows()

    def update_process_statuses_only(self):
        super().update_process_statuses_only()
        self._decorate_v2_process_rows()

    def _decorate_v2_process_rows(self) -> None:
        if not hasattr(self, "process_table"):
            return
        self._apply_v2_status_visibility()
        palette = palette_for_theme(getattr(self.data_manager.global_settings, "theme", "system"))
        for row in range(self.process_table.rowCount()):
            status_item = self.process_table.item(row, self.COL_STATUS)
            icon_item = self.process_table.item(row, self.COL_ICON)
            name_item = self.process_table.item(row, self.COL_NAME)
            status_text = status_item.text() if status_item else ""
            color = palette.line
            if status_text == PROC_STATE_RUNNING:
                color = palette.warn
            elif status_text == PROC_STATE_INCOMPLETE:
                color = palette.danger
            elif status_text == PROC_STATE_COMPLETED:
                color = palette.good

            if icon_item:
                icon_item.setBackground(QColor(color))
                icon_item.setToolTip(f"상태: {status_text or '알 수 없음'}")
                icon_item.setWhatsThis(f"v2 상태 인디케이터: {status_text or '알 수 없음'}")
            if name_item:
                name_item.setToolTip(f"{name_item.text()} · {status_text}")
                name_item.setWhatsThis(f"{name_item.text()} 상태: {status_text}")
            if status_item:
                status_item.setToolTip(f"상태 텍스트는 v2에서 숨겨져 있으며, 현재 상태는 {status_text}입니다.")
                status_item.setWhatsThis(f"숨겨진 v1 호환 상태 컬럼: {status_text}")
            button = self.process_table.cellWidget(row, self.COL_LAUNCH_BTN)
            if isinstance(button, QPushButton):
                button.setText("▶")
                button.setObjectName("V2PrimaryButton")
                process_id = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
                process = self.data_manager.get_process_by_id(process_id) if process_id else None
                if process:
                    launch_type = getattr(process, "preferred_launch_type", "shortcut") or "shortcut"
                    button.setToolTip(f"{process.name} 실행 · 방식: {launch_type}")

    def _apply_button_style(self, button: QPushButton, state: str):
        button.setStyleSheet("")
        state_name = {"RED": "due", "GREEN": "done"}.get(state, "default")
        button.setProperty("v2State", state_name)
        button.style().unpolish(button)
        button.style().polish(button)

    def _load_and_display_web_buttons(self):
        super()._load_and_display_web_buttons()
        if hasattr(self, "dynamic_web_buttons_layout"):
            for i in range(self.dynamic_web_buttons_layout.count()):
                item = self.dynamic_web_buttons_layout.itemAt(i)
                widget = item.widget() if item else None
                if isinstance(widget, QPushButton):
                    widget.setToolTip((widget.toolTip() + "\n" if widget.toolTip() else "") + "우클릭: 편집/삭제")

    def _progress_bar_stylesheet(self, chunk_color: str) -> str:
        theme = getattr(self.data_manager.global_settings, "theme", "system")
        palette = palette_for_theme(theme)
        return f"""
            QProgressBar {{
                border: 1px solid {palette.line};
                border-radius: 9px;
                text-align: center;
                background-color: {palette.input_bg};
                color: {palette.text};
                font-weight: 800;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color};
                border-radius: 8px;
            }}
        """

    def _apply_progress_bar_style(self, progress_bar, percentage: float) -> None:
        theme = getattr(self.data_manager.global_settings, "theme", "system")
        progress_bar.setStyleSheet(self._progress_bar_stylesheet(progress_chunk_color(percentage, theme)))

    def _on_statusbar_message_changed(self, message: str) -> None:
        if self._v2_status_banner and message:
            self._v2_status_banner.show_message(message)

    def _adjust_window_width_for_web_buttons(self):
        # v2 keeps a wider compact shell and wraps visual density inside the
        # topbar instead of shrinking below the v2 card-list width.
        self.setFixedWidth(self.V2_WIDTH)

    def _adjust_window_size_to_content(self):
        super()._adjust_window_size_to_content()
        self.setFixedWidth(self.V2_WIDTH)

    def _adjust_window_height_for_table_rows(self):
        super()._adjust_window_height_for_table_rows()
        self.setFixedWidth(self.V2_WIDTH)
