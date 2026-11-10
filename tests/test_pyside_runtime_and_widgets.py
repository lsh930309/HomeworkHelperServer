import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QEventLoop, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QTabBar, QToolButton, QVBoxLayout, QWidget
from shiboken6 import Shiboken

from src.data.data_models import ManagedProcess
from src.gui.power_events import PBT_APMRESUMEAUTOMATIC, WM_POWERBROADCAST, WindowsPowerEventFilter
from src.gui.qt_runtime import binding_diagnostics, is_qobject_valid, require_object_thread
from src.gui.sidebar.sidebar_widget import SidebarWidget
from src.gui.sidebar.controls import VolumeDial
from src.gui.volume_panel import _MUTE_BTN_STYLE
from src.gui.widgets_style import (
    CapsuleProgressBar,
    GameIconLabel,
    apply_modern_widgets_style,
    apply_sidebar_widgets_style,
    apply_widgets_palette,
    widgets_theme_tokens,
)


@pytest.mark.parametrize("size", [30, 32, 48])
@pytest.mark.parametrize("source_ratio", [1, 2])
def test_common_game_icon_slot_clips_source_pixels_and_centers_in_larger_cell(size, source_ratio):
    app = _qapp()
    root = QWidget()
    root.resize(80, 80)
    root.setStyleSheet("background: #102030;")
    label = GameIconLabel(size, root)
    label.setGeometry(0, 0, 80, 80)
    source = QPixmap(size * 2 * source_ratio, size * 2)
    source.fill(QColor("#f02030"))
    label.setPixmap(source)
    root.show()
    app.processEvents()
    image = root.grab().toImage()
    left = (80 - size) // 2
    assert image.pixelColor(40, 40) == QColor("#f02030")
    assert image.pixelColor(left, left) == QColor("#102030")
    assert image.pixelColor(0, 0) == QColor("#102030")
    assert label.pixmap().size() == source.size()  # 원본을 잘라 저장하지 않는다.
    root.close()


def _qapp():
    return QApplication.instance() or QApplication([])


def test_runtime_reports_only_pyside6_binding():
    diagnostics = binding_diagnostics()
    assert diagnostics["ui_binding"] == "pyside6"
    assert diagnostics["binding_version"].startswith("6.11.")
    assert diagnostics["qt_version"].startswith("6.11.")
    assert diagnostics["ui_variant"] == "newgui-2nd"
    assert diagnostics["ui_renderer"] == "widgets"


def test_qobject_validity_and_thread_guard_follow_shiboken_lifetime():
    _qapp()
    owner = QObject()
    assert is_qobject_valid(owner)
    require_object_thread(owner, "test")
    Shiboken.delete(owner)
    assert not is_qobject_valid(owner)
    with pytest.raises(RuntimeError, match="no longer valid"):
        require_object_thread(owner, "test")


def test_modern_widgets_style_marks_surface_and_primary_action():
    _qapp()
    window = QMainWindow()
    central = QWidget(window)
    central.setLayout(QVBoxLayout())
    window.setCentralWidget(central)
    window.add_game_button = QPushButton("새 게임 추가", central)
    central.layout().addWidget(window.add_game_button)
    apply_modern_widgets_style(window, dark=False)
    assert central.objectName() == "hhMainSurface"
    assert window.add_game_button.property("hhRole") == "primaryAction"
    assert "#f3f3f3" in window.styleSheet()


def test_widgets_theme_uses_neutral_accents_and_stable_button_padding():
    dark = widgets_theme_tokens(True)
    light = widgets_theme_tokens(False)
    assert dark["accent"] == "#2b2b2f"
    assert light["accent"] == "#dedee2"

    _qapp()
    window = QMainWindow()
    central = QWidget(window)
    central.setLayout(QVBoxLayout())
    window.setCentralWidget(central)
    window.add_game_button = QPushButton("새 게임 추가", central)
    central.layout().addWidget(window.add_game_button)
    apply_modern_widgets_style(window, dark=True)
    style = window.styleSheet()
    assert "QPushButton:pressed" in style
    assert "background: #3a3a3e" in style
    assert "padding: 0px 8px" in style
    assert "#6ea8fe" not in style
    assert "#2563eb" not in style


def _button_background(button: QPushButton | QToolButton) -> QColor:
    image = button.grab().toImage()
    dpr = image.devicePixelRatio()
    x = min(round(4 * dpr), image.width() - 1)
    y = min(round(4 * dpr), image.height() - 1)
    return image.pixelColor(x, y)


@pytest.mark.parametrize(
    ("role_property", "role_value"),
    [
        (None, None),
        ("hhRole", "primaryAction"),
        ("hhRole", "iconAction"),
        ("hhState", "success"),
        ("hhState", "danger"),
    ],
)
def test_main_button_roles_render_distinct_pressed_feedback(role_property, role_value):
    app = _qapp()
    window = QMainWindow()
    central = QWidget(window)
    layout = QVBoxLayout(central)
    window.setCentralWidget(central)
    button = QPushButton("확인", central)
    if role_property is not None:
        button.setProperty(role_property, role_value)
    layout.addWidget(button)
    apply_widgets_palette(dark=True)
    apply_modern_widgets_style(window, dark=True)
    window.show()
    app.processEvents()

    normal = _button_background(button)
    button.setDown(True)
    button.update()
    app.processEvents()
    pressed = _button_background(button)
    button.setDown(False)
    button.update()
    app.processEvents()

    assert pressed != normal
    assert _button_background(button) == normal
    if role_value == "iconAction":
        assert button.size().toTuple() == (30, 30)
        assert button.size() == button.sizeHint()
    window.close()


def test_checked_tool_button_keeps_pressed_feedback():
    app = _qapp()
    window = QMainWindow()
    central = QWidget(window)
    layout = QVBoxLayout(central)
    window.setCentralWidget(central)
    button = QToolButton(central)
    button.setCheckable(True)
    button.setChecked(True)
    layout.addWidget(button)
    apply_widgets_palette(dark=True)
    apply_modern_widgets_style(window, dark=True)
    window.show()
    app.processEvents()

    checked = _button_background(button)
    button.setDown(True)
    button.update()
    app.processEvents()

    assert _button_background(button) != checked
    window.close()


@pytest.mark.parametrize("checked", [False, True])
def test_volume_popover_mute_button_renders_pressed_feedback(checked):
    app = _qapp()
    button = QPushButton()
    button.setCheckable(True)
    button.setChecked(checked)
    button.setFixedSize(28, 28)
    button.setStyleSheet(_MUTE_BTN_STYLE)
    button.show()
    app.processEvents()

    normal = _button_background(button)
    button.setDown(True)
    button.update()
    app.processEvents()

    assert _button_background(button) != normal
    button.close()


@pytest.mark.parametrize("role", ["danger", "primaryAction", "folderAction"])
def test_sidebar_button_roles_render_distinct_pressed_feedback(role):
    app = _qapp()
    root = QWidget()
    layout = QVBoxLayout(root)
    button = QPushButton("동작", root)
    button.setProperty("hhRole", role)
    layout.addWidget(button)
    apply_sidebar_widgets_style(root, dark=True)
    root.show()
    app.processEvents()

    normal = _button_background(button)
    button.setDown(True)
    button.update()
    app.processEvents()

    assert _button_background(button) != normal
    root.close()


@pytest.mark.parametrize("selected", [0, 1])
def test_sidebar_gallery_tabs_have_button_like_rounded_corners_and_clear_gap(selected):
    app = _qapp()
    root = QWidget()
    root.setFixedWidth(280)
    palette = root.palette()
    palette.setColor(root.backgroundRole(), QColor("#0f0f10"))
    root.setPalette(palette)
    root.setAutoFillBackground(True)
    layout = QVBoxLayout(root)
    tabs = QTabBar()
    tabs.setExpanding(True)
    tabs.setDrawBase(False)
    tabs.addTab("스크린샷")
    tabs.addTab("녹화")
    tabs.setCurrentIndex(selected)
    layout.addWidget(tabs)
    apply_sidebar_widgets_style(root, dark=True)
    root.show()
    app.processEvents()
    image = tabs.grab().toImage()
    ratio = image.devicePixelRatio()
    def color(x, y):
        return image.pixelColor(round(x * ratio), round(y * ratio))
    gap = round(root.width() * 0.012)
    for index in (0, 1):
        rect = tabs.tabRect(index)
        left, right = rect.left(), rect.right() - (gap if index == 0 else 0)
        inside = color(left + 8, rect.top() + 2)
        assert all(color(x, y) != inside for x, y in (
            (left, rect.top()), (right, rect.top()), (left, rect.bottom()), (right, rect.bottom()),
        ))
    first = tabs.tabRect(0)
    assert color(first.right() - 1, first.center().y()) == color(first.left(), first.top())
    assert tabs.currentIndex() == selected
    root.close()


def test_sidebar_round_volume_keeps_checked_state_and_stable_size():
    app = _qapp()
    dial = VolumeDial(42)
    dial.setChecked(True)
    dial.show()
    app.processEvents()
    assert dial.isChecked() and dial.is_silent()
    assert dial.size().toTuple() == (42, 42)
    assert not dial.grab().isNull()
    dial.close()


def test_sidebar_volume_row_preserves_saved_manual_mute_in_round_dial(monkeypatch):
    from src.gui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "INSTANCE", None)
    app = _qapp()
    process = ManagedProcess(
        id="game",
        name="Game",
        monitoring_path="game.exe",
        launch_path="game.exe",
        default_muted=True,
    )
    data_manager = SimpleNamespace(
        global_settings=SimpleNamespace(sidebar_volume_section_enabled=True, screenshot_enabled=False, obs_watch_output_dir=False),
        managed_processes=[process],
    )
    sidebar = SidebarWidget(data_manager)
    monkeypatch.setattr(sidebar, "_load_icon_async", lambda *_args: None)
    sidebar._refresh_games()
    sidebar.show()
    app.processEvents()

    dial = sidebar.findChild(VolumeDial)
    assert dial.isChecked() and dial.is_silent()
    assert process.default_muted is True
    assert not dial.grab().isNull()
    assert sidebar.cleanup(deadline_ms=200)
    sidebar.close()


@pytest.mark.parametrize(
    ("value", "filled_x", "track_x"),
    [
        (0, None, 2),
        (1, 2, 6),
        (10, 2, 6),
        (500, 25, 55),
        (1000, 98, None),
    ],
)
def test_capsule_progress_bar_keeps_round_minimum_fill(value, filled_x, track_x):
    app = _qapp()
    apply_widgets_palette(dark=True)
    bar = CapsuleProgressBar()
    bar.setRange(0, 1000)
    bar.setProperty("hhBucket", "low")
    bar.resize(100, 6)
    bar.setValue(value)
    bar.show()
    app.processEvents()
    image = bar.grab().toImage()
    tokens = widgets_theme_tokens(True)
    dpr = image.devicePixelRatio()

    def logical_pixel(x: int, y: int) -> QColor:
        return image.pixelColor(
            min(round(x * dpr), image.width() - 1),
            min(round(y * dpr), image.height() - 1),
        )

    if filled_x is not None:
        assert logical_pixel(filled_x, 3) == QColor(tokens["success"])
    if track_x is not None:
        assert logical_pixel(track_x, 3) == QColor(tokens["surface"])
    bar.close()


def test_capsule_progress_bar_uses_dark_track_under_real_main_qss():
    app = _qapp()
    window = QMainWindow()
    central = QWidget(window)
    layout = QVBoxLayout(central)
    window.setCentralWidget(central)
    bar = CapsuleProgressBar(central)
    bar.setRange(0, 1000)
    bar.setValue(500)
    bar.setFixedWidth(100)
    layout.addWidget(bar)
    apply_widgets_palette(dark=True)
    apply_modern_widgets_style(window, dark=True)
    window.show()
    app.processEvents()

    image = bar.grab().toImage()
    dpr = image.devicePixelRatio()
    track = image.pixelColor(
        min(round(80 * dpr), image.width() - 1),
        min(round(3 * dpr), image.height() - 1),
    )
    expected = QColor(widgets_theme_tokens(True)["surface"])
    assert track == expected
    assert track.lightness() < QColor(widgets_theme_tokens(True)["surface_raised"]).lightness()
    window.close()


def test_slot_receiver_runs_in_its_qobject_thread():
    app = _qapp()
    thread = QThread()

    class Emitter(QObject):
        fired = Signal()

        @Slot()
        def emit_from_worker(self):
            self.fired.emit()

    class Receiver(QObject):
        received = Signal()

        def __init__(self):
            super().__init__()
            self.observed = None

        @Slot()
        def receive(self):
            self.observed = QThread.currentThread()
            self.received.emit()

    emitter = Emitter()
    receiver = Receiver()
    emitter.moveToThread(thread)
    emitter.fired.connect(receiver.receive)
    received_loop = QEventLoop()
    receiver.received.connect(received_loop.quit)
    thread.started.connect(emitter.emit_from_worker)
    try:
        thread.start()
        if receiver.observed is None:
            QTimer.singleShot(5_000, received_loop.quit)
            received_loop.exec()
        assert receiver.observed is not None
    finally:
        thread.quit()
        assert thread.wait(1_000)
    assert receiver.observed == receiver.thread()


@pytest.mark.parametrize("event_type", [
    QByteArray(b"windows_generic_MSG"), b"windows_generic_MSG",
    bytearray(b"windows_dispatcher_msg"), "windows_dispatcher_msg",
])
def test_pyside_native_power_event_dispatches_resume(event_type):
    observed = []
    event_filter = WindowsPowerEventFilter(
        observed.append,
        decoder=lambda _message: (WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC),
    )
    assert event_filter.nativeEventFilter(event_type, object()) == (False, 0)
    assert len(observed) == 1


def test_tray_and_activation_restore_the_same_widgets_window():
    from src.gui.main_window import MainWindow
    from src.gui.tray_manager import TrayManager

    app = _qapp()

    class WidgetsWindow(QMainWindow):
        activate_and_show = MainWindow.activate_and_show

    window = WidgetsWindow()
    tray = TrayManager(window)
    window.show()
    app.processEvents()
    tray.hide_window_to_tray()
    assert not window.isVisible()
    assert not app.quitOnLastWindowClosed()
    tray.toggle_window_visibility()
    app.processEvents()
    assert window.isVisible()
    assert tray.main_window is window
    assert not hasattr(window, "_presentation_window")
    tray.hide_tray_icon()
    window.close()
