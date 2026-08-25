import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QToolButton, QVBoxLayout, QWidget
from shiboken6 import Shiboken

from src.data.data_models import ManagedProcess
from src.gui.presentation import PresentationController, resolve_ui_renderer
from src.gui.qt_runtime import binding_diagnostics, is_qobject_valid, require_object_thread
from src.gui.sidebar.sidebar_widget import SidebarWidget
from src.gui.volume_panel import _MUTE_BTN_STYLE
from src.gui.widgets_style import (
    CapsuleProgressBar,
    apply_modern_widgets_style,
    apply_sidebar_widgets_style,
    apply_widgets_palette,
    widgets_theme_tokens,
)


def _qapp():
    return QApplication.instance() or QApplication([])


def test_runtime_reports_only_pyside6_binding():
    diagnostics = binding_diagnostics("widgets")
    assert diagnostics["ui_binding"] == "pyside6"
    assert diagnostics["binding_version"].startswith("6.11.")
    assert diagnostics["qt_version"].startswith("6.11.")
    assert diagnostics["ui_variant"] == "newgui-2nd"


def test_qobject_validity_and_thread_guard_follow_shiboken_lifetime():
    _qapp()
    owner = QObject()
    assert is_qobject_valid(owner)
    require_object_thread(owner, "test")
    Shiboken.delete(owner)
    assert not is_qobject_valid(owner)
    with pytest.raises(RuntimeError, match="no longer valid"):
        require_object_thread(owner, "test")


def test_renderer_selection_defaults_to_widgets_and_accepts_qml(monkeypatch):
    monkeypatch.delenv("HH_UI_RENDERER", raising=False)
    assert resolve_ui_renderer([]) == "widgets"
    assert resolve_ui_renderer(["--ui-renderer=qml"]) == "qml"
    monkeypatch.setenv("HH_UI_RENDERER", "qml")
    assert resolve_ui_renderer([]) == "qml"
    with pytest.raises(ValueError, match="지원하지 않는"):
        resolve_ui_renderer(["--ui-renderer=web"])


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


def test_sidebar_mute_button_uses_blue_checked_state_and_unclipped_focus_border():
    app = _qapp()
    root = QWidget()
    layout = QVBoxLayout(root)
    button = QPushButton(root)
    button.setProperty("hhRole", "muteToggle")
    button.setCheckable(True)
    layout.addWidget(button)
    apply_sidebar_widgets_style(root, dark=True)
    root.show()
    app.processEvents()

    button.setChecked(True)
    button.clearFocus()
    button.update()
    app.processEvents()
    checked = _button_background(button)
    assert checked.blue() > checked.red()
    assert checked.blue() > checked.green()
    assert button.size().toTuple() == (22, 22)
    assert button.size() == button.sizeHint()

    button.setDown(True)
    button.update()
    app.processEvents()
    assert _button_background(button) != checked
    button.setDown(False)
    button.setFocus()
    button.update()
    app.processEvents()
    focused = button.grab().toImage()
    edge_points = (
        (focused.width() // 2, 0),
        (focused.width() - 1, focused.height() // 2),
        (focused.width() // 2, focused.height() - 1),
        (0, focused.height() // 2),
    )
    # Fractional DPI에서는 오른쪽/아래 1px이 focus 색과 배경의 안티앨리어싱 혼합색입니다.
    assert all(
        focused.pixelColor(x, y).lightness() > checked.lightness()
        for x, y in edge_points
    )
    root.close()


def test_sidebar_volume_row_does_not_mask_checked_mute_background(monkeypatch):
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
        global_settings=SimpleNamespace(sidebar_volume_section_enabled=True),
        managed_processes=[process],
    )
    sidebar = SidebarWidget(data_manager)
    sidebar._refresh_volumes_list()
    sidebar.show()
    app.processEvents()

    mute_button = next(
        button
        for button in sidebar.findChildren(QPushButton)
        if button.property("hhRole") == "muteToggle"
    )
    checked = _button_background(mute_button)
    assert mute_button.isChecked()
    assert checked.blue() > checked.red()
    assert checked.blue() > checked.green()
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
        def __init__(self):
            super().__init__()
            self.observed = None

        @Slot()
        def receive(self):
            self.observed = QThread.currentThread()

    emitter = Emitter()
    receiver = Receiver()
    emitter.moveToThread(thread)
    emitter.fired.connect(receiver.receive)
    thread.started.connect(emitter.emit_from_worker)
    thread.start()
    deadline = 200
    while receiver.observed is None and deadline:
        app.processEvents()
        QThread.msleep(1)
        deadline -= 1
    thread.quit()
    assert thread.wait(1_000)
    assert receiver.observed == receiver.thread()


class _RefreshTimer(QObject):
    timeout = Signal()


class _FakeWindow(QObject):
    request_table_refresh_signal = Signal()

    def __init__(self):
        super().__init__()
        self.ui_refresh_timer = _RefreshTimer(self)
        self.data_manager = SimpleNamespace(
            managed_processes=[],
            global_settings=SimpleNamespace(),
        )
        self.scheduler = SimpleNamespace(determine_process_visual_status=lambda *_args: "대기")
        self.presentation = None

    def _calculate_progress_percentage(self, *_args):
        return 0.0, ""

    def _is_effective_dark_theme(self):
        return False

    def set_presentation_window(self, window, facade=None):
        self.presentation = (window, facade)

    def hide(self):
        return None


def test_qml_candidate_loads_as_independent_quick_window():
    app = _qapp()
    owner = _FakeWindow()
    controller = PresentationController(owner, "qml")
    assert controller.engine is not None
    assert controller.window is not owner
    assert owner.presentation[0] is controller.window
    controller.show()
    app.processEvents()
    assert controller.window.isVisible()
    controller.window.hide()
    controller.shutdown()
