import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel

from src.data.data_models import (
    GlobalSettings,
    ManagedProcess,
    WebShortcut,
    SIDEBAR_MODE_ALWAYS,
    SIDEBAR_MODE_DISABLED,
    SIDEBAR_MODE_GAME,
)
from src.core.process_monitor import ProcessMonitorTickResult
import src.gui.sidebar.edge_trigger_window as edge_trigger_module
from src.gui.sidebar.edge_trigger_window import EdgeTriggerWindow


class _Noop:
    def __init__(self, *_args, **_kwargs):
        pass

    def __getattr__(self, _name):
        def _noop(*_args, **_kwargs):
            return None

        return _noop


class _FakeApiClient:
    def __init__(self, processes):
        self.managed_processes = processes
        self.web_shortcuts = []
        self.global_settings = GlobalSettings(
            run_on_startup=False,
            run_as_admin=False,
            sidebar_enabled=False,
            screenshot_enabled=False,
            screenshot_gamepad_trigger=False,
            recording_enabled=False,
        )

    def get_process_by_id(self, process_id):
        return next((p for p in self.managed_processes if p.id == process_id), None)

    def get_web_shortcut_by_id(self, shortcut_id):
        return next((s for s in self.web_shortcuts if s.id == shortcut_id), None)

    def pop_latest_beholder_incident(self):
        return None

    def get_active_beholder_incidents(self):
        return []

    def get_beholder_backups(self):
        return []

    def send_runtime_heartbeat(self, **_kwargs):
        return None

    def reconcile_open_sessions(self, _running_ids):
        return []

    def save_global_settings(self, settings, actor=None):
        self.global_settings = settings
        return True


def _qapp():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("HomeworkHelper Test")
    return app


def _patch_main_window_deps(monkeypatch, tmp_path):
    import src.gui.main_window as main_window

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(main_window.IconDownloader, "start", lambda self: None)
    monkeypatch.setattr(main_window, "TrayManager", _Noop)
    monkeypatch.setattr(main_window, "Notifier", _Noop)
    monkeypatch.setattr(main_window, "SidebarController", _Noop)
    monkeypatch.setattr(main_window.GamePresetManager, "USER_CONFIG_DIR", tmp_path / "HomeworkHelper")
    monkeypatch.setattr(
        main_window.GamePresetManager,
        "USER_PRESET_FILE",
        tmp_path / "HomeworkHelper" / "game_presets_user.json",
    )
    return main_window


def test_global_settings_derives_sidebar_mode_from_legacy_bool():
    disabled = GlobalSettings(sidebar_enabled=False)
    assert disabled.sidebar_mode == SIDEBAR_MODE_DISABLED
    assert disabled.sidebar_enabled is False

    restored = GlobalSettings.from_dict({"sidebar_enabled": True, "sidebar_mode": SIDEBAR_MODE_ALWAYS})
    assert restored.sidebar_mode == SIDEBAR_MODE_ALWAYS
    assert restored.sidebar_enabled is True
    assert restored.sidebar_handle_auto_hide is True

    ranged = GlobalSettings.from_dict({
        "sidebar_trigger_y_start": 0.8,
        "sidebar_trigger_y_end": 0.2,
        "sidebar_handle_auto_hide": False,
    })
    assert ranged.sidebar_trigger_y_start == 0.2
    assert ranged.sidebar_trigger_y_end == 0.8
    assert ranged.sidebar_handle_auto_hide is False

    remote_default = GlobalSettings.from_dict({})
    assert remote_default.remote_server_mode_enabled is False
    remote_enabled = GlobalSettings.from_dict({"remote_server_mode_enabled": True})
    assert remote_enabled.remote_server_mode_enabled is True


def test_main_window_settings_menu_exposes_remote_settings_dialog():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")
    dialog_source = Path("src/gui/dialogs.py").read_text(encoding="utf-8")

    assert 'QAction("원격 설정...", self)' in source
    assert "open_remote_settings_dialog" in source
    assert "RemoteSettingsDialog" in source
    assert 'QAction("리모트 페어링 코드 발급(&P)", self)' not in source
    assert '/remote/pair/start' in source
    assert "class RemoteSettingsDialog" in dialog_source
    assert "remote_server_mode_checkbox" in dialog_source
    assert "devices_table" in dialog_source
    assert "tailscale_health_text" in dialog_source
    assert "smartthings_device_id_edit" in dialog_source
    assert "power_setup_text" in dialog_source
    assert "/remote/power/setup" in dialog_source
    assert "/remote/power/ssh-key" in dialog_source
    assert "/remote/power/smartthings/devices" in dialog_source
    assert "SSH public key 승인/등록" in dialog_source
    assert "전원 상태/승인 패널" in dialog_source
    assert "mac 클라이언트의 6자리 PIN 흐름" in dialog_source
    assert "smartthings_device_combo" in dialog_source
    assert "선택 device id 적용" in dialog_source


def test_main_window_uses_icon_only_remote_readiness_indicators():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")

    assert "showMessage(" not in source
    assert '("beholder", "●")' in source
    assert '("remote", "●")' in source
    assert '("admin", "●")' in source
    assert "remoteReadiness_server" not in source
    assert "remoteReadiness_power" not in source
    assert "remoteReadiness_tailscale" not in source
    assert "QGraphicsDropShadowEffect" in source


def test_global_settings_dialog_exposes_remote_server_mode_and_bind_logic_is_settings_backed():
    dialog_source = Path("src/gui/dialogs.py").read_text(encoding="utf-8")
    launcher_source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert "remote_server_mode_checkbox" in dialog_source
    assert "remote_server_mode_enabled" in dialog_source
    assert "def resolve_api_bind_host" in launcher_source
    assert '"0.0.0.0"' in launcher_source
    assert "remote_server_mode_enabled" in launcher_source


def _stop_window(window, app):
    for attr in (
        "monitor_timer",
        "scheduler_timer",
        "ui_refresh_timer",
        "beholder_timer",
        "runtime_heartbeat_timer",
    ):
        timer = getattr(window, attr, None)
        if timer and timer.isActive():
            timer.stop()
    window.hide()
    window.deleteLater()
    app.processEvents()


def test_main_table_hides_headers_and_uses_fixed_name_sort(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    icon_requests = []
    monkeypatch.setattr(
        main_window,
        "get_qicon_for_file",
        lambda path, *, icon_size=24, process_id=None: icon_requests.append((path, icon_size, process_id)) or QIcon(),
    )
    processes = [
        ManagedProcess(id="z", name="Zeta", monitoring_path="z.exe", launch_path="z.exe"),
        ManagedProcess(id="a", name="Alpha", monitoring_path="a.exe", launch_path="a.exe"),
        ManagedProcess(id="b", name="Beta", monitoring_path="b.exe", launch_path="b.exe"),
    ]
    window = main_window.MainWindow(_FakeApiClient(processes))
    try:
        window.show()
        app.processEvents()
        window._adjust_window_size_to_content()
        app.processEvents()

        assert not window.process_table.horizontalHeader().isVisible()
        assert not window.process_table.verticalHeader().isVisible()
        assert window.process_table.verticalHeader().width() == 0
        assert not window.process_table.isSortingEnabled()
        assert [
            window.process_table.item(row, window.COL_NAME).text()
            for row in range(window.process_table.rowCount())
        ] == ["Alpha", "Beta", "Zeta"]
        assert [request[2] for request in icon_requests] == ["a", "b", "z"]
        assert {request[1] for request in icon_requests} == {window._TABLE_ICON_LOGICAL_SIZE}
        assert window.process_table.iconSize().width() == window._TABLE_ICON_LOGICAL_SIZE
        assert window.process_table.columnWidth(window.COL_ICON) <= (
            window._TABLE_ICON_LOGICAL_SIZE + window._TABLE_ICON_COLUMN_PADDING
        )
        icon_cell = window.process_table.cellWidget(0, window.COL_ICON)
        assert isinstance(icon_cell, QLabel)
        assert icon_cell.alignment() & Qt.AlignmentFlag.AlignHCenter
        assert icon_cell.alignment() & Qt.AlignmentFlag.AlignVCenter
        assert all(
            window._TABLE_ROW_HEIGHT <= window.process_table.rowHeight(row) <= window._TABLE_ROW_HEIGHT + 4
            for row in range(window.process_table.rowCount())
        )
    finally:
        _stop_window(window, app)


def test_main_table_enables_overflow_scrollbar_instead_of_oversizing_screen(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    long_name = "Extremely Long Game Name " + ("X" * 800)
    window = main_window.MainWindow(
        _FakeApiClient([
            ManagedProcess(id="long", name=long_name, monitoring_path="long.exe", launch_path="long.exe"),
        ])
    )
    try:
        window.show()
        app.processEvents()
        window._adjust_window_size_to_content()
        app.processEvents()

        screen = window.screen() or QApplication.primaryScreen()
        max_width = int(screen.availableGeometry().width() * window._SCREEN_SIZE_RATIO)
        assert window.width() <= max(max_width, window._MIN_WINDOW_WIDTH)
        assert window.process_table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    finally:
        _stop_window(window, app)


def test_restore_window_state_does_not_leave_fixed_size(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(
        _FakeApiClient([
            ManagedProcess(id="a", name="Alpha", monitoring_path="a.exe", launch_path="a.exe"),
        ])
    )
    try:
        window.show()
        app.processEvents()
        window._restore_window_state()
        app.processEvents()

        assert window.maximumWidth() > window.width()
        assert window.maximumHeight() > window.height()
    finally:
        _stop_window(window, app)


def test_web_shortcut_click_uses_runtime_marker(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    shortcut = WebShortcut(
        id="daily",
        name="Daily",
        url="https://example.test",
        refresh_time_str="05:00",
    )
    data_manager = _FakeApiClient([])
    data_manager.web_shortcuts = [shortcut]
    marked = []

    def mark_opened(shortcut_id):
        marked.append(shortcut_id)
        shortcut.last_reset_timestamp = 1778410000.0
        return True

    data_manager.mark_web_shortcut_opened = mark_opened
    window = main_window.MainWindow(data_manager)
    opened = []
    window.open_webpage = lambda url: opened.append(url)
    try:
        window._handle_web_button_clicked(shortcut.id, shortcut.url)

        assert opened == [shortcut.url]
        assert marked == [shortcut.id]
    finally:
        _stop_window(window, app)


def test_resource_icon_label_centers_pixmap_in_fixed_space(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    window = main_window.MainWindow(_FakeApiClient([]))
    icon_path = tmp_path / "resource.png"
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("#5cc8ff"))
    assert pixmap.save(str(icon_path))
    try:
        label = window._create_centered_resource_icon_label(str(icon_path))

        assert label.width() == 18
        assert label.height() == 18
        assert label.alignment() & Qt.AlignmentFlag.AlignHCenter
        assert label.alignment() & Qt.AlignmentFlag.AlignVCenter
        assert label.pixmap() is not None
        assert label.pixmap().width() <= 16
        assert label.pixmap().height() <= 16
    finally:
        _stop_window(window, app)


def test_sidebar_activates_when_running_cache_already_exists_without_monitor_change(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    data_manager = _FakeApiClient([process])
    data_manager.global_settings.sidebar_enabled = True
    data_manager.global_settings.sidebar_mode = SIDEBAR_MODE_GAME
    data_manager.global_settings.hide_on_game = False
    window = main_window.MainWindow(data_manager)
    activated = []

    class _SidebarProbe:
        def activate_for_game(self, process_arg, pid=None, game_start_timestamp=None):
            activated.append((process_arg.id, pid, game_start_timestamp))

        def dispatch_recording_state(self, _state):
            pass

        def deactivate(self):
            raise AssertionError("steady-state running cache should not deactivate")

    try:
        window._sidebar_controller = _SidebarProbe()
        window._is_game_mode_active = False
        window.process_monitor.active_monitored_processes[process.id] = {
            "pid": 4321,
            "exe": process.monitoring_path,
            "start_time_approx": 100.0,
            "session_id": 1,
        }
        window.process_monitor.check_and_update_statuses = lambda: ProcessMonitorTickResult(changed=False)

        window.run_process_monitor_check()

        assert activated == [("game", 4321, None)]
        assert window._is_game_mode_active is True
    finally:
        _stop_window(window, app)


def test_sidebar_controller_can_enable_trigger_after_game_started_with_sidebar_disabled(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(
        sidebar_mode=SIDEBAR_MODE_DISABLED,
        hide_on_game=False,
        sidebar_handle_auto_hide=False,
    )
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    trigger_events = []
    process_updates = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            self.update_calls = []
            trigger_events.append((
                "created",
                kwargs.get("trigger_width_px"),
                kwargs.get("handle_auto_hide"),
            ))

        def start(self):
            trigger_events.append(("start", None))

        def stop(self):
            trigger_events.append(("stop", None))

        def update_settings(self, trigger_y_start, trigger_y_end, cooldown_sec, trigger_width_px=2, handle_auto_hide=True):
            self.update_calls.append((trigger_y_start, trigger_y_end, cooldown_sec, trigger_width_px, handle_auto_hide))
            trigger_events.append(("update", trigger_width_px))

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            process_updates.append(("created", kwargs.get("auto_hide_ms")))

        def update_process(self, process_arg, pid=None, game_start_timestamp=None):
            process_updates.append((process_arg.id, pid, game_start_timestamp))

        def update_auto_hide_ms(self, value):
            process_updates.append(("auto_hide", value))

        def apply_visual_settings(self):
            process_updates.append(("visual", None))

        def refresh_content(self):
            process_updates.append(("refresh", None))

        def slide_out(self):
            process_updates.append(("slide_out", None))

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)

    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)

    assert controller._active_process is process
    assert trigger_events == []

    settings.sidebar_mode = SIDEBAR_MODE_GAME
    settings.sidebar_enabled = True
    controller.apply_settings(settings)

    assert ("created", settings.sidebar_edge_width_px, False) in trigger_events
    assert ("start", None) in trigger_events
    assert ("game", 4321, 100.0) in process_updates


def test_sidebar_controller_always_mode_starts_trigger_without_game(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_ALWAYS, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    trigger_events = []
    sidebar_events = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            trigger_events.append((
                "created",
                kwargs.get("trigger_width_px"),
                kwargs.get("handle_auto_hide"),
            ))

        def start(self):
            trigger_events.append(("start", None))

        def stop(self):
            trigger_events.append(("stop", None))

        def update_settings(self, *args, **kwargs):
            trigger_events.append(("update", kwargs.get("trigger_width_px")))

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            sidebar_events.append(("created", kwargs.get("auto_hide_ms")))

        def update_process(self, *args, **kwargs):
            sidebar_events.append(("update_process", None))

        def update_auto_hide_ms(self, value):
            sidebar_events.append(("auto_hide", value))

        def apply_visual_settings(self):
            sidebar_events.append(("visual", None))

        def refresh_content(self):
            sidebar_events.append(("refresh", None))

        def slide_out(self):
            sidebar_events.append(("slide_out", None))

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)

    controller.apply_settings(settings)
    controller.deactivate()

    assert ("created", settings.sidebar_edge_width_px, True) in trigger_events
    assert trigger_events.count(("start", None)) == 2
    assert ("stop", None) not in trigger_events
    assert ("refresh", None) in sidebar_events


def test_sidebar_settings_dialog_persists_three_state_sidebar_mode(monkeypatch):
    import sys
    import types

    app = _qapp()
    monkeypatch.setitem(
        sys.modules,
        "src.screenshot.key_capture",
        types.SimpleNamespace(vk_to_display_name=lambda vk: f"VK 0x{vk:02X}"),
    )
    from src.gui.sidebar_settings_dialog import SidebarSettingsDialog

    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_ALWAYS, hide_on_game=False)
    dialog = SidebarSettingsDialog(settings)
    try:
        assert dialog._mode_combo.currentData() == SIDEBAR_MODE_ALWAYS
        assert dialog._handle_auto_hide_cb.isChecked() is True

        disabled_index = dialog._mode_combo.findData(SIDEBAR_MODE_DISABLED)
        dialog._mode_combo.setCurrentIndex(disabled_index)
        dialog._handle_auto_hide_cb.setChecked(False)
        dialog._trigger_y_start_spin.setValue(0.85)
        dialog._trigger_y_end_spin.setValue(0.15)
        updated = dialog.get_updated_settings()

        assert updated.sidebar_mode == SIDEBAR_MODE_DISABLED
        assert updated.sidebar_enabled is False
        assert updated.sidebar_handle_auto_hide is False
        assert updated.sidebar_trigger_y_start == 0.15
        assert updated.sidebar_trigger_y_end == 0.85
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_sidebar_controller_stops_trigger_immediately_when_sidebar_disabled(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_GAME, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    trigger_events = []
    sidebar_events = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            trigger_events.append("start")

        def stop(self):
            trigger_events.append("stop")

        def update_settings(self, *args, **kwargs):
            pass

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            self._is_shown = False

        def update_process(self, *args, **kwargs):
            pass

        def update_auto_hide_ms(self, *args, **kwargs):
            pass

        def apply_visual_settings(self):
            pass

        def refresh_content(self):
            pass

        def slide_out(self):
            sidebar_events.append("slide_out")

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)
    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)
    controller._sidebar._is_shown = True

    settings.sidebar_mode = SIDEBAR_MODE_DISABLED
    settings.sidebar_enabled = False
    controller.apply_settings(settings)

    assert trigger_events == ["start", "stop"]
    assert sidebar_events == ["slide_out"]


def test_sidebar_controller_edge_trigger_callback_slides_sidebar_in(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_GAME, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    triggers = []
    sidebar_events = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            self.trigger_callback = kwargs["trigger_callback"]
            triggers.append(self)

        def start(self):
            pass

        def stop(self):
            pass

        def update_settings(self, *args, **kwargs):
            pass

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            pass

        def update_process(self, *args, **kwargs):
            pass

        def update_auto_hide_ms(self, *args, **kwargs):
            pass

        def apply_visual_settings(self):
            pass

        def refresh_content(self):
            pass

        def slide_out(self):
            sidebar_events.append("slide_out")

        def slide_in(self):
            sidebar_events.append("slide_in")

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)
    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)

    assert len(triggers) == 1

    triggers[0].trigger_callback()

    assert sidebar_events == ["slide_in"]


def test_sidebar_controller_hides_handle_until_sidebar_finishes_hiding(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(sidebar_mode=SIDEBAR_MODE_GAME, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    events = []
    triggers = []
    sidebars = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            self.trigger_callback = kwargs["trigger_callback"]
            triggers.append(self)

        def start(self):
            events.append("trigger:start")

        def stop(self):
            events.append("trigger:stop")

        def update_settings(self, *args, **kwargs):
            pass

    class _SidebarProbe:
        _is_shown = False

        def __init__(self, *args, **kwargs):
            self._is_shown = False
            self._on_hidden = kwargs.get("on_hidden")
            sidebars.append(self)

        def update_process(self, *args, **kwargs):
            pass

        def update_auto_hide_ms(self, *args, **kwargs):
            pass

        def apply_visual_settings(self):
            pass

        def refresh_content(self):
            pass

        def slide_out(self):
            events.append("sidebar:slide_out")
            self._is_shown = False
            if self._on_hidden is not None:
                self._on_hidden()

        def slide_in(self):
            events.append("sidebar:slide_in")
            self._is_shown = True

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)
    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)

    assert events == ["trigger:start"]
    assert len(triggers) == 1

    triggers[0].trigger_callback()

    assert events == ["trigger:start", "trigger:stop", "sidebar:slide_in"]
    assert sidebars[0]._is_shown is True

    sidebars[0].slide_out()

    assert events == [
        "trigger:start",
        "trigger:stop",
        "sidebar:slide_in",
        "sidebar:slide_out",
        "trigger:start",
    ]


def test_main_window_no_longer_schedules_foreground_focus():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")

    assert "focus_process_window" not in source
    assert "_schedule_focus_after_launch" not in source


def test_main_window_reapplies_sidebar_startup_mode_after_native_show():
    source = Path("src/gui/main_window.py").read_text(encoding="utf-8")
    show_event_source = source[source.index("    def showEvent"):source.index("    def _on_monitor_timer_tick")]

    assert "_apply_sidebar_startup_mode" in show_event_source


def test_edge_trigger_visible_handle_uses_direct_paint_path():
    source = Path("src/gui/sidebar/edge_trigger_window.py").read_text(encoding="utf-8")

    assert "def paintEvent" in source
    assert "QPainter(self)" in source
    assert "_HANDLE_COLOR" in source
    assert "_HANDLE_GRIP_COLOR" in source


def test_edge_trigger_auto_hide_reveals_from_configured_edge_zone(monkeypatch):
    app = _qapp()
    cursor = {"pos": QPoint(0, 0)}

    class _CursorProbe:
        @staticmethod
        def pos():
            return cursor["pos"]

    monkeypatch.setattr(edge_trigger_module, "QCursor", _CursorProbe)

    edge = EdgeTriggerWindow(
        trigger_callback=lambda: None,
        trigger_y_start=0.25,
        trigger_y_end=0.5,
        trigger_width_px=12,
    )
    try:
        trigger_geometry = edge._trigger_geometry(edge._screen)
        assert trigger_geometry.height() < edge._screen.geometry().height()
        assert trigger_geometry.width() == 12

        edge.start()
        app.processEvents()

        assert edge._handle_visible is False
        assert edge._poll_timer.isActive()
        assert edge.geometry() == trigger_geometry
        assert edge.windowFlags() & Qt.WindowType.WindowTransparentForInput

        cursor["pos"] = trigger_geometry.center()
        edge._poll_cursor()
        app.processEvents()

        assert edge._handle_visible is True
        assert edge.geometry() == edge._handle_geometry(edge._screen)
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput

        cursor["pos"] = edge._screen.geometry().center() - QPoint(100, 0)
        edge._poll_cursor()
        assert edge._handle_hide_timer.isActive()

        edge._handle_hide_timer.timeout.emit()
        app.processEvents()

        assert edge._handle_visible is False
        assert edge.geometry() == trigger_geometry
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_starts_with_always_visible_borderless_click_handle():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        assert edge.windowFlags() & Qt.WindowType.WindowTransparentForInput

        edge.start()
        app.processEvents()

        assert edge._handle_visible is True
        assert edge._poll_timer.isActive()
        assert edge.geometry() == edge._handle_geometry(edge._screen)
        assert edge.geometry().width() > 2
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert edge.windowOpacity() == 1.0
        assert "background: transparent" in edge.styleSheet()
        assert "border: none" in edge.styleSheet()

        rendered = QImage(edge.width(), edge.height(), QImage.Format.Format_ARGB32)
        rendered.fill(Qt.GlobalColor.transparent)
        edge.render(rendered)
        assert any(
            rendered.pixelColor(x, y).alpha() > 0
            for x in range(rendered.width())
            for y in range(rendered.height())
        )
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_click_invokes_callback_without_hiding_handle():
    app = _qapp()
    triggered = []
    edge = EdgeTriggerWindow(
        trigger_callback=lambda: triggered.append(True),
        trigger_width_px=2,
        handle_auto_hide=False,
    )
    try:
        edge.start()
        app.processEvents()

        class _Click:
            def button(self):
                return Qt.MouseButton.LeftButton

            def accept(self):
                pass

        edge.mousePressEvent(_Click())
        edge.mousePressEvent(_Click())
        assert triggered == [True]
        assert edge._handle_visible is True
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_applies_handle_geometry_after_input_flag_change(monkeypatch):
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2)
    original_set_transparent = edge._set_transparent_for_input
    flag_calls = []
    try:
        expected_handle_geometry = edge._handle_geometry(edge._screen)

        def _resetting_flag_change(enabled):
            flag_calls.append(enabled)
            original_set_transparent(enabled)
            if enabled is False:
                # QWidget.setWindowFlag() may hide/recreate a top-level widget;
                # simulate a platform resetting geometry during that transition.
                edge.setGeometry(0, 0, 1, 1)

        monkeypatch.setattr(edge, "_set_transparent_for_input", _resetting_flag_change)

        edge._show_handle()
        app.processEvents()

        assert flag_calls == [False]
        assert edge.geometry() == expected_handle_geometry
        assert edge._handle_visible is True
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_poll_restores_always_visible_handle_without_cursor_gate():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        edge.start()
        app.processEvents()
        edge._hide_handle()
        assert edge._handle_visible is False

        edge._poll_cursor()

        assert edge._handle_visible is True
        assert edge.geometry() == edge._handle_geometry(edge._screen)
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_poll_restores_window_if_native_hide_keeps_handle_state():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        edge.start()
        app.processEvents()
        edge.hide()
        assert edge._handle_visible is True

        edge._poll_cursor()
        app.processEvents()

        assert edge.isVisible()
        assert edge.geometry() == edge._handle_geometry(edge._screen)
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_start_uses_screen_handle_even_if_hidden_geometry_stale():
    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2, handle_auto_hide=False)
    try:
        edge._hide_handle()
        edge.setGeometry(0, 0, 1, 1)

        edge.start()
        app.processEvents()

        assert edge._handle_visible is True
        assert edge.geometry() == edge._handle_geometry(edge._screen)
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_sidebar_frame_css_remains_borderless():
    source = Path("src/gui/sidebar/sidebar_widget.py").read_text(encoding="utf-8")

    assert "border-left:" not in source
    assert "border: none;" in source


def test_process_icon_prefers_process_id_cache_without_existing_exe(monkeypatch, tmp_path):
    app = _qapp()
    cached_png = tmp_path / "cached-icon.png"
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#2a82da"))
    assert pixmap.save(str(cached_png))

    import src.api.dashboard.icons as icon_cache
    from src.utils.process import get_qicon_for_file

    monkeypatch.setattr(
        icon_cache,
        "get_icon_for_size",
        lambda process_id, requested_size: cached_png if process_id == "game-id" else None,
    )
    monkeypatch.setattr(
        icon_cache,
        "extract_icon_from_exe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache hit should not extract")),
    )

    icon = get_qicon_for_file(str(tmp_path / "missing.exe"), icon_size=32, process_id="game-id")

    assert not icon.isNull()
    app.processEvents()


def test_restore_suspends_runtime_timers_and_monitor_cache():
    import types
    import src.gui.main_window as main_window

    class FakeTimer:
        def __init__(self):
            self.active = True
            self.start_calls = []
            self.stop_calls = 0

        def isActive(self):
            return self.active

        def stop(self):
            self.active = False
            self.stop_calls += 1

        def start(self, interval):
            self.active = True
            self.start_calls.append(interval)

    monitor_timer = FakeTimer()
    scheduler_timer = FakeTimer()
    heartbeat_timer = FakeTimer()
    ui_timer = FakeTimer()
    process_monitor = types.SimpleNamespace(active_monitored_processes={"game-a": {"session_id": 1}})
    window = types.SimpleNamespace(
        process_monitor=process_monitor,
        monitor_timer=monitor_timer,
        scheduler_timer=scheduler_timer,
        runtime_heartbeat_timer=heartbeat_timer,
        ui_refresh_timer=ui_timer,
        _UI_REFRESH_INTERVAL_MS=1000,
    )

    main_window.MainWindow._suspend_runtime_after_beholder_restore(window)
    main_window.MainWindow._ensure_timers_running(window)

    assert window._beholder_restore_runtime_suspended is True
    assert process_monitor.active_monitored_processes == {}
    assert monitor_timer.stop_calls == 1
    assert scheduler_timer.stop_calls == 1
    assert heartbeat_timer.stop_calls == 1
    assert monitor_timer.start_calls == []
    assert scheduler_timer.start_calls == []


def test_windows_title_bar_color_noops_off_windows(monkeypatch):
    import src.utils.windows as windows

    monkeypatch.setattr(windows.os, "name", "posix")

    assert windows.apply_windows_title_bar_color(
        1234,
        caption_color=(53, 53, 53),
        text_color=(220, 220, 220),
        dark_mode=True,
    ) is False
