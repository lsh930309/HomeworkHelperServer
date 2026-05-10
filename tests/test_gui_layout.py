import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication

from src.data.data_models import GlobalSettings, ManagedProcess
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

    def get_web_shortcut_by_id(self, _shortcut_id):
        return None

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
