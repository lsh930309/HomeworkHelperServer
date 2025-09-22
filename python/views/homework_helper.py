import sys
import datetime
import os
import functools
import ctypes
import subprocess
from typing import List, Optional, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QWidget,
    QHeaderView, QPushButton, QSizePolicy, QAbstractItemView,
    QMessageBox, QMenu, QStyle, QStatusBar, QMenuBar, QCheckBox,
    QLabel, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl, QEvent
from PyQt6.QtGui import QAction, QIcon, QColor, QDesktopServices, QFont, QFontDatabase

from .dialogs import ProcessDialog, GlobalSettingsDialog, WebShortcutDialog
from .tray_manager import TrayManager
from .gui_notification_handler import GuiNotificationHandler
from ..controllers.instance_manager import run_with_single_instance_check, SingleInstanceApplication
from ..controllers.utils import get_bundle_resource_path
from ..controllers.api_client import ApiClient
from ..models.data_models import ManagedProcess, GlobalSettings, WebShortcut
from ..controllers.process_utils import get_qicon_for_file
from ..controllers.windows_utils import set_startup_shortcut, get_startup_shortcut_status
from ..controllers.launcher import Launcher
from ..controllers.notifier import Notifier
from ..controllers.scheduler import Scheduler, PROC_STATE_INCOMPLETE, PROC_STATE_COMPLETED, PROC_STATE_RUNNING

def is_admin():
    if not os.name == 'nt': return False
    try: return ctypes.windll.shell32.IsUserAnAdmin() 
    except: return False

class MainWindow(QMainWindow):
    INSTANCE = None
    request_table_refresh_signal = pyqtSignal()

    COLOR_INCOMPLETE, COLOR_COMPLETED, COLOR_RUNNING = QColor("red"), QColor("green"), QColor("yellow")
    COLOR_WEB_BTN_RED, COLOR_WEB_BTN_GREEN = QColor("red"), QColor("green")
    COL_ICON, COL_NAME, COL_LAST_PLAYED, COL_LAUNCH_BTN, COL_STATUS = range(5)

    def __init__(self, api_client: ApiClient, instance_manager: Optional[SingleInstanceApplication] = None):
        super().__init__()
        MainWindow.INSTANCE = self
        self.api_client = api_client
        self._instance_manager = instance_manager
        self.server_process = None
        self._start_server()

        settings_data = self.api_client.get_settings()
        self.global_settings = GlobalSettings.from_dict(settings_data) if settings_data else GlobalSettings()

        self.launcher = Launcher(run_as_admin=self.global_settings.run_as_admin)
        self.setStatusBar(QStatusBar(self))
        self.setMenuBar(QMenuBar(self))

        from ..controllers.process_monitor import ProcessMonitor
        self.process_monitor = ProcessMonitor(self.api_client)
        self.system_notifier = Notifier(QApplication.applicationName())
        self.gui_notification_handler = GuiNotificationHandler(self)
        if hasattr(self.system_notifier, 'main_window_activated_callback'):
            self.system_notifier.main_window_activated_callback = self.gui_notification_handler.process_system_notification_activation

        self.scheduler = Scheduler(self.api_client, self.system_notifier, self.process_monitor)
        self.scheduler.status_change_callback = self.populate_process_list_slot

        self.setWindowTitle(QApplication.applicationName() or "숙제 관리자")
        self.setMinimumWidth(450)
        self.setGeometry(100, 100, 450, 300)
        self._set_window_icon()
        self.tray_manager = TrayManager(self)
        self._create_menu_bar()
        self._add_always_on_top_checkbox()
        self._is_game_mode_active = False

        self._setup_ui()
        self._setup_timers()
        self.apply_startup_setting()
        self.statusBar().showMessage("준비 완료.", 5000)

    def _setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        self.top_button_area_layout = QHBoxLayout()
        self.add_game_button = QPushButton("새 게임 추가")
        self.add_game_button.clicked.connect(self.open_add_process_dialog)
        self.top_button_area_layout.addWidget(self.add_game_button)
        self.top_button_area_layout.addStretch(1)
        self.dynamic_web_buttons_layout = QHBoxLayout()
        self.dynamic_web_buttons_layout.setSpacing(3)
        self.top_button_area_layout.addLayout(self.dynamic_web_buttons_layout)
        self.add_web_shortcut_button = QPushButton("+")
        self.add_web_shortcut_button.setToolTip("새로운 웹 바로 가기 버튼을 추가합니다.")
        font_metrics = self.add_web_shortcut_button.fontMetrics()
        text_width = font_metrics.horizontalAdvance(" + ")
        icon_button_size = text_width + 8
        self.add_web_shortcut_button.setFixedSize(icon_button_size, icon_button_size)
        self.add_web_shortcut_button.clicked.connect(self._open_add_web_shortcut_dialog)
        self.top_button_area_layout.addWidget(self.add_web_shortcut_button)
        self.github_button = QPushButton()
        self.github_button.setToolTip("GitHub 저장소 방문")
        github_icon = QIcon.fromTheme("github", self.style().standardIcon(QStyle.StandardPixmap.SP_CommandLink))
        self.github_button.setIcon(github_icon if not github_icon.isNull() else QIcon())
        if github_icon.isNull(): self.github_button.setText("GH")
        self.github_button.setFixedSize(icon_button_size, icon_button_size)
        self.github_button.clicked.connect(lambda: self.open_webpage("https://github.com/lsh930309/HomeworkHelper"))
        self.top_button_area_layout.addWidget(self.github_button)
        main_layout.addLayout(self.top_button_area_layout)
        self.process_table = QTableWidget(columnCount=self.COL_STATUS + 1)
        self.process_table.setHorizontalHeaderLabels(["", "이름", "진행률", "실행", "상태"])
        self._configure_table_header()
        self.process_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.process_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.process_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.process_table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.process_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.process_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.process_table.verticalHeader().setDefaultSectionSize(30)
        main_layout.addWidget(self.process_table)
        self.populate_process_list()
        self._load_and_display_web_buttons()
        self._adjust_window_height_for_table_rows()
        self._apply_window_resize_lock()

    def _setup_timers(self):
        self.request_table_refresh_signal.connect(self.populate_process_list_slot)
        self.monitor_timer = QTimer(self); self.monitor_timer.timeout.connect(self.run_process_monitor_check); self.monitor_timer.start(1000)
        self.scheduler_timer = QTimer(self); self.scheduler_timer.timeout.connect(self.run_scheduler_check); self.scheduler_timer.start(1000)
        self.web_button_refresh_timer = QTimer(self); self.web_button_refresh_timer.timeout.connect(self._refresh_web_button_states); self.web_button_refresh_timer.start(60000)
        self.status_column_refresh_timer = QTimer(self); self.status_column_refresh_timer.timeout.connect(self.update_process_statuses_only); self.status_column_refresh_timer.start(30000)
        self.progress_bar_refresh_timer = QTimer(self); self.progress_bar_refresh_timer.timeout.connect(self._refresh_progress_bars); self.progress_bar_refresh_timer.start(1000)

    def _start_server(self):
        if self.server_process: return
        try:
            command = [sys.executable, "-m", "uvicorn", "python.controllers.create_server:app", "--host", "127.0.0.1", "--port", "8000"]
            creation_flags = subprocess.CREATE_NO_WINDOW if getattr(sys, 'frozen', False) and os.name == 'nt' else 0
            self.server_process = subprocess.Popen(command, creationflags=creation_flags)
        except Exception as e:
            QMessageBox.critical(self, "Server Error", f"Could not start local server: {e}")

    def _stop_server(self):
        if self.server_process:
            self.server_process.terminate()
            self.server_process.wait()
            self.server_process = None

    def initiate_quit_sequence(self):
        self._stop_server()
        for timer in [self.monitor_timer, self.scheduler_timer, self.web_button_refresh_timer, self.status_column_refresh_timer, self.progress_bar_refresh_timer]:
            if timer.isActive(): timer.stop()
        if self.tray_manager: self.tray_manager.hide_tray_icon()
        if self._instance_manager: self._instance_manager.cleanup()
        QApplication.instance().quit()

    def populate_process_list_slot(self):
        self.populate_process_list()

    def populate_process_list(self):
        self.process_table.setSortingEnabled(False)
        processes_data = self.api_client.get_processes()
        self.process_table.setRowCount(len(processes_data))
        now_dt = datetime.datetime.now()
        for r, p_data in enumerate(processes_data):
            self._update_table_row(r, ManagedProcess.from_dict(p_data), now_dt, self.global_settings)
        self.process_table.setSortingEnabled(True)
        self.process_table.resizeColumnsToContents()
        self.process_table.horizontalHeader().setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        self._adjust_window_height_for_table_rows()

    def _update_table_row(self, r: int, p: ManagedProcess, now_dt: datetime.datetime, gs: GlobalSettings):
        icon_item = QTableWidgetItem()
        qi = get_qicon_for_file(p.monitoring_path)
        if qi and not qi.isNull(): icon_item.setIcon(qi)
        self.process_table.setItem(r, self.COL_ICON, icon_item)
        name_item = QTableWidgetItem(p.name)
        name_item.setData(Qt.ItemDataRole.UserRole, p.id)
        self.process_table.setItem(r, self.COL_NAME, name_item)
        percentage, time_str = self._calculate_progress_percentage(p, now_dt)
        self.process_table.setCellWidget(r, self.COL_LAST_PLAYED, self._create_progress_bar_widget(percentage, time_str))
        btn = QPushButton("실행")
        btn.clicked.connect(functools.partial(self.handle_launch_button_in_row, p.id))
        self.process_table.setCellWidget(r, self.COL_LAUNCH_BTN, btn)
        st_str = self.scheduler.determine_process_visual_status(p, now_dt, gs)
        st_item = QTableWidgetItem(st_str)
        st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if st_str == PROC_STATE_RUNNING: st_item.setBackground(self.COLOR_RUNNING); st_item.setForeground(QColor("black"))
        elif st_str == PROC_STATE_INCOMPLETE: st_item.setBackground(self.COLOR_INCOMPLETE)
        else: st_item.setBackground(self.COLOR_COMPLETED)
        self.process_table.setItem(r, self.COL_STATUS, st_item)

    def handle_edit_action_for_row(self, pid: str):
        p_data = self.api_client.get_process_by_id(pid)
        if not p_data: return
        dialog = ProcessDialog(self, existing_process=ManagedProcess.from_dict(p_data))
        if dialog.exec():
            data = dialog.get_data()
            if data and self.api_client.update_process(pid, data):
                self.populate_process_list()

    def handle_delete_action_for_row(self, pid: str):
        p_data = self.api_client.get_process_by_id(pid)
        if not p_data: return
        if QMessageBox.question(self, "삭제 확인", f"'{p_data['name']}' 삭제?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.api_client.delete_process(pid): self.populate_process_list()

    def handle_launch_button_in_row(self, pid: str):
        p_data = self.api_client.get_process_by_id(pid)
        if not p_data or not p_data.get('launch_path'): return
        if self.launcher.launch_process(p_data['launch_path']):
            if self.global_settings.notify_on_launch_success: self.system_notifier.send_notification(title="프로세스 실행", message=f"'{p_data['name']}' 실행함.")
            self.update_process_statuses_only()
        elif self.global_settings.notify_on_launch_failure: self.system_notifier.send_notification(title="실행 실패", message=f"'{p_data['name']}' 실행 실패. 로그 확인.")

    def open_add_process_dialog(self):
        dialog = ProcessDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if data:
                if not data.get("name") and data.get("monitoring_path"): data["name"] = os.path.splitext(os.path.basename(data["monitoring_path"]))[0]
                if self.api_client.create_process(data): self.populate_process_list()

    def open_global_settings_dialog(self):
        dlg = GlobalSettingsDialog(self.global_settings, self)
        if dlg.exec():
            upd_gs = dlg.get_updated_settings()
            if self.api_client.update_settings(upd_gs.to_dict()):
                self.global_settings = upd_gs
                self.launcher.run_as_admin = upd_gs.run_as_admin
                self.apply_startup_setting()
                self.populate_process_list()
                self._update_window_resize_lock()

    def _toggle_always_on_top(self, checked: bool):
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint if checked else self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()
        self.global_settings.always_on_top = checked
        self.api_client.update_settings(self.global_settings.to_dict())

    def _load_always_on_top_setting(self):
        self.always_on_top_checkbox.setChecked(self.global_settings.always_on_top)
        if self.global_settings.always_on_top: self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    def apply_startup_setting(self):
        set_startup_shortcut(self.global_settings.run_on_startup)

    def run_process_monitor_check(self):
        if self.process_monitor.check_and_update_statuses(): self.update_process_statuses_only()
        self._check_and_toggle_game_mode()

    def _check_and_toggle_game_mode(self):
        processes_data = self.api_client.get_processes()
        if not processes_data: return
        any_game_running = any(self.scheduler.determine_process_visual_status(ManagedProcess.from_dict(p), datetime.datetime.now(), self.global_settings) == PROC_STATE_RUNNING for p in processes_data)
        if any_game_running and not self._is_game_mode_active:
            self._is_game_mode_active = True
            self.tray_manager.handle_minimize_event()
        elif not any_game_running and self._is_game_mode_active:
            self._is_game_mode_active = False
            self.activate_and_show()

    def run_scheduler_check(self):
        if self.scheduler.run_all_checks(): self.update_process_statuses_only()

    def update_process_statuses_only(self):
        if not hasattr(self, 'process_table'): return
        processes_data = self.api_client.get_processes()
        if self.process_table.rowCount() != len(processes_data): self.populate_process_list(); return
        now_dt = datetime.datetime.now()
        for r in range(self.process_table.rowCount()):
            pid = self.process_table.item(r, self.COL_NAME).data(Qt.ItemDataRole.UserRole)
            p_data = next((p for p in processes_data if p['id'] == pid), None)
            if p_data: self._update_table_row(r, ManagedProcess.from_dict(p_data), now_dt, self.global_settings)

    def _load_and_display_web_buttons(self):
        self._clear_layout(self.dynamic_web_buttons_layout)
        shortcuts = self.api_client.get_shortcuts()
        for sc_data in shortcuts:
            button = QPushButton(sc_data['name'])
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            button.clicked.connect(functools.partial(self._handle_web_button_clicked, sc_data['id'], sc_data['url']))
            button.setProperty("shortcut_id", sc_data['id'])
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(functools.partial(self._show_web_button_context_menu, button))
            self._apply_button_style(button, self._determine_web_button_state(WebShortcut.from_dict(sc_data), datetime.datetime.now()))
            self.dynamic_web_buttons_layout.addWidget(button)
        self._adjust_window_width_for_web_buttons()

    def _handle_web_button_clicked(self, shortcut_id: str, url: str):
        self.open_webpage(url)
        shortcuts = self.api_client.get_shortcuts()
        shortcut_data = next((sc for sc in shortcuts if sc['id'] == shortcut_id), None)
        if shortcut_data:
            shortcut = WebShortcut.from_dict(shortcut_data)
            if shortcut.refresh_time_str:
                shortcut.last_reset_timestamp = datetime.datetime.now().timestamp()
                if self.api_client.update_shortcut(shortcut.id, shortcut.to_dict()):
                    self._refresh_web_button_states()

    def _open_add_web_shortcut_dialog(self):
        dialog = WebShortcutDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if data and self.api_client.create_shortcut(data):
                self._load_and_display_web_buttons()

    def _edit_web_shortcut(self, shortcut_id: str):
        sc_data = self.api_client.get_shortcut_by_id(shortcut_id)
        if not sc_data: return
        dialog = WebShortcutDialog(self, shortcut_data=sc_data)
        if dialog.exec():
            data = dialog.get_data()
            if data and self.api_client.update_shortcut(shortcut_id, data):
                self._load_and_display_web_buttons()

    def _delete_web_shortcut(self, shortcut_id: str):
        sc_data = self.api_client.get_shortcut_by_id(shortcut_id)
        if not sc_data: return
        if QMessageBox.question(self, "삭제 확인", f"'{sc_data['name']}' 삭제?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.api_client.delete_shortcut(shortcut_id): self._load_and_display_web_buttons()

    def _refresh_web_button_states(self):
        current_dt = datetime.datetime.now()
        for i in range(self.dynamic_web_buttons_layout.count()):
            widget = self.dynamic_web_buttons_layout.itemAt(i).widget()
            if isinstance(widget, QPushButton):
                shortcut_id = widget.property("shortcut_id")
                if shortcut_id:
                    sc_data = self.api_client.get_shortcut_by_id(shortcut_id)
                    if sc_data: self._apply_button_style(widget, self._determine_web_button_state(WebShortcut.from_dict(sc_data), current_dt))

    def _refresh_progress_bars(self):
        now_dt = datetime.datetime.now()
        processes_data = self.api_client.get_processes()
        managed_processes = {p['id']: ManagedProcess.from_dict(p) for p in processes_data}
        for row in range(self.process_table.rowCount()):
            pid = self.process_table.item(row, self.COL_NAME).data(Qt.ItemDataRole.UserRole)
            if pid in managed_processes:
                process = managed_processes[pid]
                percentage, time_str = self._calculate_progress_percentage(process, now_dt)
                current_widget = self.process_table.cellWidget(row, self.COL_LAST_PLAYED)
                if isinstance(current_widget, QProgressBar):
                    current_widget.setValue(int(percentage))
                    current_widget.setFormat(f"{percentage:.1f}%")
                elif isinstance(current_widget, QLabel):
                    current_widget.setText(time_str)

    # All other methods are included below, fully implemented...
    def changeEvent(self, event: QEvent):
        if event.type() == QEvent.Type.WindowStateChange and self.windowState() & Qt.WindowState.WindowMinimized:
            if hasattr(self, 'tray_manager') and self.tray_manager.is_tray_icon_visible():
                self.tray_manager.handle_minimize_event()
        super().changeEvent(event)

    def activate_and_show(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def open_webpage(self, url: str):
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "URL 열기 실패", f"다음 URL을 여는 데 실패했습니다:\n{url}")

    def _set_window_icon(self):
        icon_path_ico = get_bundle_resource_path(r"img\app_icon.ico")
        if os.path.exists(icon_path_ico):
            icon = QIcon(icon_path_ico)
            if not icon.isNull():
                self.setWindowIcon(icon)
                return
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))

    def _configure_table_header(self):
        h = self.process_table.horizontalHeader()
        h.setSectionResizeMode(self.COL_ICON, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(self.COL_LAST_PLAYED, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(self.COL_LAUNCH_BTN, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)

    def _create_menu_bar(self):
        mb = self.menuBar()
        fm = mb.addMenu("파일(&F)")
        ei = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        ea = QAction(QIcon.fromTheme("application-exit", ei), "종료(&X)", self)
        ea.setShortcut("Ctrl+Q")
        ea.triggered.connect(self.initiate_quit_sequence)
        fm.addAction(ea)
        sm = mb.addMenu("설정(&S)")
        gsa = QAction("전역 설정 변경...", self)
        gsa.triggered.connect(self.open_global_settings_dialog)
        sm.addAction(gsa)

    def _add_always_on_top_checkbox(self):
        menu_bar = self.menuBar()
        right_widget = QWidget()
        right_layout = QHBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.always_on_top_checkbox = QCheckBox("항상 위")
        self.always_on_top_checkbox.toggled.connect(self._toggle_always_on_top)
        right_layout.addWidget(self.always_on_top_checkbox)
        menu_bar.setCornerWidget(right_widget, Qt.Corner.TopRightCorner)
        self._load_always_on_top_setting()

    def show_table_context_menu(self, pos):
        item = self.process_table.itemAt(pos)
        if not item: return
        pid = self.process_table.item(item.row(), self.COL_NAME).data(Qt.ItemDataRole.UserRole)
        if not pid: return
        menu = QMenu(self)
        edit_act = QAction("편집", self)
        del_act = QAction("삭제", self)
        edit_act.triggered.connect(functools.partial(self.handle_edit_action_for_row, pid))
        del_act.triggered.connect(functools.partial(self.handle_delete_action_for_row, pid))
        menu.addActions([edit_act, del_act])
        menu.exec(self.process_table.mapToGlobal(pos))

    def _clear_layout(self, layout: QHBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()

    def _determine_web_button_state(self, shortcut: WebShortcut, current_dt: datetime.datetime) -> str:
        if not shortcut.refresh_time_str: return "DEFAULT"
        try: rt_hour, rt_minute = map(int, shortcut.refresh_time_str.split(':'))
        except (ValueError, TypeError): return "DEFAULT"
        refresh_time_today = datetime.time(rt_hour, rt_minute)
        todays_refresh_dt = datetime.datetime.combine(current_dt.date(), refresh_time_today)
        last_reset_dt = datetime.datetime.fromtimestamp(shortcut.last_reset_timestamp) if shortcut.last_reset_timestamp else None
        if current_dt >= todays_refresh_dt:
            return "RED" if last_reset_dt is None or last_reset_dt < todays_refresh_dt else "GREEN"
        else:
            yesterdays_refresh_dt = todays_refresh_dt - datetime.timedelta(days=1)
            return "GREEN" if last_reset_dt and last_reset_dt >= yesterdays_refresh_dt else "DEFAULT"

    def _apply_button_style(self, button: QPushButton, state: str):
        button.setStyleSheet("")
        if state == "RED": button.setStyleSheet(f"background-color: {self.COLOR_WEB_BTN_RED.name()};")
        elif state == "GREEN": button.setStyleSheet(f"background-color: {self.COLOR_WEB_BTN_GREEN.name()};")

    def _show_web_button_context_menu(self, button: QPushButton, position):
        shortcut_id = button.property("shortcut_id")
        if not shortcut_id: return
        menu = QMenu(self)
        edit_action = QAction("편집", self)
        delete_action = QAction("삭제", self)
        edit_action.triggered.connect(functools.partial(self._edit_web_shortcut, shortcut_id))
        delete_action.triggered.connect(functools.partial(self._delete_web_shortcut, shortcut_id))
        menu.addActions([edit_action, delete_action])
        menu.exec(button.mapToGlobal(position))

    def closeEvent(self, event: QEvent):
        if self.tray_manager: self.tray_manager.handle_window_close_event(event)
        else: event.ignore(); self.hide()

    def _adjust_window_height_for_table_rows(self):
        header_height = self.process_table.horizontalHeader().height()
        content_height = sum(self.process_table.rowHeight(r) for r in range(self.process_table.rowCount()))
        total_height = header_height + content_height + (self.process_table.frameWidth() * 2)
        self.process_table.setFixedHeight(total_height if total_height > 50 else 50)
        self.resize(self.width(), self.sizeHint().height())

    def _adjust_window_width_for_web_buttons(self):
        self.resize(self.sizeHint().width(), self.height())

    def _apply_window_resize_lock(self):
        if self.global_settings.lock_window_resize:
            self.setFixedSize(self.size())
        else:
            self.setMinimumSize(300, 0)
            self.setMaximumSize(16777215, 16777215)

    def _update_window_resize_lock(self):
        self._apply_window_resize_lock()

    def _calculate_progress_percentage(self, process: ManagedProcess, current_dt: datetime.datetime) -> tuple[float, str]:
        if not process.last_played_timestamp or not process.user_cycle_hours: return 0.0, "기록 없음"
        try: 
            elapsed_hours = (current_dt - datetime.datetime.fromtimestamp(process.last_played_timestamp)).total_seconds() / 3600
            progress = min(elapsed_hours / process.user_cycle_hours, 1.0)
            return progress * 100, ""
        except Exception: return 0.0, "계산 오류"

    def _create_progress_bar_widget(self, percentage: float, time_str: str) -> QWidget:
        if percentage == 0.0: return QLabel(time_str)
        progress_bar = QProgressBar()
        progress_bar.setValue(int(percentage))
        progress_bar.setFormat(f"{percentage:.1f}%")
        # Styling based on percentage can be added here
        return progress_bar

def start_main_application(instance_manager: SingleInstanceApplication):
    app = QApplication(sys.argv)
    app.setApplicationName("숙제 관리자")
    app.setOrganizationName("HomeworkHelperOrg")

    if os.name == 'nt': print(f"현재 실행 상태: {'관리자' if is_admin() else '일반 사용자'}")

    font_path_ttf = get_bundle_resource_path(r"font\NEXONLv1GothicOTFBold.otf")
    if os.path.exists(font_path_ttf):
        font_id = QFontDatabase.addApplicationFont(font_path_ttf)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            app.setFont(QFont(font_family, 10))

    app.setQuitOnLastWindowClosed(False)
    api_client_instance = ApiClient()
    main_window = MainWindow(api_client_instance, instance_manager=instance_manager)
    instance_manager.start_ipc_server(main_window_to_activate=main_window)
    main_window.show()
    sys.exit(app.exec())

# This file is a module and should not be run directly.
# Use run.pyw in the project root to start the application.
