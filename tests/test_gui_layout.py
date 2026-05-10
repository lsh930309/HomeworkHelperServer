import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication

from src.data.data_models import GlobalSettings, ManagedProcess, WebShortcut
from src.core.process_monitor import ProcessMonitorTickResult
from src.gui.sidebar.edge_trigger_window import EdgeTriggerWindow
from src.utils.window_focus import focus_process_window


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
            window._TABLE_ICON_LOGICAL_SIZE + window._TABLE_ICON_COLUMN_PADDING + 8
        )
        assert all(
            window.process_table.rowHeight(row) >= window._TABLE_ROW_HEIGHT
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


def test_sidebar_activates_when_running_cache_already_exists_without_monitor_change(monkeypatch, tmp_path):
    app = _qapp()
    main_window = _patch_main_window_deps(monkeypatch, tmp_path)
    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    data_manager = _FakeApiClient([process])
    data_manager.global_settings.sidebar_enabled = True
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
    settings = GlobalSettings(sidebar_enabled=False, hide_on_game=False)
    data_manager = type("DataManagerProbe", (), {"global_settings": settings})()
    trigger_events = []
    process_updates = []

    class _TriggerProbe:
        def __init__(self, *args, **kwargs):
            self.update_calls = []
            trigger_events.append(("created", kwargs.get("trigger_width_px")))

        def start(self):
            trigger_events.append(("start", None))

        def stop(self):
            trigger_events.append(("stop", None))

        def update_settings(self, trigger_y_start, trigger_y_end, cooldown_sec, trigger_width_px=2):
            self.update_calls.append((trigger_y_start, trigger_y_end, cooldown_sec, trigger_width_px))
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

    settings.sidebar_enabled = True
    controller.apply_settings(settings)

    assert ("created", settings.sidebar_edge_width_px) in trigger_events
    assert ("start", None) in trigger_events
    assert ("game", 4321, 100.0) in process_updates


def test_sidebar_controller_stops_trigger_immediately_when_sidebar_disabled(monkeypatch):
    _qapp()
    import src.gui.sidebar.sidebar_controller as controller_module

    process = ManagedProcess(id="game", name="Running Game", monitoring_path="game.exe", launch_path="game.exe")
    settings = GlobalSettings(sidebar_enabled=True, hide_on_game=False)
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
        _is_shown = True

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

        def set_on_start_recording(self, _callback):
            pass

    monkeypatch.setattr(controller_module, "EdgeTriggerWindow", _TriggerProbe)
    monkeypatch.setattr(controller_module, "SidebarWidget", _SidebarProbe)

    controller = controller_module.SidebarController(data_manager)
    controller.activate_for_game(process, pid=4321, game_start_timestamp=100.0)

    settings.sidebar_enabled = False
    controller.apply_settings(settings)

    assert trigger_events == ["start", "stop"]
    assert sidebar_events == ["slide_out"]


def test_focus_helper_noops_off_windows(monkeypatch):
    import src.utils.window_focus as window_focus

    monkeypatch.setattr(window_focus.sys, "platform", "darwin")
    monkeypatch.setattr(
        window_focus,
        "find_process_ids_by_executable",
        lambda _path: (_ for _ in ()).throw(AssertionError("should return before process scan")),
    )

    assert focus_process_window(pid=1234, executable_path="/Applications/Game.app") is False


def test_edge_trigger_exposes_borderless_click_handle():
    app = _qapp()
    triggered = []
    edge = EdgeTriggerWindow(trigger_callback=lambda: triggered.append(True), trigger_width_px=2)
    try:
        assert edge.windowFlags() & Qt.WindowType.WindowTransparentForInput

        edge._show_handle()
        app.processEvents()

        assert edge._handle_visible is True
        assert edge.geometry().width() > 2
        assert not edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert "border: none" in edge.styleSheet()

        class _Click:
            def button(self):
                return Qt.MouseButton.LeftButton

            def accept(self):
                pass

        edge.mousePressEvent(_Click())
        assert triggered == [True]
        assert edge._handle_visible is False
        assert edge.windowFlags() & Qt.WindowType.WindowTransparentForInput
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_edge_trigger_polls_only_inside_the_edge_strip(monkeypatch):
    import src.gui.sidebar.edge_trigger_window as edge_module

    app = _qapp()
    edge = EdgeTriggerWindow(trigger_callback=lambda: None, trigger_width_px=2)
    try:
        edge._hide_handle()
        geo = edge.geometry()
        monkeypatch.setattr(
            edge_module,
            "QCursor",
            type("FakeCursor", (), {"pos": staticmethod(lambda: QPoint(geo.right() + 100, geo.center().y()))}),
        )
        edge._poll_cursor()
        assert edge._handle_visible is False

        monkeypatch.setattr(
            edge_module,
            "QCursor",
            type("FakeCursor", (), {"pos": staticmethod(lambda: QPoint(geo.center().x(), geo.center().y()))}),
        )
        edge._poll_cursor()
        assert edge._handle_visible is True
    finally:
        edge.stop()
        edge.deleteLater()
        app.processEvents()


def test_sidebar_frame_css_remains_borderless():
    source = Path("src/gui/sidebar/sidebar_widget.py").read_text(encoding="utf-8")

    assert "border-left:" not in source
    assert "border: none;" in source


def test_window_focus_declares_user32_signatures():
    source = Path("src/utils/window_focus.py").read_text(encoding="utf-8")

    for api_name in [
        "EnumWindows",
        "IsWindowVisible",
        "GetWindowThreadProcessId",
        "AllowSetForegroundWindow",
        "ShowWindow",
        "BringWindowToTop",
        "SetForegroundWindow",
    ]:
        assert f"user32.{api_name}.argtypes" in source
        assert f"user32.{api_name}.restype" in source


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


def test_windows_title_bar_color_noops_off_windows(monkeypatch):
    import src.utils.windows as windows

    monkeypatch.setattr(windows.os, "name", "posix")

    assert windows.apply_windows_title_bar_color(
        1234,
        caption_color=(53, 53, 53),
        text_color=(220, 220, 220),
        dark_mode=True,
    ) is False
